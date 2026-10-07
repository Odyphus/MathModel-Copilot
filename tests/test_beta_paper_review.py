"""Actual run/state plus synthetic paper-input failures, not real A-problem QA."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from test_copilot_runtime import make_project, SOLVER
from copilot_runtime import Runtime
from copilot_paper_review import review_materials


class BetaPaperReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory()
        root = Path(cls.baseline.name)
        rt, ids, reg = make_project(root)
        (root / "solver.py").write_text(SOLVER + "\nPath('table.csv').write_text('time_s,temperature_c,surface_c\\n100,28,29\\n300,30,31\\n', encoding='utf-8')\n", encoding="utf-8")
        ids["code"] = reg("CodeManifest", "code.Q1", {"question": "Q1"}, [ids["model"]], ["solver.py"])
        run = rt.execute(rt.read()["copilot"]["revision"], "Q1", ["{python}", "solver.py"],
                         ["result.json", "table.csv"], dependencies=[ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        cls.result_id = rt.validate_run(rt.read()["copilot"]["revision"], run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]["result_id"]
        obj = rt.read()["copilot"]["objects"][cls.result_id]
        path = next(f["path"] for f in obj["files"] if f["path"].endswith("/table.csv"))
        cls.contract = {"version": "0.1", "tables": [{"id": "table_q1", "question": "Q1", "source_id": cls.result_id,
            "result_id": cls.result_id, "parameter_object_id": ids["params"], "path": path,
            "required_columns": ["time_s", "temperature_c", "surface_c"],
            "numeric_columns": {"temperature_c": {"unit": "degC", "basis": "synthetic test known range", "min": 0, "max": 100},
                                "surface_c": {"unit": "degC", "basis": "synthetic test known range", "min": 0, "max": 100}}}], "manuscripts": []}

    @classmethod
    def tearDownClass(cls):
        cls.baseline.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(self.baseline.name, self.root)
        self.rt = Runtime(self.root)
        self.plan = copy.deepcopy(self.contract)

    def check(self):
        return review_materials(self.root, self.plan)

    def derived(self, csv_text, deps=None):
        (self.root / "paper-table.csv").write_text(csv_text, encoding="utf-8")
        aid = self.rt.register(self.rt.read()["copilot"]["revision"], "ArtifactRecord", "paper.table", {"path": "paper-table.csv"},
                               dependencies=[self.result_id] if deps is None else deps)["result"]["object_id"]
        self.plan["tables"][0].update(source_id=aid, path="paper-table.csv")

    def test_actual_validated_run_is_accepted_without_writing_authority(self):
        before = self.rt.store.path.read_bytes()
        report = self.check()
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["not_verified"])
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_other_question_cannot_borrow_same_numeric_table(self):
        self.plan["tables"][0]["question"] = "Q2"
        report = self.check()
        self.assertFalse(report["passed"])
        self.assertIn("小问", report["findings"][0]["message"])

    def test_parameter_identity_cannot_be_replaced_by_another_object(self):
        self.plan["tables"][0]["parameter_object_id"] = self.result_id
        report = self.check()
        self.assertFalse(report["passed"])
        self.assertIn("参数版本", report["findings"][0]["message"])

    def test_derived_table_must_depend_on_result(self):
        self.derived("time_s,temperature_c,surface_c\n100,28,29\n", deps=[])
        self.assertFalse(self.check()["passed"])

    def test_multiple_source_results_cannot_be_cherry_picked(self):
        cp = self.rt.read()["copilot"]
        source_run = cp["objects"][cp["objects"][self.result_id]["payload"]["run_id"]]
        run_id = self.rt.execute(cp["revision"], "Q1", ["{python}", "solver.py"], ["result.json", "table.csv"],
                                 dependencies=source_run["dependencies"])["result"]["object_id"]
        second = self.rt.validate_run(self.rt.read()["copilot"]["revision"], run_id, "checker.py",
                                      ["{python}", "{checker}", "{run}", "{report}"])["result"]["result_id"]
        self.derived("time_s,temperature_c,surface_c\n100,28,29\n", deps=[self.result_id, second])
        self.assertFalse(self.check()["passed"])

    def test_missing_surface_column_is_rejected(self):
        self.derived("time_s,temperature_c\n100,28\n")
        self.assertIn("缺少", self.check()["findings"][0]["message"])

    def test_time_value_mapped_to_temperature_fails_declared_range(self):
        self.derived("time_s,temperature_c,surface_c\n1800,1800,29\n")
        report = self.check()
        self.assertFalse(report["passed"])
        self.assertIn("超出声明范围", report["findings"][0]["message"])

    def test_nonfinite_blank_overflow_and_malformed_numeric_values_fail(self):
        for value in ("nan", "NaN", "inf", "-Infinity", "∞", "1e999", "", "broken"):
            with self.subTest(value=value):
                self.derived(f"time_s,temperature_c,surface_c\n100,{value},29\n")
                self.assertFalse(self.check()["passed"])

    def test_missing_geometry_position_can_be_explained_without_nan(self):
        self.derived("time_s,temperature_c,surface_c\n100,位置已在材料外,29\n")
        rule = self.plan["tables"][0]["numeric_columns"]["temperature_c"]
        rule["missing"] = {"位置已在材料外": "收缩后该固定半径已大于当前表面半径，另列真实表面温度"}
        self.assertTrue(self.check()["passed"])
        rule["missing"] = {"nan": "out of geometry"}
        with self.assertRaises(ValueError):
            self.check()

    def test_duplicate_headers_ragged_and_empty_tables_fail(self):
        for text in ("time_s,temperature_c,temperature_c\n100,28,29\n", "time_s,temperature_c,surface_c\n100,28\n", "time_s,temperature_c,surface_c\n", ""):
            with self.subTest(text=text):
                self.derived(text)
                self.assertFalse(self.check()["passed"])

    def test_file_drift_after_successful_observation_fails(self):
        self.assertTrue(self.check()["passed"])
        (self.root / self.plan["tables"][0]["path"]).write_text("time_s,temperature_c,surface_c\n100,29,30\n", encoding="utf-8")
        self.assertFalse(self.check()["passed"])

    def test_upstream_code_drift_fails_even_when_table_unchanged(self):
        with (self.root / "solver.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# drift\n")
        self.assertFalse(self.check()["passed"])

    def test_unbound_path_fails_even_with_identical_table(self):
        source = self.root / self.plan["tables"][0]["path"]
        shutil.copyfile(source, self.root / "copy.csv")
        self.plan["tables"][0]["path"] = "copy.csv"
        self.assertFalse(self.check()["passed"])

    def test_manuscript_nan_is_flagged_and_ordinary_words_are_not(self):
        self.plan["manuscripts"] = ["draft.md"]
        target = self.root / "draft.md"
        target.write_text("表格结果为nan。", encoding="utf-8")
        self.assertFalse(self.check()["passed"])
        target.write_text("finance, banana, infinity_model", encoding="utf-8")
        self.assertTrue(self.check()["passed"])

    def test_invalid_contracts_cannot_claim_pass(self):
        for mutate in (lambda p: p.update(tables=[]), lambda p: p["tables"].append(copy.deepcopy(p["tables"][0])),
                       lambda p: p["tables"][0].update(numeric_columns={}),
                       lambda p: p["tables"][0]["numeric_columns"]["surface_c"].update(max=float("nan"))):
            with self.subTest(mutate=mutate):
                self.plan = copy.deepcopy(self.contract)
                mutate(self.plan)
                with self.assertRaises(ValueError):
                    self.check()

    def test_cli_reports_failure_and_keeps_state_unchanged(self):
        self.derived("time_s,temperature_c\n100,28\n")
        path = self.root / "review.json"
        path.write_text(json.dumps(self.plan), encoding="utf-8")
        before = self.rt.store.path.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/copilot_paper_review.py"), "--workspace", str(self.root), "--contract", "review.json"],
                                capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["passed"])
        self.assertEqual(before, self.rt.store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
