"""User-facing completion statements stay tied to a live authority observation."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_copilot_runtime import make_project
from copilot_summary import report


class FactualReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root)

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def verified(self):
        run = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
            dependencies=[self.ids[key] for key in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        checked = self.rt.validate_run(self.rev(), run, "checker.py",
            ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.rt.cover(self.rev(), "REQ-Q1-001", {"value": checked["result_id"]})
        return checked["result_id"]

    def test_unregistered_external_pass_text_does_not_grant_verification(self):
        (self.root / "results").mkdir()
        (self.root / "results/claimed.md").write_text("5/5 verified; 18,925,485; user approved", encoding="utf-8")
        before = self.rt.store.path.read_bytes()
        value = report(self.root)
        facts = value["report_facts"]
        self.assertEqual(0, facts["requirements"]["verified"])
        self.assertEqual([], facts["results"])
        self.assertFalse(facts["submission"]["ready"])
        self.assertIn("results/claimed.md", facts["untracked_outputs"]["files"])
        self.assertNotIn("18,925,485", value["markdown"])
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_current_verified_result_with_lineage_and_missing_other_questions(self):
        rid = self.verified()
        value = report(self.root)
        facts = value["report_facts"]
        self.assertEqual(1, facts["requirements"]["verified"])
        self.assertEqual({"Q1": "verified", "Q2": "missing", "Q3": "missing"}, facts["requirements"]["questions"])
        self.assertFalse(facts["submission"]["ready"])
        result = next(r for r in facts["results"] if r["id"] == rid)
        self.assertEqual(10, result["metrics"]["value"])
        self.assertTrue({"ProblemContract", "ModelSpec", "RunRecord", "ValidationReport"} <= {o["kind"] for o in result["lineage"]})

    def test_same_revision_file_drift_removes_current_result(self):
        self.verified()
        first = report(self.root)
        before_rev = self.rev()
        (self.root / "solver.py").write_text("print('changed')", encoding="utf-8")
        after = report(self.root)
        self.assertEqual(before_rev, self.rev())
        self.assertNotEqual(first["file_observation_hash"], after["file_observation_hash"])
        self.assertEqual(0, after["report_facts"]["requirements"]["verified"])
        self.assertFalse(after["report_facts"]["results"])

    def test_superseded_parameters_do_not_reuse_old_verified_metrics(self):
        self.verified()
        old = self.rt.read()["copilot"]["objects"][self.ids["params"]]["payload"]
        payload = copy.deepcopy(old)
        payload["entries"][0]["current_value"] = 7
        self.reg("ParameterSet", "params.Q1", payload, [self.ids["model"]])
        self.assertEqual([], report(self.root)["report_facts"]["results"])

    def test_save_is_create_only_and_not_a_state_write(self):
        before = self.rt.store.path.read_bytes()
        value = report(self.root, "outputs/事实简报.md")
        saved = self.root / value["saved_to"]
        self.assertEqual(value["markdown"], saved.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            report(self.root, "outputs/事实简报.md")
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_rejects_unsafe_or_authority_paths(self):
        for path in ("../escape.md", "state/summary.md", ".copilot/summary.md", ".git/summary.md", "outputs/report.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                report(self.root, path)

    def test_large_untracked_inventory_admits_truncation(self):
        from copilot_summary import _untracked
        (self.root / "outputs").mkdir()
        for i in range(3):
            (self.root / f"outputs/{i}.md").write_text("not evidence", encoding="utf-8")
        result = _untracked(self.root, set(), limit=2)
        self.assertEqual(2, len(result["files"]))
        self.assertTrue(result["truncated"])

    def test_windows_path_aliases_cannot_write_authority_or_special_files(self):
        before = self.rt.store.path.read_bytes()
        for path in ("state./alias.md", "STATE/alias.md", "state /alias.md",
                     ".copilot. /alias.md", ".git./alias.md", "outputs./alias.md",
                     "outputs/report.md.", "outputs/report.md ", "outputs/CON.md",
                     "outputs/NUL.md", "outputs/COM1.md", "outputs/LPT9.md"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                report(self.root, path)
        self.assertFalse((self.root / "state/alias.md").exists())
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_resolved_alias_into_state_is_rejected(self):
        # Exercise the resolved-path boundary without depending on OS link
        # privileges. A real symlink/junction is resolved by safe_path first.
        with patch("copilot_summary.safe_path", return_value=self.root / "state/alias.md"):
            with self.assertRaises(ValueError):
                report(self.root, "outputs/alias.md")
        self.assertFalse((self.root / "state/alias.md").exists())

    def test_untracked_scan_does_not_follow_directory_aliases(self):
        from copilot_summary import _untracked
        other = self.root / "other-source"
        other.mkdir()
        (other / "not-an-output.md").write_text("not output evidence", encoding="utf-8")
        (self.root / "results").mkdir()
        link = self.root / "results/alias"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(other), str(link))
        else:
            link.symlink_to(other, target_is_directory=True)
        try:
            self.assertEqual([], _untracked(self.root, set())["files"])
            self.assertEqual([], report(self.root)["report_facts"]["untracked_outputs"]["files"])
        finally:
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()
        self.assertEqual("not output evidence", (other / "not-an-output.md").read_text(encoding="utf-8"))

    def test_failed_snapshot_does_not_leave_a_success_report(self):
        from copilot_store import ConflictError
        with patch("copilot_summary.snapshot", side_effect=ConflictError("changed")):
            with self.assertRaises(ConflictError):
                report(self.root, "outputs/not-created.md")
        self.assertFalse((self.root / "outputs/not-created.md").exists())


if __name__ == "__main__":
    unittest.main()
