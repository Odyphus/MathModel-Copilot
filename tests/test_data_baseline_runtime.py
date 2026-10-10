"""Actual receipts, current coverage and invalidation; original synthetic data."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_runtime import Runtime, project_status
from copilot_data import binding
from copilot_domain import seal_record

entry = ROOT / "examples/data_baselines/run_example.py"
spec = importlib.util.spec_from_file_location("data_baseline_example", entry)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class DataBaselineRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / "project"
        cls.report = example.run_example(cls.root)

    def test_run_validation_result_receipts_and_known_metrics(self):
        report = self.report
        self.assertEqual(report["metrics"]["Q1"]["energy_total"], 1440)
        self.assertEqual(report["metrics"]["Q1"]["objective"], 4260)
        self.assertAlmostEqual(report["metrics"]["Q2"]["test_mae"], 0)
        self.assertEqual(report["metrics"]["Q2"]["baseline_mae"], 6)
        cp = Runtime(self.root).read()["copilot"]
        for ids in report["objects"].values():
            self.assertEqual(cp["objects"][ids["result"]]["status"], "verified")
            self.assertEqual(cp["objects"][ids["run"]]["execution"]["returncode"], 0)
            self.assertTrue(any(item["path"].endswith("receipt.json") for item in cp["objects"][ids["run"]]["files"]))
        self.assertTrue(report["status"]["requirements"]["complete"])
        self.assertFalse(report["status"]["submission"]["ready"])

    def test_parameter_change_invalidates_old_run_and_reexecution_recovers(self):
        change = self.report["parameter_change"]
        self.assertEqual((change["old_objective"], change["new_objective"]), (3960, 4260))
        cp = Runtime(self.root).read()["copilot"]
        self.assertEqual(cp["objects"][change["first_run"]]["status"], "stale")
        self.assertNotEqual(change["first_run"], self.report["objects"]["Q1"]["run"])

    def test_raw_attachment_drift_seen_without_rewriting_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            shutil.copytree(self.root, root)
            before = (root / "state/decision_log.json").read_bytes()
            power = root / "power.csv"
            power.write_text(power.read_text(encoding="utf-8").replace(",60", ",61", 1), encoding="utf-8")
            status = project_status(root, Runtime(root).read())
            self.assertFalse(status["requirements"]["complete"])
            self.assertEqual(status["requirements"]["questions"]["Q2"], "verified")
            self.assertEqual((root / "state/decision_log.json").read_bytes(), before)

    def test_forged_report_rejected_before_registration_transaction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            shutil.copytree(self.root, root)
            rt = Runtime(root)
            cp = rt.read()["copilot"]
            contract = json.loads(json.dumps(cp["objects"][self.report["objects"]["Q1"]["data"]]["payload"]))
            report_ref = contract["adapter"]["report"]["path"]
            report = json.loads((root / report_ref).read_text(encoding="utf-8"))
            report["fields"][2]["unit"] = "Wh"
            (root / report_ref).write_text(json.dumps(report), encoding="utf-8")
            changed = binding(root, report_ref)
            contract["adapter"]["report"] = changed
            contract["inventory"]["entries"][3] = changed
            contract["inventory"] = seal_record(contract["inventory"])
            before = (root / "state/decision_log.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "重读不一致"):
                rt.register(cp["revision"], "DataContract", "data.Q1", contract, dependencies=[self.report["objects"]["Q1"]["contract"]])
            self.assertEqual((root / "state/decision_log.json").read_bytes(), before)

    def test_independent_checker_rejects_modified_solver_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "run"
            cp = Runtime(self.root).read()["copilot"]
            run = cp["objects"][self.report["objects"]["Q1"]["run"]]
            output = next(item["path"] for item in run["payload"]["outputs"] if item["path"].endswith("result.json"))
            shutil.copytree((self.root / output).parent, root)
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            result["objective"] += 1
            (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "examples/data_baselines/checker.py"), str(root), str(root / "bad-check.json")], capture_output=True)
            self.assertEqual(completed.returncode, 1)
            report = json.loads((root / "bad-check.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["status"] == "fail" for item in report["checks"]))


if __name__ == "__main__":
    unittest.main()
