"""Observable regressions reproduced in the upstream audit (F01–F07)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import doctor
import extract_diff
import render_ai_usage
import render_paper
import score_artifact
import status
from copilot_store import Store, ConflictError


def state_template():
    return json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))


def critique(stage=1, variant="stage_level"):
    return {"stage_id": stage, "iteration": 0,
            "scores": {dim: {"score": 9, "evidence": "Reviewer observation; not execution proof"}
                       for dim in score_artifact.load_dim_whitelist("cumcm", stage, variant)},
            "min_score": 9, "mean_score": 9, "issues": [], "verdict": "pass_early"}


class StateTruthRegressions(unittest.TestCase):
    def test_f01_ready_flag_cannot_bypass_missing_evidence(self):
        state = state_template()
        state["current_stage"] = 9
        state["stages"]["9"]["submission_ready"] = True
        for gate, _ in status.STAGE9_GATES:
            state["stages"]["9"]["compliance_checks"][gate] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stored = Store(root / "state/decision_log.json").create(state)
            report = status.build_status(stored, workspace=root)
        self.assertFalse(report["submission_ready"])
        self.assertTrue(report["facts"]["submission"]["blockers"])

    def test_f03_navigation_without_reviews_is_zero_review_progress(self):
        state = state_template()
        state["current_stage"] = 9
        report = status.build_status(state)
        self.assertEqual(report["progress"]["completed"], 0)
        self.assertIn("非完成度", status.render_text(report))

    def test_f02_incomplete_aggregate_preserves_state_and_single_qi_still_works(self):
        state = state_template()
        state["stages"]["5"]["qi_count"] = 3
        rows = [{"qi": key, "min": 9, "mean": 9, "issues": []} for key in ("Q1", "Q2")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_log.json"
            Store(path).create(state)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Q3"):
                score_artifact.update_stage5_aggregate({}, rows, None, path)
            self.assertEqual(path.read_bytes(), before)
            score_artifact.update_decision_log(5, critique(5, "per_qi"), path, "per_qi", "Q1")
            saved = Store(path).read()
            self.assertEqual(saved["scores"]["5_per_qi"][-1]["qi_id"], "Q1")
            self.assertEqual(saved["scores"]["5_per_qi"][-1]["evidence_status"], "review_only")

    def test_f02_weights_bind_to_ids_when_results_reordered(self):
        rows = [{"qi": "Q1", "min": 7, "mean": 7, "issues": []},
                {"qi": "Q2", "min": 9, "mean": 9, "issues": []}]
        original = score_artifact.compute_stage5_verdict(rows, [3, 1])
        reordered = score_artifact.compute_stage5_verdict(rows[::-1], [3, 1])
        mapped = score_artifact.compute_stage5_verdict(rows[::-1], {"Q1": 3, "Q2": 1})
        self.assertEqual(original["weighted_mean"], 7.5)
        self.assertEqual(reordered["weighted_mean"], original["weighted_mean"])
        self.assertEqual(mapped["weighted_mean"], original["weighted_mean"])

    def test_new_per_qi_review_invalidates_old_complete_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_log.json"
            state = state_template()
            state["stages"]["5"]["qi_count"] = 1
            Store(path).create(state)
            score_artifact.update_stage5_aggregate({}, [{"qi": "Q1", "min": 9, "mean": 9, "issues": []}], None, path)
            score_artifact.update_decision_log(5, critique(5, "per_qi"), path, "per_qi", "Q1")
            self.assertFalse(Store(path).read()["stages"]["5"]["aggregate"]["complete"])

    def test_f04_stale_score_write_cannot_replace_teammate_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_log.json"
            store = Store(path)
            store.create(state_template())
            store.transact(0, "teammate", "record note", lambda state: state["problem_meta"].update(title="Keep this"))
            before = path.read_bytes()
            with self.assertRaises(ConflictError):
                score_artifact.update_decision_log(1, critique(), path, expected_revision=0)
            self.assertEqual(path.read_bytes(), before)
            score_artifact.update_decision_log(1, critique(), path, expected_revision=1)
            self.assertEqual(store.read()["problem_meta"]["title"], "Keep this")

    def test_f07_nested_invalid_state_is_rejected_by_doctor(self):
        cases = [("count", lambda s: s["stages"]["5"].update(qi_count=-1)),
                 ("AI ledger", lambda s: s["compliance"].update(ai_usage="verified")),
                 ("team", lambda s: s["problem_meta"].update(team_size="three"))]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state/decision_log.json"
            path.parent.mkdir()
            for name, change in cases:
                with self.subTest(name=name):
                    state = state_template()
                    change(state)
                    path.write_text(json.dumps(state), encoding="utf-8")
                    check = next(x for x in doctor.run_checks("cumcm", root, check_tools=False) if x.name == "workspace-state")
                    self.assertEqual(check.status, "fail")

    def test_f07_invalid_yaml_cannot_pass_name_regex(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SKILL.md"
            path.write_text("---\nname: mathmodel-skill\nbad: [unterminated\n---\n", encoding="utf-8")
            self.assertIsNone(doctor._frontmatter_name(path))


class PatchVersionRegressions(unittest.TestCase):
    def test_stale_section_patch_cannot_erase_newer_text(self):
        original = "## Model\nold\n## Results\nold result\n"
        newer = original.replace("old result", "teammate result")
        patch = f"MATHMODEL_SOURCE_SHA256: {extract_diff.source_hash(original)}\n<<< SECTION_PATCH section_0\n## Model\nnew\n>>>"
        with self.assertRaisesRegex(ValueError, "过期"):
            extract_diff.apply_section_patches(newer, patch)
        self.assertIn("new\n## Results\nold result", extract_diff.apply_section_patches(original, patch))

    def test_patch_without_source_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "源版本哈希"):
            extract_diff.apply_section_patches("## Model\na\n", "<<< SECTION_PATCH a\n## Model\nb\n>>>")
        with self.assertRaisesRegex(ValueError, "源版本哈希"):
            extract_diff.apply_unidiff("a\n", "--- a\n+++ a\n@@ -1 +1 @@\n-a\n+b\n")

    def test_fenced_headings_are_preserved_as_section_content(self):
        artifact = "## Model\n```python\n## Not a heading\n```\n~~~~text\n# Also not a heading\n~~~~\n## Results\ntext\n"
        self.assertEqual([x[0] for x in extract_diff.split_sections(artifact)], ["## Model", "## Results"])
        self.assertEqual(extract_diff.split_sections(artifact)[0][2], 6)

    def test_patch_delimiter_in_fenced_content_does_not_truncate_section(self):
        artifact = "## Model\nold\n"
        replacement = "## Model\n```text\n>>>\n```\nPreserve this tail."
        patch = f"MATHMODEL_SOURCE_SHA256: {extract_diff.source_hash(artifact)}\n<<< SECTION_PATCH s\n{replacement}\n>>>\n"
        self.assertEqual(extract_diff.apply_section_patches(artifact, patch), replacement + "\n")


class DisclosurePolicyRegressions(unittest.TestCase):
    def test_cumcm_process_explanation_does_not_require_raw_interactions(self):
        entry = {"tool": "Test assistant", "model": "Test", "version": "2026",
                 "use_stage": "Stage 5", "purpose": "解释求解器错误", "paper_sections": ["模型求解"],
                 "process_summary": "询问不可行状态的含义，再由团队检查约束。",
                 "human_review": "已复算预算约束并保留运行记录。"}
        entries = render_ai_usage.validate_entries([entry], "cumcm")
        report = render_ai_usage.render_cumcm_markdown(entries, {})
        self.assertIn(entry["process_summary"], report)
        self.assertIn("导出不代表已核验", report)
        with self.assertRaises(render_ai_usage.LedgerValidationError):
            render_ai_usage.validate_entries([entry], "mcm")

    def test_used_ai_declaration_is_before_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper"
            paper.mkdir()
            for filename in render_paper.SECTION_TO_FILE.values():
                (paper / filename).write_text("Example content\n", encoding="utf-8")
            (paper / render_paper.CUMCM_AI_FILENAME).write_text("本参赛队使用了 Test。", encoding="utf-8")
            tex, _ = render_paper.fill_template("cumcm", paper, root / "out", prefer_pandoc=False)
            text = tex.read_text(encoding="utf-8")
            self.assertLess(text.index(r"\input{sections/cumcm_no_ai_statement}"), text.index(r"\input{sections/8_references}"))
            self.assertIn("本参赛队使用了 Test", (root / "out/sections/cumcm_no_ai_statement.tex").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
