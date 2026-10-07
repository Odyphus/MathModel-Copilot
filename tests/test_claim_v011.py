"""Claim assurance must follow checked content, never an author's type label."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_copilot_runtime import make_project
from copilot_runtime import usable, _put, project_status
from copilot_delivery import Delivery
import copilot_domain as domain


class ClaimContentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.rt, self.ids, _ = make_project(self.root, count=1)
        self.run = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
            dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        checked = self.rt.validate_run(self.rev(), self.run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"])
        self.result = checked["result_id"]
        run = self.rt.read()["copilot"]["objects"][self.run]["payload"]
        self.base = {"paper_anchor":"results", "formal_run_id":self.run, "requirement_ids":["REQ-Q1-001"],
            "data_sources":[run["data_hash"]], "code_locations":["solver.py"], "tables":[run["outputs"][0]["path"]],
            "validation_evidence":["Q1.run.formal"], "limitations":["Synthetic deterministic length case only."]}

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def claim(self, text, kind="method", key="C", **fields):
        payload = dict(self.base, claim_id=key, claim=text, claim_type=kind, **fields)
        return self.rt.claim(self.rev(), payload, [self.result])["result"]["claim_id"]

    def section(self, claim_id, text):
        (self.root / "section.md").write_text(text + " [[claim:" + claim_id + "]]", encoding="utf-8")
        return Delivery(self.root).section(self.rev(), "paper.results", "section.md", [claim_id])

    def test_false_result_never_verified_under_any_type(self):
        for kind in ("numerical", "method", "model", "theory", "limitation"):
            with self.subTest(kind=kind):
                try:
                    oid = self.claim("The computed length is 999 m.", kind, "false." + kind)
                except ValueError:
                    continue
                self.assertNotEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "verified")
                with self.assertRaises(ValueError):
                    self.section(oid, "The computed length is 999 m.")
                with self.assertRaises(ValueError):
                    self.rt.cover(self.rev(), "REQ-Q1-001", {"value":oid})

    def test_true_result_is_bound_for_every_type(self):
        for kind in ("numerical", "method", "model", "theory", "limitation"):
            with self.subTest(kind=kind):
                oid = self.claim("The computed length is 10 m.", kind, "true." + kind)
                obj = self.rt.read()["copilot"]["objects"][oid]
                self.assertEqual(obj["status"], "verified")
                self.assertTrue(obj["numeric_bindings"])
                self.section(oid, "The computed length is 10 m.")

    def test_method_numbers_are_preserved_without_false_assurance(self):
        for i, text in enumerate(("Method 2 was described in 2018.", "We use the formula y=2n.", "步骤 2：按公式 y=2n 计算。")):
            with self.subTest(text=text):
                oid = self.claim(text, "method", "note." + str(i))
                obj = self.rt.read()["copilot"]["objects"][oid]
                self.assertEqual(obj["payload"]["claim"], text)
                self.assertEqual(obj["status"], "generated")
                self.assertEqual(obj["payload"]["status"], "draft")
                self.assertFalse(obj["claim_assurance"]["verified"])

    def test_plain_method_and_qualitative_result_need_content_evidence(self):
        for i, text in enumerate(("We use direct addition.", "Our method always outperforms the baseline.")):
            oid = self.claim(text, "method", "plain." + str(i))
            self.assertEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "generated")
            with self.assertRaises(ValueError):
                self.section(oid, text)

    def test_actual_evidence_requirements_cannot_be_removed_by_type(self):
        for kind in ("method", "model", "theory", "limitation"):
            for field in ("data_sources", "code_locations", "validation_evidence"):
                with self.subTest(kind=kind, field=field), self.assertRaises(ValueError):
                    self.claim("The computed length is 10 m.", kind, "missing", **{field:[]})

    def test_old_verified_type_bypass_is_unusable_without_rewriting_history(self):
        # Simulates the exact previously-issued legacy envelope, not a new result.
        payload = dict(self.base, claim_id="legacy.bad", claim="The computed length is 999 m.", claim_type="method", status="pass")
        def legacy(log):
            oid = _put(log, "EvidenceMapEntry", "legacy.bad", payload, [self.result], status="verified")
            log["copilot"]["objects"][oid]["numeric_bindings"] = []
            return oid
        oid = self.rt._tx(self.rev(), "fixture", "Load legacy envelope for regression", legacy)["result"]
        before = self.rt.store.path.read_bytes()
        cp = self.rt.read()["copilot"]
        self.assertFalse(usable(self.root, cp, oid, verified=True))
        self.assertIn(oid, project_status(self.root, self.rt.read())["stale_objects"])
        with self.assertRaises(ValueError):
            self.section(oid, payload["claim"])
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_forged_legacy_binding_does_not_replace_actual_metric(self):
        payload = dict(self.base, claim_id="legacy.forged", claim="The computed length is 999 m.", claim_type="method", status="pass")
        def legacy(log):
            oid = _put(log, "EvidenceMapEntry", "legacy.forged", payload, [self.result], status="verified")
            log["copilot"]["objects"][oid]["numeric_bindings"] = [{"text":"999", "sources":[{"result_id":self.result, "metric_path":".value", "value":999}]}]
            return oid
        oid = self.rt._tx(self.rev(), "fixture", "Load legacy cached binding for regression", legacy)["result"]
        self.assertFalse(usable(self.root, self.rt.read()["copilot"], oid, verified=True))
        with self.assertRaises(ValueError):
            self.section(oid, payload["claim"])

    def test_legacy_valid_numerical_claim_remains_usable(self):
        oid = self.claim("The computed length is 10 m.", "numerical")
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], oid, verified=True))
        self.section(oid, "The computed length is 10 m.")

    def test_display_whitespace_does_not_change_sign_or_scale(self):
        for i, literal in enumerate(("- 10", "−\u00a010", "−\n10", "–10", "10 %", "1e - 2")):
            with self.subTest(literal=literal):
                oid = self.claim("The computed length is " + literal + " m.", key="space." + str(i))
                self.assertNotEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "verified")
        for i, literal in enumerate(("+ 10", "1e 1")):
            oid = self.claim("The computed length is " + literal + " m.", key="positive." + str(i))
            self.assertEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "verified")

    def test_result_heading_does_not_bypass_section_numbers(self):
        oid = self.claim("The computed length is 10 m.", "numerical")
        with self.assertRaisesRegex(ValueError, "Unsupported numerical"):
            self.section(oid, "# The computed length is 999 m.\n\nThe computed length is 10 m.")

    def test_adjacent_operators_never_hide_an_unsupported_literal(self):
        for i, literal in enumerate(("10–999", "10-999", "10+999", "10−999", "10—999", "10--999", "10+.999")):
            with self.subTest(literal=literal):
                oid = self.claim("The computed length is " + literal + " m.", key="adjacent." + str(i))
                self.assertNotEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "verified")
        oid = self.claim("The measured endpoints are 10–10 m.", key="adjacent.positive")
        self.assertEqual(self.rt.read()["copilot"]["objects"][oid]["status"], "verified")

    def test_qualitative_statement_must_be_actually_returned_by_checker(self):
        statement = "Independent addition matches the result."
        checker = self.root / "checker.py"
        checker.write_text(checker.read_text(encoding="utf-8").replace("'metrics':{'value':actual}",
            "'metrics':{'value':actual, 'statement':" + repr(statement) + "}"), encoding="utf-8")
        self.ids["plan"] = self.rt.register(self.rev(), "ValidationPlan", "plan.Q1",
            {"question":"Q1", "checker":{"path":"checker.py", "sha256":domain.sha256_file(checker)},
             "checks":[{"check_id":"known", "method":"independent addition", "criterion":"expected addition matches"}]},
            dependencies=[self.ids["model"]])["result"]["object_id"]
        self.run = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
            dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        checked = self.rt.validate_run(self.rev(), self.run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"])
        self.result = checked["result_id"]
        run = self.rt.read()["copilot"]["objects"][self.run]["payload"]
        self.base.update(formal_run_id=self.run, tables=[run["outputs"][0]["path"]])
        oid = self.claim(statement, "method", "qualitative")
        obj = self.rt.read()["copilot"]["objects"][oid]
        self.assertEqual(obj["status"], "verified")
        self.assertTrue(obj["claim_assurance"]["statement_bindings"])
        self.section(oid, statement)
        false = self.claim("Independent addition disproves the result.", "method", "qualitative.false")
        self.assertEqual(self.rt.read()["copilot"]["objects"][false]["status"], "generated")


if __name__ == "__main__":
    unittest.main()
