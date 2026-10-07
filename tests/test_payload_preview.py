from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_payload import payload_help
from copilot_domain import load_structured, sha256_file
from test_copilot_runtime import make_project


class PayloadPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args, code=0, workspace=None):
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/copilot.py"),
            "--workspace", str(workspace or self.root), *args], capture_output=True,
            encoding="utf-8", timeout=25)
        self.assertEqual(completed.returncode, code, completed.stdout + completed.stderr)
        return json.loads(completed.stdout if code == 0 else completed.stderr)

    def payload(self, value):
        path = self.root / "payload.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return "payload.json"

    def test_help_needs_no_project_and_creates_no_files(self):
        unused = self.root / "not-created"
        for name in ("configure", "run", "validate", "stage-record", "decide"):
            with self.subTest(name=name):
                result = self.cli("payload-help", name, workspace=unused)["result"]
                self.assertIn("example", result)
                self.assertTrue(set(result["required_fields"]) <= set(result["example"]))
        self.cli("payload-help", "register", "--kind", "ValidationPlan", workspace=unused)
        self.assertFalse(unused.exists())

    def test_help_rejects_unsupported_kind_without_writing(self):
        self.cli("payload-help", "register", "--kind", "ImaginaryContract", code=2)
        self.cli("payload-help", "run", "--kind", "ValidationPlan", code=2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_configure_help_example_is_accepted_by_real_cli(self):
        self.cli("init", "--competition", "generic")
        example = self.cli("payload-help", "configure")["result"]["example"]
        self.cli("configure", "--expected-revision", "0", "--payload", self.payload(example))
        state = json.loads((self.root / "state/decision_log.json").read_text(encoding="utf-8"))
        self.assertEqual(state["problem_meta"]["title"], example["title"])
        self.assertEqual(state["stages"]["5"]["qi_count"], example["question_count"])

    def test_unknown_configure_fields_are_named_and_preserve_authority(self):
        self.cli("init")
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        for unknown in ("years", "metadata", "submission_ready", "actor", "revision"):
            with self.subTest(unknown=unknown):
                result = self.cli("configure", "--expected-revision", "0", "--payload",
                    self.payload({unknown: "must-not-be-silently-dropped", "title": "partial write forbidden"}), code=2)
                self.assertIn(unknown, result["message"])
                self.assertIn("允许字段", result["message"])
                self.assertIn("question_count", result["message"])
                self.assertNotIn("must-not-be-silently-dropped", result["message"])
                self.assertEqual(authority.read_bytes(), before)

    def test_legitimate_metadata_and_cas_are_preserved(self):
        self.cli("init")
        data = {"title": "测试", "letter": "A", "deadline_iso": "2026-10-07T12:00:00+08:00", "team_size": 3}
        self.cli("configure", "--expected-revision", "0", "--payload", self.payload(data))
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        self.cli("configure", "--expected-revision", "0", "--payload", "payload.json", code=3)
        self.assertEqual(authority.read_bytes(), before)
        state = json.loads(before)
        self.assertEqual({key: state["problem_meta"][key] for key in data}, data)

    def test_runtime_validation_is_not_bypassed(self):
        self.cli("init")
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        for data in ({"question_count": 0}, {"mode": "auto-pass"},
                     {"evaluation_mode": "formal_contest", "problem_year": 2018, "rules_year": 2026}):
            self.cli("configure", "--expected-revision", "0", "--payload", self.payload(data), code=2)
            self.assertEqual(authority.read_bytes(), before)

    def test_missing_and_unknown_run_fields_never_start_execution(self):
        self.cli("init")
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        for data in ({"question": "Q1"}, {**payload_help("run")["example"], "shell": True}):
            result = self.cli("run", "--expected-revision", "0", "--payload", self.payload(data), code=2)
            self.assertIn("允许字段", result["message"])
            self.assertEqual(authority.read_bytes(), before)
        self.assertFalse((self.root / ".copilot/runs").exists())

    def test_validation_plan_help_example_registers_and_runs_real_checker(self):
        rt, ids, _ = make_project(self.root)
        plan = payload_help("register", "ValidationPlan")["example"]
        plan["checker"]["sha256"] = sha256_file(self.root / "checker.py")
        registered = self.cli("register", "--kind", "ValidationPlan", "--key", "plan.Q1",
            "--depends", ids["model"], "--expected-revision", str(rt.read()["copilot"]["revision"]),
            "--payload", self.payload(plan))["result"]
        ids["plan"] = registered["result"]["object_id"]
        run = payload_help("run")["example"]
        run["dependencies"] = [ids[key] for key in ("model", "params", "data", "code", "plan")]
        executed = self.cli("run", "--expected-revision", str(rt.read()["copilot"]["revision"]),
            "--payload", self.payload(run))["result"]["result"]["object_id"]
        validation = payload_help("validate")["example"]
        checked = self.cli("validate", "--run-id", executed,
            "--expected-revision", str(rt.read()["copilot"]["revision"]),
            "--payload", self.payload(validation))["result"]["result"]
        self.assertTrue(checked["passed"], checked)
        cp = rt.read()["copilot"]
        self.assertEqual(cp["objects"][checked["result_id"]]["payload"]["metrics"]["value"], 10)
        self.assertNotEqual(cp["objects"][ids["plan"]]["kind"], "ResultRecord")

    def test_filled_yaml_template_is_accepted_without_changing_its_shape(self):
        rt, ids, _ = make_project(self.root)
        plan = load_structured(ROOT / "templates/copilot/validation_plan.yaml")
        plan["checker"]["sha256"] = sha256_file(self.root / "checker.py")
        plan["checks"][0].update(check_id="known", method="independent addition",
            criterion="value equals independently recomputed sum", evidence_target="result.json")
        result = self.cli("register", "--kind", "ValidationPlan", "--key", "plan.Q1",
            "--depends", ids["model"], "--expected-revision", str(rt.read()["copilot"]["revision"]),
            "--payload", self.payload(plan))["result"]["result"]
        self.assertIn(result["object_id"], rt.read()["copilot"]["objects"])

    def test_placeholder_or_missing_criterion_cannot_register(self):
        rt, ids, _ = make_project(self.root)
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        plan = payload_help("register", "ValidationPlan")["example"]
        for attempt, message in ((plan, "checker"),
                ({**plan, "checker": {**plan["checker"], "sha256": sha256_file(self.root / "checker.py")},
                   "checks": [{"check_id": "known", "method": "addition"}]}, "criterion")):
            rejected = self.cli("register", "--kind", "ValidationPlan", "--key", "plan.Q1",
                "--depends", ids["model"], "--expected-revision", str(rt.read()["copilot"]["revision"]),
                "--payload", self.payload(attempt), code=2)
            self.assertIn(message, rejected["message"])
            self.assertEqual(authority.read_bytes(), before)

    def test_report_cli_keeps_json_and_export_is_create_only(self):
        self.cli("init")
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        result = self.cli("report")["result"]
        self.assertEqual(result["revision"], 0)
        self.assertTrue(result["markdown"])
        self.assertNotIn("saved_to", result)
        exported = self.cli("report", "--output", "reports/progress.md")["result"]
        target = self.root / "reports/progress.md"
        self.assertEqual(target.read_text(encoding="utf-8"), exported["markdown"])
        saved = target.read_bytes()
        self.cli("report", "--output", "reports/progress.md", code=2)
        self.cli("report", "--output", "../outside.md", code=2)
        self.assertEqual(target.read_bytes(), saved)
        self.assertEqual(authority.read_bytes(), before)

    def test_interpretation_review_payload_uses_real_api_field_contract(self):
        self.cli("init")
        authority = self.root / "state/decision_log.json"
        before = authority.read_bytes()
        rejected = self.cli("interpretation-review", "--id", "not-an-object@1", "--expected-revision", "0",
            "--payload", self.payload({"approved_by_user": True}), code=2)
        self.assertIn("approved_by_user", rejected["message"])
        self.assertIn("rationale", rejected["message"])
        self.assertIn("payload-help interpretation-review", rejected["message"])
        self.assertEqual(authority.read_bytes(), before)

    def test_interpretation_help_overview_and_examples_are_read_only(self):
        unused = self.root / "not-created"
        from copilot_interpretation import FIELDS
        for command in ("interpretation", "interpretation-review"):
            overview = self.cli("payload-help", command, workspace=unused)["result"]
            self.assertEqual(set(overview["kinds"]), set(FIELDS))
            for kind in FIELDS:
                result = self.cli("payload-help", command, "--kind", kind, workspace=unused)["result"]
                self.assertTrue(set(result["required_fields"]) <= set(result["example"]))
                self.assertTrue(set(result["example"]) <= set(result["allowed_fields"]))
                if command == "interpretation":
                    self.assertEqual(set(result["allowed_fields"]), FIELDS[kind] | {"legacy_refs"})
                    self.assertNotIn("legacy_sources", result["allowed_fields"])
        self.assertFalse(unused.exists())

    def test_interpretation_templates_and_help_work_without_pyyaml(self):
        for kind in ("AmbiguityEntry", "AssumptionEntry"):
            expected = payload_help("interpretation", kind)
            with patch.dict(sys.modules, {"yaml": None}):
                actual = payload_help("interpretation", kind)
            self.assertEqual(actual["example"], expected["example"])

    def test_real_yaml_templates_register_before_any_problem_contract(self):
        self.cli("init")
        self.cli("configure", "--expected-revision", "0", "--payload", self.payload({"question_count": 1}))
        revision = 1
        for kind, filename, status in (("AmbiguityEntry", "ambiguity_entry.yaml", "open"),
                                       ("AssumptionEntry", "assumption_entry.yaml", "proposed")):
            text = (ROOT / "templates/copilot" / filename).read_text(encoding="utf-8")
            (self.root / filename).write_text(text, encoding="utf-8")
            result = self.cli("interpretation", "--kind", kind, "--expected-revision", str(revision),
                              "--payload", filename)["result"]
            revision = result["revision"]
            self.assertEqual(result["result"]["status"], status)
            state = json.loads((self.root / "state/decision_log.json").read_text(encoding="utf-8"))
            cp = state["copilot"]
            self.assertFalse(any(obj["kind"] == "ProblemContract" for obj in cp["objects"].values()))
            obj = cp["objects"][result["result"]["object_id"]]
            self.assertEqual(obj["payload"]["status"], status)
            self.assertEqual(obj["status"], "recorded")
            self.assertNotIn("review", payload_help("interpretation", kind)["example"])

    def test_interpretation_examples_cannot_forge_review_or_validation(self):
        self.cli("init")
        self.cli("configure", "--expected-revision", "0", "--payload", self.payload({"question_count": 1}))
        authority = self.root / "state/decision_log.json"
        for kind, forbidden in (("AmbiguityEntry", "resolved"), ("AssumptionEntry", "accepted")):
            example = payload_help("interpretation", kind)["example"]
            before = authority.read_bytes()
            for forged in ({**example, "status": forbidden}, {**example, "review": {"actor": "human", "approved": True}},
                           {**example, "legacy_sources": []}):
                self.cli("interpretation", "--kind", kind, "--expected-revision", "1",
                         "--payload", self.payload(forged), code=2)
                self.assertEqual(authority.read_bytes(), before)
        example = payload_help("interpretation", "AmbiguityEntry")["example"]
        created = self.cli("interpretation", "--kind", "AmbiguityEntry", "--expected-revision", "1",
                           "--payload", self.payload(example))["result"]
        before = authority.read_bytes()
        review = payload_help("interpretation-review", "AmbiguityEntry")["example"]
        for forged in ({**review, "evidence_files": []}, review,
                       {"action": "validate", "rationale": "AI says checked", "result_ids": ["imaginary-result@1"]}):
            self.cli("interpretation-review", "--id", created["result"]["object_id"],
                     "--expected-revision", str(created["revision"]), "--payload", self.payload(forged), code=2)
            self.assertEqual(authority.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
