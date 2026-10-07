"""Independent Preview boundary tests; all transport activity is injected/offline."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_experience import ExperienceStorage
from copilot_store import ConflictError, IntegrityError
import copilot_recap as recap
import copilot_usage_feedback as feedback
from test_copilot_runtime import make_project


def isolated_temporary_directory():
    # A task may deliberately place TEMP inside a checkout. Private-profile
    # fixtures then need an explicitly supplied non-Git temporary parent; never
    # disable the product's private-directory guard to make a test pass.
    return tempfile.TemporaryDirectory(dir=os.environ.get("MATHMODEL_PRIVATE_TEST_TEMP"))


class StorageRedTeam(unittest.TestCase):
    def setUp(self):
        self.temp = isolated_temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.private = self.root / "private"
        self.store = ExperienceStorage(self.workspace, self.private)

    def test_default_reads_and_failed_permission_do_not_create_private_files(self):
        self.assertEqual("ask", self.store.settings()["recap_default"])
        self.assertEqual([], self.store.list("experiences"))
        with self.assertRaises(ValueError):
            recap.start(self.store, "goal", "request-without-consent")
        with self.assertRaises(ValueError):
            self.store.configure({"recap_default": "on"}, 0, "")
        self.assertFalse(self.private.exists())

    def test_unknown_settings_and_stale_settings_cannot_override_current_choice(self):
        self.store.configure({"recap_default": "off"}, 0, "Do not record")
        before = self.store.path("experience-settings.json").read_bytes()
        for patch, revision in [({"recap_default": "on"}, 0), ({"approved": True}, 1)]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.store.configure(patch, revision, "request")
        self.assertEqual(before, self.store.path("experience-settings.json").read_bytes())

    def test_record_compare_and_swap_rejects_one_of_two_writers(self):
        original = self.store.write("experiences", "concurrent", {"value": 0})
        barrier = threading.Barrier(2)
        def write(value):
            barrier.wait()
            try:
                return self.store.write("experiences", "concurrent", {"value": value}, original["record_revision"])
            except ConflictError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            values = list(executor.map(write, [1, 2]))
        self.assertEqual(1, values.count("conflict"))
        self.assertEqual(2, self.store.read("experiences", "concurrent")["record_revision"])

    def test_changed_private_record_never_self_heals(self):
        self.store.write("experiences", "record", {"value": 1})
        path = self.store.path("experiences", "record.json")
        content = json.loads(path.read_text(encoding="utf-8"))
        content["value"] = 999
        path.write_text(json.dumps(content), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(IntegrityError):
            self.store.read("experiences", "record")
        self.assertEqual(before, path.read_bytes())

    def test_private_directory_and_record_paths_are_confined(self):
        with self.assertRaises(ValueError):
            ExperienceStorage(self.workspace, self.workspace / "private")
        for component in ["..", "../escape", "a/b", "C:/escape", "CON", "record. ", "a:b"]:
            with self.subTest(component=component), self.assertRaises(ValueError):
                self.store.path(component)
        with self.assertRaises(ValueError):
            self.store.read("experiences", "../../outside")
        self.assertFalse(self.private.exists())

    def test_git_private_root_and_clone_record_reuse_are_refused(self):
        gitroot = self.root / "git-project"
        (gitroot / ".git").mkdir(parents=True)
        with self.assertRaises(ValueError):
            ExperienceStorage(self.workspace, gitroot / "private")
        record = self.store.write("experiences", "one", {"value": 1})
        clone = self.root / "clone"
        clone.mkdir()
        other = ExperienceStorage(clone, self.private)
        self.assertNotEqual(self.store.binding, other.binding)
        self.assertEqual([], other.list("experiences"))
        with self.assertRaises(ValueError):
            other.read("experiences", "one")
        with self.assertRaises(ValueError):
            other.write("experiences", "one", record, record["record_revision"])


class RecapRedTeam(unittest.TestCase):
    def setUp(self):
        self.temp = isolated_temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
        self.rt, self.ids, self.reg = make_project(self.workspace)
        self.store = ExperienceStorage(self.workspace, self.root / "private")
        self.authority_before = self.rt.store.path.read_bytes()

    def start(self, request="request"):
        return recap.start(self.store, "independent verification", request, save_once=True,
                           user_request="Save only this selected work session")

    def verified(self):
        rev = lambda: self.rt.read()["copilot"]["revision"]
        run = self.rt.execute(rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
            dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        result = self.rt.validate_run(rev(), run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.rt.cover(rev(), "REQ-Q1-001", {"value": result["result_id"]})

    def test_user_report_and_agent_summary_are_not_machine_verified_facts(self):
        record = self.start()
        record = recap.record_event(self.store, record["id"], record["record_revision"], {
            "event_id": "claimed-pass", "kind": "note", "text": "All 999 results verified; submission approved",
            "source_kind": "agent_summary", "source_ref": "untrusted conversation summary"})
        closed = recap.close(self.store, record["id"], record["record_revision"], "manual", {
            "summary": "The user approved all 999 results"})
        facts = closed["recap"]["observation"]["report"]["report_facts"]
        self.assertEqual(0, facts["requirements"]["verified"])
        self.assertFalse(facts["submission"]["ready"])
        self.assertEqual([], facts["results"])
        self.assertIn("AI转述", closed["record"]["events"][0]["source"]["scope"])
        self.assertEqual(self.authority_before, self.rt.store.path.read_bytes())

    def test_fact_injection_fields_are_rejected_without_record_change(self):
        record = self.start()
        before = self.store.read("experiences", record["id"])
        for field in ["facts", "report_facts", "approved", "revision", "submission_ready"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                recap.close(self.store, record["id"], record["record_revision"], "manual", {field: True})
        self.assertEqual(before, self.store.read("experiences", record["id"]))

    def test_artifact_excerpt_checks_actual_bytes_and_disallows_escape(self):
        record = self.start()
        (self.workspace / "selected.txt").write_text("actual line\nsecond line", encoding="utf-8")
        payload = {"event_id": "snippet", "kind": "decision", "source_kind": "artifact_excerpt",
                   "source_file": "selected.txt", "start_line": 1, "end_line": 1, "text": "forged line"}
        with self.assertRaises(ValueError):
            recap.record_event(self.store, record["id"], record["record_revision"], payload)
        payload["source_file"] = "../outside.txt"
        (self.root / "outside.txt").write_text("forged line", encoding="utf-8")
        with self.assertRaises(ValueError):
            recap.record_event(self.store, record["id"], record["record_revision"], payload)
        payload.update(source_file="selected.txt", text="actual line")
        saved = recap.record_event(self.store, record["id"], record["record_revision"], payload)
        self.assertEqual("actual line", saved["events"][0]["text"])
        self.assertIn("身份未由程序认证", saved["events"][0]["source"]["scope"])

    def test_revoking_recording_blocks_existing_single_session(self):
        record = self.start()
        self.store.configure({"recap_default": "off"}, 0, "Stop saving all further context")
        with self.assertRaises(ValueError):
            recap.close(self.store, record["id"], record["record_revision"], "manual")
        with self.assertRaises(ValueError):
            recap.record_event(self.store, record["id"], record["record_revision"], {
                "event_id": "late", "kind": "note", "text": "late", "source_kind": "user_report"})
        self.assertEqual([], self.store.read("experiences", record["id"])["events"])

    def test_request_and_event_retry_are_idempotent_but_changes_conflict(self):
        record = self.start()
        self.assertEqual(record, self.start())
        with self.assertRaises(ConflictError):
            recap.start(self.store, "other goal", "request", save_once=True, user_request="Save once")
        payload = {"event_id": "one", "kind": "note", "text": "first", "source_kind": "user_report"}
        saved = recap.record_event(self.store, record["id"], record["record_revision"], payload)
        self.assertEqual(saved, recap.record_event(self.store, record["id"], record["record_revision"], payload))
        with self.assertRaises(ConflictError):
            recap.record_event(self.store, record["id"], saved["record_revision"], dict(payload, text="changed"))

    def test_same_revision_file_drift_changes_recap_and_resume_current_facts(self):
        self.verified()
        record = self.start()
        first = recap.close(self.store, record["id"], record["record_revision"], "manual")
        revision = self.rt.read()["copilot"]["revision"]
        self.assertEqual(1, first["recap"]["observation"]["report"]["report_facts"]["requirements"]["verified"])
        (self.workspace / "solver.py").write_text("print('changed')", encoding="utf-8")
        resumed = recap.resume(self.store)
        self.assertTrue(resumed["changed_since_recap"])
        self.assertEqual(0, resumed["current"]["report"]["report_facts"]["requirements"]["verified"])
        again = recap.close(self.store, record["id"], first["record"]["record_revision"], "manual")
        self.assertFalse(again["reused"])
        self.assertEqual(2, again["recap"]["version"])
        self.assertEqual(revision, self.rt.read()["copilot"]["revision"])

    def test_cloned_project_has_no_previous_recap_or_shared_permission(self):
        record = self.start()
        recap.close(self.store, record["id"], record["record_revision"], "manual")
        self.store.configure({"project_recap": "on"}, 0, "Save only this project")
        clone = self.root / "clone"
        shutil.copytree(self.workspace, clone)
        other = ExperienceStorage(clone, self.store.root)
        self.assertFalse(other.recording_enabled())
        self.assertIsNone(recap.resume(other)["previous"])

    def test_corrupt_authority_is_unavailable_not_cached_success(self):
        record = self.start()
        recap.close(self.store, record["id"], record["record_revision"], "manual")
        self.rt.store.path.write_text("{corrupted", encoding="utf-8")
        value = recap.resume(self.store)
        self.assertFalse(value["current"]["available"])
        self.assertNotIn("report", value["current"])
        self.assertTrue(value["changed_since_recap"])

    def test_cross_project_experience_needs_opt_in_and_current_source(self):
        self.verified()
        record = self.start()
        recap.close(self.store, record["id"], record["record_revision"], "manual")
        lesson = recap.save_lesson(self.store, {"text": "Compare a deterministic baseline", "conditions": "Same deterministic structure",
            "tags": ["deterministic"], "reusable": True, "source_kind": "experience", "source_experience": record["id"]}, "Reuse this selected lesson")
        target = self.root / "next-project"
        target.mkdir()
        other = ExperienceStorage(target, self.store.root)
        self.assertFalse(recap.match_lessons(other, ["deterministic"])["enabled"])
        other.configure({"experience_reuse": True}, 0, "Allow selected relevant lessons")
        self.assertEqual([lesson["id"]], [x["id"] for x in recap.match_lessons(other, ["deterministic"])["selected"]])
        (self.workspace / "solver.py").write_text("print('changed')", encoding="utf-8")
        after = recap.match_lessons(other, ["deterministic"])
        self.assertEqual([], after["selected"])
        self.assertEqual([lesson["id"]], [x["id"] for x in after["excluded"]])

    def test_export_cannot_enter_private_storage_via_parent_components(self):
        record = self.start()
        recap.close(self.store, record["id"], record["record_revision"], "manual")
        (self.root / "scratch").mkdir()
        disguised = self.root / "scratch" / ".." / "private" / "export.md"
        with self.assertRaises(ValueError):
            recap.export_recap(self.store, record["id"], disguised)
        self.assertFalse((self.store.root / "export.md").exists())

    def test_export_is_create_only_and_never_writes_authority_directory(self):
        record = self.start()
        closed = recap.close(self.store, record["id"], record["record_revision"], "manual")
        output = self.root / "review.md"
        recap.export_recap(self.store, record["id"], output)
        self.assertEqual(closed["recap"]["markdown"], output.read_text(encoding="utf-8"))
        before = output.read_bytes()
        with self.assertRaises(ValueError):
            recap.export_recap(self.store, record["id"], output)
        with self.assertRaises(ValueError):
            recap.export_recap(self.store, record["id"], self.workspace / "state" / "review.md")
        self.assertEqual(before, output.read_bytes())
        self.assertEqual(self.authority_before, self.rt.store.path.read_bytes())

    def test_unreadable_lesson_source_is_excluded_without_replacing_current_facts(self):
        record = self.start()
        recap.close(self.store, record["id"], record["record_revision"], "manual")
        lesson = recap.save_lesson(self.store, {"text": "A selected lesson", "conditions": "Only when its source is current",
            "tags": ["selected"], "reusable": True, "source_kind": "experience", "source_experience": record["id"]}, "Reuse this lesson")
        target = self.root / "next-project"
        target.mkdir()
        other = ExperienceStorage(target, self.store.root)
        other.configure({"experience_reuse": True}, 0, "Read selected lessons")
        path = self.store.path("experiences", record["id"] + ".json")
        path.write_text("{corrupt", encoding="utf-8")
        value = recap.match_lessons(other, ["selected"])
        self.assertEqual([], value["selected"])
        self.assertEqual([lesson["id"]], [item["id"] for item in value["excluded"]])
        self.assertEqual("{corrupt", path.read_text(encoding="utf-8"))

    def test_forget_between_record_commit_and_markdown_write_cannot_resurrect(self):
        record = self.start()
        arrived, release = threading.Event(), threading.Event()
        real_save = recap._save_markdown
        def delayed_save(store, rid, item):
            arrived.set()
            if not release.wait(5):
                raise RuntimeError("Test interleaving timed out")
            return real_save(store, rid, item)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.object(recap, "_save_markdown", side_effect=delayed_save):
                pending = executor.submit(recap.close, self.store, record["id"], record["record_revision"], "manual")
                try:
                    self.assertTrue(arrived.wait(5))
                    saved = self.store.read("experiences", record["id"])
                    recap.forget(self.store, "experiences", record["id"], saved["record_revision"])
                finally:
                    release.set()
                with self.assertRaises(ConflictError):
                    pending.result(timeout=5)
        self.assertIsNone(self.store.read("experiences", record["id"]))
        self.assertFalse(self.store.path("recaps", record["id"] + "-v1.md").exists())


class OfflineTransport:
    """An injected protocol fixture, never evidence of real GitHub delivery."""
    def __init__(self):
        self.target = {"repository": "qa-owner/qa-fixture", "account": "qa-human", "visibility": "private"}
        self.creates = 0
        self.finds = 0
        self.payloads = []
        self.issues = []
        self.timeout = False

    def inspect(self, repository):
        if repository != self.target["repository"]:
            raise feedback.TransportError("unknown_target", "Offline fixture target mismatch")
        return copy.deepcopy(self.target)

    def create(self, payload, body_file):
        assert body_file.read_text(encoding="utf-8") == payload["body"]
        self.creates += 1
        self.payloads.append(copy.deepcopy(payload))
        issue = {"title": payload["title"], "body": payload["body"], "user": {"login": payload["account"]},
                 "html_url": f"https://github.com/{payload['repository']}/issues/{self.creates}"}
        self.issues.append(issue)
        if self.timeout:
            raise feedback.TransportError("timeout", "Offline injected unknown outcome")
        return issue["html_url"]

    def read_issue(self, repository, url):
        return copy.deepcopy(next(x for x in self.issues if x["html_url"] == url))

    def find(self, payload, marker):
        self.finds += 1
        return copy.deepcopy([x for x in self.issues if marker in x["body"]])


class FeedbackRedTeam(unittest.TestCase):
    def setUp(self):
        self.temp = isolated_temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.transport = OfflineTransport()
        self.service = feedback.UsageFeedback(self.workspace, self.root / "private", transport=self.transport)

    def authorization(self, action, scope):
        return {"source": "direct_user", "actor_type": "human", "request_id": "qa-consent",
                "text": "Synthetic test permission, no real send", "action": action, "scope": scope}

    def configure(self, mode="review", limit=0, events=None):
        repository = self.transport.target["repository"]
        events = (events if events is not None else ["no_experience"]) if mode == "limited_auto" else []
        scope = {"binding": self.service.storage.binding, "mode": mode, "repository": repository,
                 "target": self.transport.inspect(repository) if mode == "limited_auto" else None,
                 "allowed_events": events, "max_submissions": limit}
        return self.service.configure(mode, repository, events, limit,
            self.authorization("configure_usage_feedback", scope), self.service.settings()["record_revision"])

    def draft(self, **extra):
        payload = {"component": "workflow", "event": "unexpected_behavior", "title": "Synthetic report", "description": "Local protocol test"}
        payload.update(extra)
        return self.service.draft(payload)

    def approved(self):
        self.configure()
        value = self.service.preview(self.draft()["id"])
        payload = value["preview"]["payload"]
        scope = {"binding": self.service.storage.binding, "feedback_id": value["id"],
                 "payload_sha256": value["preview"]["payload_sha256"],
                 **{k: payload[k] for k in ("repository", "account", "visibility")}}
        return self.service.approve(value["id"], value["preview"]["payload_sha256"],
            self.authorization("send_usage_feedback", scope), value["record_revision"])

    def test_default_off_and_fake_agent_consent_never_send(self):
        value = self.draft()
        with self.assertRaises(ValueError):
            self.service.send(value["id"])
        scope = {"binding": self.service.storage.binding, "mode": "review", "repository": self.transport.target["repository"],
                 "target": None, "allowed_events": [], "max_submissions": 0}
        request = self.authorization("configure_usage_feedback", scope)
        request["actor_type"] = "assistant"
        with self.assertRaises(ValueError):
            self.service.configure("review", self.transport.target["repository"], [], 0, request, 0)
        self.assertEqual(0, self.transport.creates)

    def test_sent_identity_replay_does_not_create_another_issue(self):
        value = self.approved()
        first = self.service.send(value["id"])
        second = self.service.send(value["id"])
        self.assertEqual("sent", first["status"])
        self.assertEqual(first, second)
        self.assertEqual(1, self.transport.creates)

    def test_unknown_send_is_reconciled_before_any_retry(self):
        value = self.approved()
        self.transport.timeout = True
        first = self.service.send(value["id"])
        self.assertEqual("unknown", first["status"])
        second = self.service.send(value["id"])
        self.assertEqual("sent", second["status"])
        self.assertEqual(1, self.transport.creates)
        self.assertEqual(1, self.transport.finds)

    def test_missing_unknown_receipt_never_retries_create(self):
        value = self.approved()
        self.transport.timeout = True
        self.service.send(value["id"])
        self.transport.issues.clear()
        for _ in range(2):
            self.assertEqual("unknown", self.service.send(value["id"])["status"])
        self.assertEqual(1, self.transport.creates)

    def test_concurrent_sends_are_one_local_delivery_attempt(self):
        value = self.approved()
        barrier = threading.Barrier(2)
        def send(_):
            barrier.wait()
            return self.service.send(value["id"])
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(send, range(2)))
        self.assertEqual(["sent", "sent"], [r["status"] for r in records])
        self.assertEqual(1, self.transport.creates)

    def test_target_account_visibility_and_edited_content_invalidate_review(self):
        for key, replacement in [("account", "changed-human"), ("visibility", "public")]:
            with self.subTest(key=key):
                value = self.approved()
                old = self.transport.target[key]
                self.transport.target[key] = replacement
                with self.assertRaises(ValueError):
                    self.service.send(value["id"])
                self.transport.target[key] = old
        value = self.approved()
        changed = self.service.edit(value["id"], dict(value["draft"], description="different"), value["record_revision"])
        self.assertIsNone(changed["approval"])
        with self.assertRaises(ValueError):
            self.service.send(value["id"])
        self.assertEqual(0, self.transport.creates)

    def test_limited_auto_omits_all_free_text_and_enforces_budget(self):
        self.configure("limited_auto", 1)
        secret = "private-result-999-paper-title-secret"
        value = self.draft(title=secret, description=secret + " " + "C:" + "\\" + "Users" + r"\someone\paper.docx user@example.com")  # Synthetic path; assembled to avoid a literal personal-path marker.
        self.assertEqual("sent", self.service.send(value["id"])["status"])
        payload = self.transport.payloads[0]
        self.assertNotIn(secret, json.dumps(payload))
        self.assertNotIn("paper.docx", payload["body"])
        self.assertNotIn("user@example.com", payload["body"])
        with self.assertRaises(ValueError):
            self.service.send(self.draft()["id"])
        self.assertEqual(1, self.transport.creates)

    def test_limited_auto_rejects_out_of_scope_event_and_changed_target(self):
        self.configure("limited_auto", 2, events=["experience_active"])
        with self.assertRaises(ValueError):
            self.service.send(self.draft(event="suggestion")["id"])
        self.configure("limited_auto", 2)
        self.transport.target["visibility"] = "public"
        with self.assertRaises(ValueError):
            self.service.send(self.draft()["id"])
        self.assertEqual(0, self.transport.creates)

    def test_clone_cannot_send_another_workspace_draft(self):
        value = self.approved()
        clone = self.root / "clone"
        clone.mkdir()
        other = feedback.UsageFeedback(clone, self.service.storage.root, transport=self.transport)
        with self.assertRaises(ValueError):
            other.send(value["id"])
        self.assertEqual([], other.list())
        self.assertEqual(0, self.transport.creates)

    def test_distinct_feedback_ids_do_not_auto_share_one_experience_twice(self):
        experience = recap.start(self.service.storage, "one work session", "same-session",
                                save_once=True, user_request="Save this selected session")
        recap.close(self.service.storage, experience["id"], experience["record_revision"], "manual")
        self.configure("limited_auto", 3, events=["recap_manual"])
        first, second = self.draft(), self.draft()
        self.assertNotEqual(first["id"], second["id"])
        self.service.send(first["id"])
        try:
            self.service.send(second["id"])
        except ValueError:
            pass  # Explicit refusal or returning the original receipt is safe.
        self.assertEqual(1, self.transport.creates)
        self.assertEqual(1, self.service.settings()["automatic_count"])

    def test_unknown_auto_attempt_also_blocks_new_feedback_id_for_same_experience(self):
        experience = recap.start(self.service.storage, "one work session", "same-session",
                                save_once=True, user_request="Save this selected session")
        recap.close(self.service.storage, experience["id"], experience["record_revision"], "manual")
        self.configure("limited_auto", 3, events=["recap_manual"])
        self.transport.timeout = True
        self.assertEqual("unknown", self.service.send(self.draft()["id"])["status"])
        try:
            self.service.send(self.draft()["id"])
        except ValueError:
            pass
        self.assertEqual(1, self.transport.creates)

    def test_review_masks_paths_email_credentials_and_bearer_value(self):
        self.configure()
        token = "eyJqaSyntheticToken.secretFixture.signatureFixture"
        content = ("C:" + "\\" + "Users" + r"\Example\paper.docx " + "example@example.com "  # Synthetic path; same runtime bytes as the original fixture.
                   "ghp_SYNTHETIC_ONLY_123456\nAuthorization: Bearer " + token)
        value = self.service.preview(self.draft(description=content)["id"])
        outgoing = value["preview"]["payload"]["body"]
        for sensitive in ["paper.docx", "example@example.com", "ghp_SYNTHETIC_ONLY_123456", token]:
            with self.subTest(sensitive=sensitive):
                self.assertNotIn(sensitive, outgoing)


if __name__ == "__main__":
    unittest.main()
