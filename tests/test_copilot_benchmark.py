"""One real low-cost benchmark run plus adversarial evidence checks."""
from __future__ import annotations
import copy
import importlib.util
import itertools
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/cumcm2018b"
spec = importlib.util.spec_from_file_location("benchmark_checker", EXAMPLE / "checker.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class BenchmarkCheckerTests(unittest.TestCase):
    def test_interval_with_missing_bound_cannot_pass(self):
        samples = [2, 4]
        mean, sd = statistics.mean(samples), statistics.stdev(samples)
        entry = {"sample_counts": samples, "n": 2, "mean": mean, "sd": sd, "minimum": 2, "maximum": 4,
                 "mean_ci95_normal": [mean - 1.96 * sd / 2 ** 0.5, mean + 1.96 * sd / 2 ** 0.5]}
        checker.validate_statistics(entry, 2)
        entry["mean_ci95_normal"] = entry["mean_ci95_normal"][:1]
        with self.assertRaisesRegex(ValueError, "interval"):
            checker.validate_statistics(entry, 2)

    def test_duplicate_sensitivity_cannot_replace_missing_configuration(self):
        summary = {"faults": [{"group": 1, "mode": mode} for mode in ("single", "two")],
                   "sensitivity": [{"group": 1, "mode": mode, "fault_probability": probability, "repair_range": repair}
                        for mode, probability, repair in itertools.product(("single", "two"), (0.005, 0.01, 0.02),
                                                                           ((600, 900), (600, 1200), (900, 1200)))]}
        checker.validate_configuration_coverage(summary, [1])
        summary["sensitivity"][-1] = copy.deepcopy(summary["sensitivity"][0])
        with self.assertRaisesRegex(ValueError, "sensitivity"):
            checker.validate_configuration_coverage(summary, [1])


REQUIRED_HISTORICAL_ASSETS = (
    "CUMCM-2018-Problem-B-English.pdf", "CUMCM-2018-Problem-B-English-Appendix-1.pdf",
    "Case_1_ result_E.xls", "Case_2_ result_E.xls", "Case_3_ result_1_E.xls",
    "Case_3_ result_2_E.xls", "official_parameters.json",
)
MISSING_HISTORICAL_ASSETS = [name for name in REQUIRED_HISTORICAL_ASSETS
                             if not (EXAMPLE / "assets" / name).is_file()]


@unittest.skipIf(MISSING_HISTORICAL_ASSETS,
                 "historical_fixture_missing: " + ", ".join(MISSING_HISTORICAL_ASSETS)
                 + "; obtain authorized assets in a private test copy; see docs/HISTORICAL_FIXTURES.md")
@unittest.skipUnless(importlib.util.find_spec("xlrd") and importlib.util.find_spec("xlwt"),
                     "2018B official XLS integration requires optional xlrd and xlwt")
class BenchmarkIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.workspace = cls.root / "smoke"
        completed = subprocess.run([sys.executable, str(EXAMPLE / "run_benchmark.py"), "--workspace", str(cls.workspace), "--smoke"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=240)
        if completed.returncode:
            raise AssertionError(completed.stdout + completed.stderr)
        cls.report = json.loads((cls.workspace / "benchmark_report.json").read_text(encoding="utf-8"))

    def test_real_smoke_covers_two_questions_without_formal_ready(self):
        report = self.report
        self.assertEqual(report["question_count"], 2)
        self.assertEqual(report["facts"]["requirements"]["questions"], {"Q1": "verified", "Q2": "verified"})
        self.assertEqual(report["facts"]["requirements"]["verified"], 8)
        self.assertFalse(report["old_results_reused"])
        self.assertFalse(report["facts"]["submission"]["ready"])
        metrics = report["objects"]["Q2"]["metrics"]
        self.assertEqual((metrics["trace_count"], metrics["tuning_candidates"], metrics["seed_count"]), (4, 508, 2))
        self.assertEqual((metrics["workbooks"], metrics["sheets_checked"]), (4, 6))
        state = json.loads((self.workspace / "state/decision_log.json").read_text(encoding="utf-8"))["copilot"]
        for question in ("Q1", "Q2"):
            section = state["objects"][report["objects"][question]["section"]]
            self.assertEqual(section["kind"], "PaperSection")
            self.assertEqual(section["status"], "verified")

    def test_checker_rejects_forged_completed_count(self):
        source = self.workspace / self.report["objects"]["Q2"]["directory"]
        copied = self.root / "mutated-run"
        shutil.copytree(source, copied)
        trace_path = copied / "results/trace_group1_single_healthy.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["count"] += 1
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        output = self.root / "rejected.json"
        checked = subprocess.run([sys.executable, str(EXAMPLE / "checker.py"), str(copied), str(output)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(checked.returncode, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["checks"], [])

    def test_existing_workspace_is_preserved(self):
        authority = self.workspace / "state/decision_log.json"
        before = authority.read_bytes()
        repeated = subprocess.run([sys.executable, str(EXAMPLE / "run_benchmark.py"), "--workspace", str(self.workspace), "--smoke"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("existing artifacts will not be overwritten", repeated.stderr)
        self.assertEqual(authority.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
