#!/usr/bin/env python3
"""Regression tests for fail-closed patching and Stage 5 aggregation."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mathmodel_safety_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


extract_diff = load_script("extract_diff")
score_artifact = load_script("score_artifact")


class SectionPatchSafetyTests(unittest.TestCase):
    def test_long_section_is_never_silently_truncated(self) -> None:
        sentinel = "TAIL_SENTINEL_MUST_SURVIVE"
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "paper.md"
            artifact.write_text(
                "## Model\n\n" + ("evidence line\n" * 180) + sentinel + "\n",
                encoding="utf-8",
            )
            prompt = extract_diff.build_section_patch_prompt(
                str(artifact),
                {"issues": [{
                    "where": "Model",
                    "fix": "Clarify one sentence.",
                    "severity": "medium",
                    "anti_pattern_id": None,
                }]},
            )

        self.assertIn(sentinel, prompt)
        self.assertNotIn("<truncated>", prompt)

    def test_oversized_section_fails_instead_of_truncating(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "paper.md"
            artifact.write_text(
                "## Model\n" + ("x" * (extract_diff.MAX_SECTION_PATCH_CHARS + 1)),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不会截断"):
                extract_diff.build_section_patch_prompt(
                    str(artifact),
                    {"issues": [{"where": "Model", "fix": "Clarify."}]},
                )

    def test_multiple_issues_for_one_section_share_one_patch_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "paper.md"
            artifact.write_text("## Model\n\nOriginal.\n", encoding="utf-8")
            prompt = extract_diff.build_section_patch_prompt(
                str(artifact),
                {"issues": [
                    {"where": "Model", "fix": "Fix A."},
                    {"where": "Model", "fix": "Fix B."},
                ]},
            )

        self.assertEqual(prompt.count('"patch_id": "section_0"'), 1)
        self.assertEqual(prompt.count('"section_heading": "## Model"'), 1)
        self.assertIn("issue_0", prompt)
        self.assertIn("issue_1", prompt)


class UnifiedDiffSafetyTests(unittest.TestCase):
    def test_multiple_hunks_use_original_coordinates(self) -> None:
        artifact = "alpha\none\ntwo\nthree\nmiddle\nfour\nfive\nsix\nomega\n"
        patch = """--- paper.md
+++ paper.md
@@ -2,3 +2,4 @@
 one
-two
+TWO
+two-and-half
 three
@@ -6,3 +7,2 @@
 four
-five
 six
"""
        patch = f"MATHMODEL_SOURCE_SHA256: {extract_diff.source_hash(artifact)}\n" + patch
        result = extract_diff.apply_unidiff(artifact, patch)
        self.assertEqual(
            result,
            "alpha\none\nTWO\ntwo-and-half\nthree\nmiddle\nfour\nsix\nomega\n",
        )

    def test_stale_context_is_rejected(self) -> None:
        artifact = "alpha\none\ntwo\nthree\n"
        patch = """--- paper.md
+++ paper.md
@@ -1,3 +1,3 @@
 alpha
-WRONG
+ONE
 two
"""
        patch = f"MATHMODEL_SOURCE_SHA256: {extract_diff.source_hash(artifact)}\n" + patch
        with self.assertRaisesRegex(ValueError, "原文校验失败"):
            extract_diff.apply_unidiff(artifact, patch)


class StageFiveAggregationSafetyTests(unittest.TestCase):
    @staticmethod
    def issue(severity: str) -> dict:
        return {
            "severity": severity,
            "where": "Q2 validation",
            "fix": "Repair and rerun the validation.",
            "anti_pattern_id": None,
        }

    def test_high_severity_issue_blocks_even_when_scores_pass(self) -> None:
        result = score_artifact.compute_stage5_verdict([
            {"qi": "Q1", "min": 8, "mean": 8.4, "issues": []},
            {
                "qi": "Q2",
                "min": 8,
                "mean": 8.6,
                "issues": [self.issue("high")],
            },
        ])
        self.assertEqual(result["verdict"], "block")
        self.assertEqual(result["block_qis"], ["Q2"])
        self.assertEqual(result["qi_status"]["Q2"], "block")

    def test_all_failed_qis_require_full_refine(self) -> None:
        result = score_artifact.compute_stage5_verdict([
            {"qi": "Q1", "min": 5, "mean": 6.0, "issues": []},
            {"qi": "Q2", "min": 6, "mean": 6.8, "issues": []},
        ])
        self.assertEqual(result["verdict"], "refine")
        self.assertEqual(result["refine_qis"], ["Q1", "Q2"])

    def test_missing_issues_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能丢弃子问问题"):
            score_artifact.compute_stage5_verdict([
                {"qi": "Q1", "min": 8, "mean": 8.4},
            ])


if __name__ == "__main__":
    unittest.main()
