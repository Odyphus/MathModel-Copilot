"""Check real isolated execution metadata and bound lock-file behavior."""
import copy
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_copilot_runtime import make_project
import copilot_domain as domain
from copilot_run_environment import observe_git


class RunEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="preview-run-env-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root, count=1)

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def execute(self):
        result = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
                    dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]
        self.assertEqual(result["status"], "executed", result)
        return result, self.rt.read()["copilot"]["objects"][result["object_id"]]["payload"]

    def test_no_git_does_not_forge_commit_and_code_identity_is_retained(self):
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", {"question": "Q1", "git_commit": "f" * 40},
                                    [self.ids["model"]], ["solver.py"])
        with patch("copilot_run_environment.shutil.which", return_value=None):
            _, run = self.execute()
        self.assertEqual(run["git_commit"], "")
        self.assertEqual(run["code_manifest_id"], self.ids["code"])
        manifest = self.rt.read()["copilot"]["objects"][self.ids["code"]]
        self.assertEqual(run["code_manifest_hash"], manifest["payload_hash"].upper())
        checked = self.rt.validate_run(self.rev(), run["run_id"] + "@1", "checker.py",
                     ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"], checked)
        report = self.rt.read()["copilot"]["objects"][checked["validation_id"]]["payload"]
        self.assertEqual(report["code_manifest_id"], self.ids["code"])
        forged = copy.deepcopy(report)
        forged["code_manifest_hash"] = "0" * 64
        self.assertTrue(domain.validate_run_report(self.root, domain.seal_record(forged), run))

    def test_actual_child_interpreter_reports_scientific_distribution_versions(self):
        _, run = self.execute()
        observation = run["environment"]["scientific_libraries"]
        self.assertEqual(observation["status"], "observed", observation)
        self.assertEqual(observation["executable"], sys.executable)
        self.assertIn("not_loaded_modules", observation["scope"])
        for package in ("numpy", "scipy", "cvxpy"):
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                self.assertEqual(observation["libraries"][package]["status"], "not_installed")
            else:
                self.assertEqual(observation["libraries"][package]["version"], version)

    def test_environment_lock_is_snapshotted_without_claiming_environment_match(self):
        lock = self.root / "requirements.lock"
        lock.write_text("numpy==999.0.0\n", encoding="utf-8")
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", {"question": "Q1", "environment_lock": "requirements.lock"},
                                    [self.ids["model"]], ["solver.py"])
        result, run = self.execute()
        observed = run["environment"]["environment_lock"]
        self.assertEqual(observed["binding"]["sha256"], domain.sha256_file(lock))
        self.assertEqual(observed["environment_match"], "not_verified")
        run_dir = self.root / Path(result["receipt"]).parent
        self.assertEqual((run_dir / "requirements.lock").read_bytes(), lock.read_bytes())

    def test_false_or_outside_lock_binding_rejected_before_registration(self):
        (self.root / "requirements.lock").write_text("numpy==1\n", encoding="utf-8")
        for lock in ("../outside.lock", "missing.lock", {"path": "requirements.lock", "sha256": "0" * 64}, None):
            before = self.rev()
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                self.reg("CodeManifest", "code.Q1", {"question": "Q1", "environment_lock": lock},
                         [self.ids["model"]], ["solver.py"])
            self.assertEqual(self.rev(), before)

    def test_lock_drift_prevents_run(self):
        lock = self.root / "requirements.lock"
        lock.write_text("numpy==1\n", encoding="utf-8")
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", {"question": "Q1", "environment_lock": "requirements.lock"},
                                    [self.ids["model"]], ["solver.py"])
        lock.write_text("numpy==2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "失效"):
            self.execute()


if __name__ == "__main__":
    unittest.main()
