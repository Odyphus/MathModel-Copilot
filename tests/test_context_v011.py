"""Independent review B: a Context is a complete revision projection, not a seal."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_copilot_runtime import make_project
from copilot_context import acknowledge, build_context, project_status
from copilot_store import ConflictError, IntegrityError, Store, digest, state_digest, state_at_revision


def reseal(context):
    context["common_hash"] = digest(context["common"])
    context.pop("context_id", None)
    context["context_id"] = digest(context)
    return context


class ContextProjectionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root)
        self.rt.task(self.rev(), "T-context", {
            "title": "Implement and check the scoped calculation", "role": "coder",
            "requirements": ["REQ-Q1-001"],
            "dependencies": [self.ids["params"], self.ids["code"]],
        })

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def context(self, **kwargs):
        return build_context(self.root, role="coder", member="member_2", **kwargs)

    def receive(self, context):
        return acknowledge(self.root, self.rev(), context, member="member_2", action="received")

    def assert_rejected_without_write(self, context):
        before = self.rt.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.receive(reseal(context))
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_review_B_resealed_readiness_and_completion_forgery_is_rejected(self):
        context = self.context()
        self.assertFalse(context["common"]["requirements"]["complete"])
        self.assertFalse(context["common"]["submission"]["ready"])
        context["common"]["blockers"] = []
        context["common"]["submission"].update(ready=True, blockers=[])
        context["common"]["requirements"].update(complete=True, verified=context["common"]["requirements"]["total"])
        self.assert_rejected_without_write(context)

    def mutations(self):
        def drop_object(context):
            context["objects"].pop(self.ids["model"])
        return {
            "common_problem": lambda c: c["common"]["problem"].update(team_size=999),
            "common_competition": lambda c: c["common"].update(competition="forged"),
            "navigation_stage": lambda c: c["common"].update(navigation_stage=9),
            "requirement_rows": lambda c: c["common"]["requirements"].update(rows=[]),
            "requirement_complete": lambda c: c["common"]["requirements"].update(complete=True),
            "requirement_verified": lambda c: c["common"]["requirements"].update(verified=999),
            "requirement_missing": lambda c: c["common"]["requirements"].update(missing=[]),
            "submission_ready": lambda c: c["common"]["submission"].update(ready=True),
            "submission_blockers": lambda c: c["common"]["submission"].update(blockers=[]),
            "blockers": lambda c: c["common"].update(blockers=[]),
            "stale_objects": lambda c: c["common"].update(stale_objects={"invented": ["hidden state"]}),
            "current_model_pointer": lambda c: c["common"]["current"].update({"model.Q1": self.ids["code"]}),
            "missing_model_bucket": lambda c: c["common"].update(models={}),
            "decisions": lambda c: c["common"].update(decisions=[{"accepted": "invented conclusion"}]),
            "task_title": lambda c: c["task"].update(title="Publish the submission"),
            "task_requirements": lambda c: c["task"].update(requirements=[]),
            "task_dependencies": lambda c: c["task"].update(dependencies=[]),
            "task_outputs": lambda c: c["task"].update(outputs=[self.ids["model"]]),
            "task_status": lambda c: c["task"].update(status="completed"),
            "missing_task": lambda c: c.update(task=None),
            "wrong_task_id": lambda c: c.update(task_id="T-invented"),
            "missing_dependency_object": drop_object,
            "missing_all_objects": lambda c: c.update(objects={}),
            "object_dependencies": lambda c: c["objects"][self.ids["params"]].update(dependencies=[]),
            "object_status": lambda c: c["objects"][self.ids["code"]].update(status="verified"),
            "object_observation": lambda c: c["objects"][self.ids["code"]].update(current_errors=["invented error"]),
            "object_creation_revision": lambda c: c["objects"][self.ids["code"]].update(created_revision=0),
            "missing_changes": lambda c: c.update(changes=[]),
            "journal_entry": lambda c: c["changes"][0].update(reason="Invented accepted decision"),
            "next_action": lambda c: c.update(next_action="All verified; submit now"),
            "unknown_role": lambda c: c.update(role="unrecognized"),
            "wrong_baseline": lambda c: c.update(changes_since=-1),
            "unexpected_field": lambda c: c.update(trusted_override=True),
        }

    def test_all_current_projection_fields_are_authoritative(self):
        for name, mutate in self.mutations().items():
            with self.subTest(field=name):
                context = self.context()
                mutate(context)
                self.assert_rejected_without_write(context)

    def test_all_historical_projection_fields_are_authoritative(self):
        original = self.context()
        self.rt.configure(self.rev(), stage=4)
        for name, mutate in self.mutations().items():
            with self.subTest(field=name):
                context = copy.deepcopy(original)
                mutate(context)
                self.assert_rejected_without_write(context)

    def test_valid_current_and_history_are_receivable_without_promoting_evidence(self):
        context = self.context()
        source_revision = context["source_revision"]
        first = self.receive(context)["result"]
        self.assertEqual(first["received_revision"], source_revision)
        self.assertEqual(first["adoptions"], [])
        self.rt.configure(self.rev(), stage=3)
        self.rt.configure(self.rev(), stage=5)
        again = self.receive(context)["result"]
        self.assertEqual(again["received_revision"], source_revision)
        adopted = acknowledge(self.root, self.rev(), context, member="member_2", action="adopted", object_ids=[self.ids["model"]])["result"]
        self.assertEqual(adopted["adoptions"][-1]["object_ids"], [self.ids["model"]])
        self.assertEqual(adopted["verifications"], [])

    def test_valid_history_is_receivable_after_object_superseded_but_cannot_be_adopted(self):
        context = self.context()
        previous_code = self.ids["code"]
        self.reg("CodeManifest", "code.Q1", {"question": "Q1", "revision_id": "replacement"}, [self.ids["model"]], ["solver.py"])
        self.receive(context)
        with self.assertRaises(ConflictError):
            acknowledge(self.root, self.rev(), context, member="member_2", action="adopted", object_ids=[previous_code])

    def test_file_drift_requires_explicit_reconciliation_before_new_export(self):
        context = self.context()
        (self.root / "solver.py").write_text("print('changed source')", encoding="utf-8")
        before = self.rt.store.path.read_bytes()
        with self.assertRaisesRegex(ConflictError, "reconcile"):
            self.context()
        self.assertEqual(before, self.rt.store.path.read_bytes())
        self.rt.reconcile(self.rev())
        fresh = self.context()
        self.assertEqual(fresh["objects"][self.ids["code"]]["status"], "stale")
        self.assertTrue(fresh["objects"][self.ids["code"]]["current_errors"])
        self.receive(context)
        with self.assertRaises(ConflictError):
            acknowledge(self.root, self.rev(), context, member="member_2", action="adopted", object_ids=[self.ids["code"]])

    def test_default_member_baseline_cannot_be_forged(self):
        self.receive(self.context())
        self.rt.configure(self.rev(), stage=3)
        context = self.context()
        self.assertGreater(context["changes_since"], 0)
        context["changes_since"] = 0
        context["changes"] = copy.deepcopy(self.rt.read()["copilot"]["journal"])
        self.assert_rejected_without_write(context)

    def test_explicit_baseline_and_task_are_valid_selection_parameters(self):
        base = self.rev()
        self.rt.configure(base, stage=2)
        context = self.context(since=base, task_id="T-context")
        self.assertEqual([entry["revision"] for entry in context["changes"]], [base + 1])
        self.receive(context)

    def test_partial_explicit_context_does_not_skip_unreceived_changes(self):
        context = self.context(since=self.rev() - 1)
        record = self.receive(context)["result"]
        self.assertEqual(record["received_revision"], 0)
        self.assertEqual(record["receipts"][-1]["changes_since"], context["changes_since"])
        self.assertEqual(record["receipts"][-1]["scope"], "partial_history")
        adopted = acknowledge(self.root, self.rev(), context, member="member_2", action="adopted", object_ids=[self.ids["model"]])["result"]
        self.assertEqual(adopted["received_revision"], 0)
        self.assertEqual(adopted["adoptions"][-1]["object_ids"], [self.ids["model"]])

    def test_partial_ranges_join_after_missing_history_is_received(self):
        earlier = self.context()
        self.rt.configure(self.rev(), stage=4)
        later = self.context(since=earlier["source_revision"])
        partial = self.receive(later)["result"]
        self.assertEqual(partial["received_revision"], 0)
        completed = self.receive(earlier)["result"]
        self.assertEqual(completed["received_revision"], later["source_revision"])
        self.assertEqual(completed["receipts"][-1]["scope"], "cumulative_history")

    def test_resealed_valid_partial_selection_cannot_claim_cumulative_sync(self):
        context = self.context()
        context["selection"]["baseline"] = "explicit"
        context["changes_since"] = context["source_revision"]
        context["changes"] = []
        # This is a valid alternate view, but it proves no missing event range.
        record = self.receive(reseal(context))["result"]
        self.assertEqual(record["received_revision"], 0)
        self.assertEqual(record["receipts"][-1]["scope"], "partial_history")

    def test_role_views_share_common_revision_and_export_is_read_only(self):
        before = self.rt.store.path.read_bytes()
        views = [build_context(self.root, role=role, member="member_2", task_id="T-context") for role in ("modeler", "coder", "writer")]
        self.assertEqual(len({view["common_hash"] for view in views}), 1)
        self.assertEqual(len({view["source_state_hash"] for view in views}), 1)
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_historical_task_and_baseline_are_replayed_from_source_revision(self):
        self.receive(self.context())
        self.rt.configure(self.rev(), stage=2)
        original = self.context()
        self.rt.task(self.rev(), "T-new-current", {
            "title": "A different next task", "role": "writer", "requirements": ["REQ-Q1-001"],
            "dependencies": [self.ids["contract"]],
        })
        self.receive(self.context())
        received_before = self.rt.read()["copilot"]["members"]["member_2"]["received_revision"]
        record = self.receive(original)["result"]
        self.assertEqual(record["received_revision"], received_before)
        self.assertEqual(original["task_id"], "T-context")
        self.assertLess(original["changes_since"], original["source_revision"])

    def test_current_receipt_after_uncommitted_file_drift_preserves_historical_meaning(self):
        context = self.context()
        (self.root / "solver.py").write_text("print('changed after export')", encoding="utf-8")
        self.receive(context)
        self.assertEqual(context["objects"][self.ids["code"]]["current_errors"], [])
        with self.assertRaises(ConflictError):
            acknowledge(self.root, self.rev(), context, member="member_2", action="adopted", object_ids=[self.ids["code"]])
        current = self.context()
        self.assertTrue(current["objects"][self.ids["code"]]["current_errors"])

    def test_validator_change_requires_explicit_reconcile_before_new_export(self):
        previous = self.context()
        real_status = project_status
        def stricter_status(root, state):
            result = real_status(root, state)
            result["blockers"].append("New independent validation requirement")
            return result
        with patch("copilot_context.project_status", side_effect=stricter_status):
            before = self.rt.store.path.read_bytes()
            with self.assertRaisesRegex(ConflictError, "reconcile"):
                self.context()
            self.assertEqual(before, self.rt.store.path.read_bytes())
            self.rt.reconcile(self.rev())
            updated = self.context()
            self.assertIn("New independent validation requirement", updated["common"]["blockers"])
            self.receive(previous)

    def test_types_and_role_selectors_are_checked_not_only_python_equality(self):
        for name, mutate in {
            "bool_as_integer": lambda c: c["common"]["requirements"].update(complete=0),
            "role_without_view_rebuild": lambda c: c.update(role="impossible"),
            "boolean_revision": lambda c: c.update(source_revision=True),
            "unknown_selector": lambda c: c["selection"].update(hidden_override=True),
            "unknown_projection_version": lambda c: c.update(projection_version="0.99"),
            "forged_observation_time": lambda c: c["file_observation"].update(at="tomorrow"),
        }.items():
            with self.subTest(field=name):
                context = self.context()
                mutate(context)
                self.assert_rejected_without_write(context)

    def test_role_views_without_a_task_enforce_the_complete_selected_set(self):
        self.rt.store.transact(self.rev(), "qa", "Clear active task for role projection test", lambda state: state["copilot"].update(current_task=None))
        coder = self.context()
        writer = build_context(self.root, role="writer", member="member_2")
        self.assertEqual(coder["common"], writer["common"])
        self.assertNotEqual(set(coder["objects"]), set(writer["objects"]))
        coder["role"] = "writer"
        self.assert_rejected_without_write(coder)


class ContextSnapshotStorageTests(unittest.TestCase):
    setUp = ContextProjectionRegressionTests.setUp
    rev = ContextProjectionRegressionTests.rev
    context = ContextProjectionRegressionTests.context
    receive = ContextProjectionRegressionTests.receive

    def test_every_retained_revision_reconstructs_original_full_state_hash(self):
        original = self.rt.read()
        self.rt.configure(self.rev(), stage=4)
        state = self.rt.read()
        prior = state_at_revision(state, original["copilot"]["revision"])
        self.assertEqual(prior, original)
        self.assertEqual(state_digest(prior), original["copilot"]["state_hash"])
        for revision, entry in state["copilot"]["context_history"].items():
            with self.subTest(revision=revision):
                restored = state_at_revision(state, int(revision))
                self.assertEqual(state_digest(restored), restored["copilot"]["state_hash"])
                self.assertNotIn("context_history", entry["state"]["copilot"])
        self.assertEqual(len(state["copilot"]["context_history"]), state["copilot"]["revision"])

    def test_history_and_commit_projection_cannot_be_rewritten_through_store(self):
        key = next(iter(self.rt.read()["copilot"]["context_history"]))
        mutations = {
            "history_edit": lambda cp: cp["context_history"][key]["state"].update(competition="forged"),
            "history_delete": lambda cp: cp["context_history"].pop(key),
            "history_clear": lambda cp: cp.update(context_history={}),
            "projection_forgery": lambda cp: cp["context_projection"]["status"]["submission"].update(ready=True),
            "projection_type_change": lambda cp: cp["context_projection"]["status"]["submission"].update(ready=0),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                before = self.rt.store.path.read_bytes()
                with self.assertRaises(IntegrityError):
                    self.rt.store.transact(self.rev(), "qa", name, lambda state: mutate(state["copilot"]))
                self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_forged_historical_facts_fail_original_state_hash_reconstruction(self):
        state = self.rt.read()
        revision = min(int(key) for key in state["copilot"]["context_history"])
        state["copilot"]["context_history"][str(revision)]["state"]["current_stage"] = 9
        with self.assertRaises(IntegrityError):
            state_at_revision(state, revision)

    def test_legacy_state_needs_explicit_checkpoint_without_fabricating_older_history(self):
        state = self.rt.read()
        cp = state["copilot"]
        legacy_revision = cp["revision"]
        cp.pop("context_history")
        cp.pop("context_projection")
        cp["state_hash"] = state_digest(state)
        self.rt.store.path.write_text(json.dumps(state), encoding="utf-8")
        before = self.rt.store.path.read_bytes()
        self.rt.read()
        with self.assertRaisesRegex(ConflictError, "reconcile"):
            self.context()
        self.assertEqual(before, self.rt.store.path.read_bytes())
        self.rt.reconcile(self.rev())
        current = self.context()
        self.receive(current)
        updated = self.rt.read()
        restored = state_at_revision(updated, legacy_revision)
        self.assertEqual(restored, state)
        self.assertNotIn("context_projection", restored["copilot"])
        with self.assertRaisesRegex(ValueError, "完整权威快照"):
            state_at_revision(updated, legacy_revision - 1)

    def test_unsupported_projection_version_has_explicit_upgrade_path(self):
        state = self.rt.read()
        state["copilot"]["context_projection"]["version"] = "unsupported-test-version"
        state["copilot"]["state_hash"] = state_digest(state)
        self.rt.store.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ConflictError, "projection_version.*reconcile"):
            self.context()
        self.rt.reconcile(self.rev())
        current = self.context()
        self.assertEqual(current["projection_version"], "0.1.1")
        self.receive(current)

    def test_legacy_receipt_without_scope_does_not_certify_a_cumulative_baseline(self):
        legacy_revision = self.rev()
        def add_legacy_record(state):
            state["copilot"]["members"]["member_2"] = {
                "received_revision": legacy_revision,
                "receipts": [{"context_id": "old-unscoped-context", "revision": legacy_revision, "at": "legacy"}],
                "adoptions": [], "verifications": [],
            }
        self.rt.store.transact(self.rev(), "qa", "Import a real v0.1 receipt shape", add_legacy_record)
        current = self.context()
        self.assertEqual(current["changes_since"], 0)
        partial = self.context(since=current["source_revision"])
        record = self.receive(partial)["result"]
        self.assertEqual(record["received_revision"], 0)
        self.assertEqual(record["legacy_received_revision"], legacy_revision)
        self.assertEqual(record["receipts"][0]["context_id"], "old-unscoped-context")
        complete = self.receive(current)["result"]
        self.assertEqual(complete["received_revision"], current["source_revision"])

    def test_commit_projector_never_reads_or_reenters_store(self):
        store = self.rt.store
        original_read = Store.read
        reads = []
        def counted_read(current):
            reads.append(str(current.path))
            return original_read(current)
        with patch.object(Store, "read", counted_read):
            store.transact(self.rev(), "qa", "No recursive Store access", lambda state: state.update(task_type="observation-test"))
        # One explicit self.rev() read and one transaction read, and no more.
        self.assertEqual(len(reads), 2)

    def windows_reader_without_delete_sharing(self):
        import ctypes
        from ctypes import wintypes
        library = ctypes.WinDLL("kernel32", use_last_error=True)
        library.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        library.CreateFileW.restype = wintypes.HANDLE
        library.CloseHandle.argtypes = [wintypes.HANDLE]
        library.CloseHandle.restype = wintypes.BOOL
        # Share reads/writes, but retain a real OS handle that denies replace.
        handle = library.CreateFileW(str(self.rt.store.path), 0x80000000, 1 | 2, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        closed = threading.Event()
        def close():
            if not closed.is_set():
                if not library.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                closed.set()
        return close

    @unittest.skipUnless(os.name == "nt", "Requires actual Win32 file sharing semantics")
    def test_short_windows_replace_denial_recovers_after_reader_releases_handle(self):
        revision = self.rev()
        close = self.windows_reader_without_delete_sharing()
        release = threading.Timer(0.25, close)
        release.start()
        try:
            self.rt.configure(revision, stage=4)
        finally:
            release.join()
            close()
        self.assertEqual(self.rev(), revision + 1)
        self.assertEqual(self.rt.read()["current_stage"], 4)

    @unittest.skipUnless(os.name == "nt", "Requires actual Win32 file sharing semantics")
    def test_permanent_windows_replace_denial_keeps_authority_and_removes_temp(self):
        revision = self.rev()
        before = self.rt.store.path.read_bytes()
        close = self.windows_reader_without_delete_sharing()
        started = time.monotonic()
        try:
            with self.assertRaises(PermissionError) as caught:
                self.rt.configure(revision, stage=4)
        finally:
            close()
        self.assertIn(caught.exception.winerror, {5, 32, 33})
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(before, self.rt.store.path.read_bytes())
        self.assertEqual(self.rev(), revision)
        self.assertEqual(list(self.rt.store.path.parent.glob(".decision_log.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
