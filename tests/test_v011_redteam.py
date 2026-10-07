"""Independent adjacent attacks for v0.1.1; no implementation patches.

MATHMODEL_TEST_REPO selects an older read-only implementation for pre-fix runs.
MATHMODEL_V01_BAD_PROJECT optionally supplies a real v0.1-created bad project;
the test always copies it before consumption. Otherwise a synthetic historical
envelope exercises the same legacy schema through a normal Store fixture write.
MATHMODEL_V01_HEADING_PROJECT similarly supplies a real v0.1-created section
whose unsupported numeric heading was accepted despite its legitimate claim.
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(os.environ.get("MATHMODEL_TEST_REPO", Path(__file__).resolve().parents[1])).resolve()
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "tests")]
from test_copilot_runtime import make_project
from copilot_context import build_context, acknowledge
from copilot_delivery import Delivery
from copilot_runtime import Runtime, _put, usable, project_status, bind_file
from copilot_store import digest
import copilot_domain as domain


def reseal(context):
    result = copy.deepcopy(context)
    result["common_hash"] = digest(result["common"])
    result.pop("context_id", None)
    result["context_id"] = digest(result)
    return result


class ClaimBoundaryRedTeam(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root, count=1)
        self.run = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
            dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        checked = self.rt.validate_run(self.rev(), self.run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"], checked)
        self.result = checked["result_id"]
        obj = self.rt.read()["copilot"]["objects"]
        self.assertEqual(obj[self.result]["payload"]["metrics"], {"value": 10})
        self.base = {
            "paper_anchor": "results", "formal_run_id": self.run, "requirement_ids": ["REQ-Q1-001"],
            "data_sources": [self.ids["data"]], "code_locations": ["solver.py"],
            "tables": [obj[self.run]["payload"]["outputs"][0]["path"]], "validation_evidence": ["Q1.run.formal"],
            "limitations": ["Only this deterministic synthetic case."],
        }

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def claim(self, key, kind, text):
        payload = dict(self.base, claim_id=key, claim_type=kind, claim=text)
        return self.rt.claim(self.rev(), payload, [self.result])["result"]["claim_id"]

    def section(self, claim_id, text, key="paper.test"):
        path = self.root / "section.md"
        path.write_text(text + " [[claim:" + claim_id + "]]\n", encoding="utf-8")
        return Delivery(self.root).section(self.rev(), key, "section.md", [claim_id])

    def test_false_result_cannot_gain_verification_under_any_nonnumerical_label(self):
        for kind in ("method", "model", "theory", "limitation"):
            with self.subTest(kind=kind):
                claim_id = self.claim("false." + kind, kind, "The computed length is 999 m.")
                cp = self.rt.read()["copilot"]
                self.assertNotEqual(cp["objects"][claim_id]["status"], "verified")
                self.assertFalse(usable(self.root, cp, claim_id, verified=True))

    def test_label_change_cannot_close_requirement(self):
        for kind in ("method", "theory", "limitation"):
            with self.subTest(kind=kind):
                claim_id = self.claim("cover." + kind, kind, "The measured error is 999%.")
                with self.assertRaises(ValueError):
                    self.rt.cover(self.rev(), "REQ-Q1-001", {"value": claim_id})

    def test_text_matching_alone_cannot_make_fake_result_section_verified(self):
        for kind, token in (("method", "999"), ("model", ".10"), ("theory", "−10"), ("limitation", "10e2")):
            with self.subTest(kind=kind, token=token):
                text = "The measured output is " + token + " m."
                claim_id = self.claim("paper." + kind, kind, text)
                with self.assertRaises(ValueError):
                    self.section(claim_id, text, "section." + kind)

    def test_actual_metric_keeps_numerical_and_method_claims_usable(self):
        for kind in ("numerical", "method"):
            with self.subTest(kind=kind):
                text = "The computed length is 10 m."
                claim_id = self.claim("good." + kind, kind, text)
                cp = self.rt.read()["copilot"]
                self.assertEqual(cp["objects"][claim_id]["status"], "verified")
                self.assertTrue(cp["objects"][claim_id].get("numeric_bindings"))
                section_id = self.section(claim_id, text, "section.good." + kind)["result"]["section_id"]
                self.assertEqual(self.rt.read()["copilot"]["objects"][section_id]["status"], "verified")

    def test_false_numerical_control_still_rejected(self):
        with self.assertRaises(ValueError):
            self.claim("false.numerical", "numerical", "The computed length is 999 m.")

    def test_spaced_mathematical_minus_cannot_bind_a_positive_metric(self):
        text = "The computed length is − 10 m."
        claim_id = self.claim("format.negative", "method", text)
        self.assertNotEqual(self.rt.read()["copilot"]["objects"][claim_id]["status"], "verified")
        with self.assertRaises(ValueError):
            self.section(claim_id, text, "paper.negative")

    def test_adjacent_range_and_arithmetic_values_cannot_disappear(self):
        for index, expression in enumerate(("10–999", "10—999", "10-999", "10+999")):
            for kind in ("numerical", "method", "model", "theory", "limitation"):
                with self.subTest(expression=expression, kind=kind):
                    text = "The computed length lies in " + expression + " m."
                    if kind == "numerical":
                        with self.assertRaises(ValueError):
                            self.claim("format.adjacent." + kind + str(index), kind, text)
                    else:
                        claim_id = self.claim("format.adjacent." + kind + str(index), kind, text)
                        self.assertNotEqual(self.rt.read()["copilot"]["objects"][claim_id]["status"], "verified")
                        with self.assertRaises(ValueError):
                            self.section(claim_id, text, "paper.adjacent." + kind + str(index))

    def test_numerical_conclusion_in_heading_still_needs_evidence(self):
        good = self.claim("heading.good", "numerical", "The computed length is 10 m.")
        text = "# The computed length is 999 m.\n\nThe computed length is 10 m."
        with self.assertRaises(ValueError):
            self.section(good, text, "paper.heading")

    def test_normal_methods_years_steps_and_constants_can_be_registered_as_drafts(self):
        texts = ["We use independent addition to check the calculation.",
            "The method follows the 2018 problem statement.", "Step 2 evaluates Equation 1.",
            "The definition doubles n using the constant 2."]
        for index, text in enumerate(texts):
            with self.subTest(text=text):
                claim_id = self.claim("draft." + str(index), "method", text)
                obj = self.rt.read()["copilot"]["objects"][claim_id]
                self.assertNotEqual(obj["status"], "verified", "Registration must not assert unperformed numeric/semantic validation")

    def legacy_bad_claim(self, forged_cache=False):
        actual_project = os.environ.get("MATHMODEL_V01_BAD_PROJECT")
        if actual_project and not forged_cache:
            copied = self.root / "imported-v01"
            shutil.copytree(actual_project, copied)
            self.root, self.rt = copied, Runtime(copied)
            return "CLAIM-BAD@1", "The computed length is 999 m."
        text = "The computed length is 999 m."
        entry = domain.EvidenceMapEntry.from_dict(dict(self.base, claim_id="legacy.bad", claim_type="method", claim=text))
        entry.status = "pass"
        (self.root / "legacy-section.md").write_text(text + " [[claim:legacy.bad@1]]\n", encoding="utf-8")
        def historical_fixture(state):
            oid = _put(state, "EvidenceMapEntry", "legacy.bad", entry.to_dict(), [self.result], [], "verified")
            state["copilot"]["objects"][oid]["numeric_bindings"] = ([{"text": "999", "sources": [
                {"result_id": self.result, "metric_path": ".value", "value": 999}]}] if forged_cache else [])
            _put(state, "PaperSection", "legacy.paper", {"path": "legacy-section.md", "claim_ids": [oid],
                "marker_protocol": "[[claim:versioned-object-id]]"}, [oid], [bind_file(self.root, "legacy-section.md")], "verified")
            return {"object_id": oid}
        oid = self.rt._tx(self.rev(), "qa", "Synthetic legacy v0.1 envelope fixture", historical_fixture)["result"]["object_id"]
        return oid, text

    def test_existing_v01_bad_claim_cannot_be_reused_in_a_new_section(self):
        claim_id, text = self.legacy_bad_claim()
        with self.assertRaises(ValueError):
            self.section(claim_id, text, "paper.reused")

    def test_existing_v01_bad_claim_cannot_complete_requirement(self):
        claim_id, _ = self.legacy_bad_claim()
        with self.assertRaises(ValueError):
            self.rt.cover(self.rev(), "REQ-Q1-001", {"value": claim_id})

    def test_cached_numeric_binding_cannot_replace_actual_result_metrics(self):
        claim_id, text = self.legacy_bad_claim(forged_cache=True)
        with self.assertRaises(ValueError):
            self.section(claim_id, text, "paper.cached")

    def test_existing_legacy_claim_and_section_are_unusable_on_read(self):
        claim_id, _ = self.legacy_bad_claim()
        before = self.rt.store.path.read_bytes()
        cp = self.rt.read()["copilot"]
        self.assertFalse(usable(self.root, cp, claim_id, verified=True))
        sections = [oid for oid, obj in cp["objects"].items() if obj["kind"] == "PaperSection" and claim_id in obj["dependencies"]]
        self.assertTrue(sections)
        for oid in sections:
            self.assertFalse(usable(self.root, cp, oid, verified=True))
        self.assertEqual(before, self.rt.store.path.read_bytes(), "A read must report risk without rewriting the old authority")

    def test_valid_legacy_numerical_claim_remains_usable(self):
        actual_project = os.environ.get("MATHMODEL_V01_BAD_PROJECT")
        if actual_project:
            copied = self.root / "imported-good-v01"
            shutil.copytree(actual_project, copied)
            self.root, self.rt = copied, Runtime(copied)
            claim_id = "CLAIM-GOOD@1"
        else:
            entry = domain.EvidenceMapEntry.from_dict(dict(self.base, claim_id="legacy.good", claim_type="numerical", claim="The computed length is 10 m."))
            entry.status = "pass"
            def historical_fixture(state):
                oid = _put(state, "EvidenceMapEntry", "legacy.good", entry.to_dict(), [self.result], [], "verified")
                state["copilot"]["objects"][oid]["numeric_bindings"] = [{"text": "10", "sources": [
                    {"result_id": self.result, "metric_path": ".value", "value": 10}]}]
                return {"object_id": oid}
            claim_id = self.rt._tx(self.rev(), "qa", "Synthetic legitimate v0.1 claim fixture", historical_fixture)["result"]["object_id"]
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], claim_id, verified=True))
        self.section(claim_id, "The computed length is 10 m.", "paper.legacy.good")

    def test_existing_v01_bad_heading_section_cannot_be_consumed(self):
        actual_project = os.environ.get("MATHMODEL_V01_HEADING_PROJECT")
        if actual_project:
            copied = self.root / "imported-heading-v01"
            shutil.copytree(actual_project, copied)
            self.root, self.rt = copied, Runtime(copied)
            claim_id, section_id = "format.good@1", "format.heading@1"
        else:
            claim_id = self.claim("legacy.heading.good", "numerical", "The computed length is 10 m.")
            path = self.root / "legacy-heading.md"
            path.write_text("# The computed length is 999 m.\n\nThe computed length is 10 m. [[claim:"
                + claim_id + "]]\n", encoding="utf-8")
            def historical_fixture(state):
                sid = _put(state, "PaperSection", "legacy.heading", {"path": "legacy-heading.md",
                    "claim_ids": [claim_id], "marker_protocol": "[[claim:versioned-object-id]]"},
                    [claim_id], [bind_file(self.root, "legacy-heading.md")], "verified")
                return {"object_id": sid}
            section_id = self.rt._tx(self.rev(), "qa", "Synthetic legacy v0.1 heading section fixture", historical_fixture)["result"]["object_id"]
        before = self.rt.store.path.read_bytes()
        cp = self.rt.read()["copilot"]
        self.assertTrue(usable(self.root, cp, claim_id, verified=True), "Its real result claim remains valid")
        self.assertFalse(usable(self.root, cp, section_id, verified=True), "Old section status cannot hide its unsupported heading")
        self.assertEqual(before, self.rt.store.path.read_bytes(), "Read-side migration checks must not rewrite authority")


class ContextProjectionRedTeam(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root)
        self.since = self.rev()
        self.initial_context = build_context(self.root, role="coder", member="reader", since=0)
        self.rt.task(self.rev(), "T1", {"title": "Implement the active model", "role": "coder",
            "requirements": ["REQ-Q1-001"], "dependencies": [self.ids["params"]]})
        self.rt.configure(self.rev(), stage=3)
        self.rt.configure(self.rev(), stage=4)

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def context(self):
        return build_context(self.root, role="coder", task_id="T1", member="reader", since=self.since)

    def reject(self, snapshot):
        with self.assertRaises(ValueError):
            acknowledge(self.root, self.rev(), reseal(snapshot), member="reader", action="received")

    def test_complete_current_projection_is_received(self):
        context = self.context()
        receipt = acknowledge(self.root, self.rev(), context, member="reader", action="received")["result"]
        self.assertEqual(receipt["adoptions"], [])
        self.assertEqual(receipt["verifications"], [])

    def test_authentic_partial_history_receipt_cannot_skip_member_cursor_gap(self):
        context = self.context()
        self.assertGreater(context["changes_since"], 0)
        receipt = acknowledge(self.root, self.rev(), context, member="reader", action="received")["result"]
        self.assertEqual(receipt["received_revision"], 0,
            "A true tail view is receivable, but its missing prefix is not thereby received")
        self.assertTrue(any(x["context_id"] == context["context_id"] for x in receipt["receipts"]))

    def test_late_authentic_prefix_connects_already_received_tail(self):
        context = self.context()
        acknowledge(self.root, self.rev(), context, member="reader", action="received")
        receipt = acknowledge(self.root, self.rev(), self.initial_context, member="reader", action="received")["result"]
        self.assertEqual(receipt["received_revision"], context["source_revision"])
        self.assertEqual(receipt["adoptions"], [])
        self.assertEqual(receipt["verifications"], [])

    def test_resealed_completion_and_submission_facts_are_not_authoritative(self):
        context = self.context()
        context["common"]["blockers"] = []
        context["common"]["requirements"].update(complete=True, verified=99)
        context["common"]["submission"].update(ready=True, blockers=[])
        self.reject(context)

    def test_deleting_required_common_fact_groups_is_detected(self):
        for key in ("requirements", "contracts", "models", "parameters", "current", "decisions", "problem", "submission"):
            with self.subTest(key=key):
                context = self.context()
                context["common"].pop(key)
                self.reject(context)

    def test_removing_one_dependency_from_task_closure_is_detected(self):
        context = self.context()
        self.assertIn(self.ids["contract"], context["objects"])
        context["objects"].pop(self.ids["contract"])
        self.reject(context)

    def test_empty_objects_cannot_masquerade_as_complete_task_context(self):
        context = self.context()
        context["objects"] = {}
        self.reject(context)

    def test_dropping_middle_cumulative_change_is_detected(self):
        context = self.context()
        self.assertGreaterEqual(len(context["changes"]), 3)
        del context["changes"][1]
        self.reject(context)

    def test_truncating_all_cumulative_changes_is_detected(self):
        context = self.context()
        context["changes"] = []
        self.reject(context)

    def test_task_dependencies_and_next_action_are_not_caller_editable(self):
        for field in ("task", "next_action"):
            with self.subTest(field=field):
                context = self.context()
                if field == "task":
                    context["task"]["dependencies"] = []
                    context["task"]["requirements"] = []
                else:
                    context["next_action"] = "Submit the supposedly completed paper now."
                self.reject(context)

    def test_object_display_status_and_current_errors_are_bound(self):
        context = self.context()
        target = context["objects"][self.ids["params"]]
        target["status"] = "verified"
        target["current_errors"] = ["invented problem"]
        self.reject(context)

    def test_authentic_historical_receipt_is_allowed_but_stale_adoption_is_not(self):
        context = self.context()
        self.rt.configure(self.rev(), stage=5)
        (self.root / "problem.txt").write_text("Changed problem source after the context was issued.", encoding="utf-8")
        receipt = acknowledge(self.root, self.rev(), context, member="reader", action="received")["result"]
        self.assertTrue(any(x["context_id"] == context["context_id"] for x in receipt["receipts"]))
        with self.assertRaises(ValueError):
            acknowledge(self.root, self.rev(), context, member="reader", action="adopted", object_ids=[self.ids["params"]])

    def test_resealed_historical_projection_cannot_use_receipt_exception(self):
        context = self.context()
        self.rt.configure(self.rev(), stage=5)
        context["common"]["submission"].update(ready=True, blockers=[])
        context["changes"] = []
        self.reject(context)

    def test_role_views_share_common_facts_and_leave_authority_unchanged(self):
        before = self.rt.store.path.read_bytes()
        contexts = [build_context(self.root, role=role, member="reader", since=self.since) for role in ("modeler", "coder", "writer")]
        self.assertEqual(len({x["common_hash"] for x in contexts}), 1)
        self.assertEqual(before, self.rt.store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
