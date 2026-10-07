#!/usr/bin/env python3
"""Unit tests for scripts/render_ai_usage.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "render_ai_usage.py"
SPEC = importlib.util.spec_from_file_location("render_ai_usage", MODULE_PATH)
assert SPEC and SPEC.loader
render_ai_usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = render_ai_usage
SPEC.loader.exec_module(render_ai_usage)


class AIUsageReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.entry = {
            "tool": "OpenAI ChatGPT",
            "model": "GPT-5",
            "version": "21 July 2026 version",
            "used_at": "2026-07-21T14:30:00+08:00",
            "use_stage": "Stage 7 / model evaluation",
            "purpose": "Check whether the sensitivity discussion is understandable.",
            "paper_sections": ["Abstract", "Section 7"],
            "query": "Review this sentence exactly: x | y and ```nested```.",
            "output": "The sentence needs a defined baseline and one quantified result.",
            "human_review": "We recomputed the result, checked the cited source, and rewrote the sentence ourselves.",
            "adoption": "Only the suggestion to state the baseline was retained.",
            "evidence": ["state/ai/AI-001.txt"],
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_log(self, competition: str, entries: list[dict]) -> Path:
        path = self.root / "state" / "decision_log.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "competition": competition,
                    "problem_meta": {
                        "year": 2026,
                        "letter": "A",
                        "title": "A Test Problem",
                    },
                    "compliance": {"ai_usage": entries},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_mcm_report_preserves_complete_query_and_output(self) -> None:
        log = self.write_log("mcm", [self.entry])
        paper_workspace = self.root / "paper_workspace"
        support_dir = self.root / "support_materials"

        outputs = render_ai_usage.render_reports(log, paper_workspace, support_dir)

        self.assertEqual(outputs, [paper_workspace / "11_ai_use_report.md"])
        report = outputs[0].read_text(encoding="utf-8")
        self.assertFalse(report.startswith("#"))
        self.assertNotIn("# Report on Use of AI", report)
        self.assertIn(self.entry["query"], report)
        self.assertIn(self.entry["output"], report)
        self.assertIn("Human verification and revisions", report)
        # The payload contains a triple-backtick run; the outer fence must grow.
        self.assertIn("````text", report)

    def test_cumcm_markdown_and_pdf_are_generated(self) -> None:
        log = self.write_log("cumcm", [self.entry])
        paper_workspace = self.root / "paper_workspace"
        support_dir = self.root / "support_materials"
        paper_workspace.mkdir()
        (paper_workspace / "AI工具未使用声明.md").write_text(
            "stale", encoding="utf-8"
        )

        try:
            outputs = render_ai_usage.render_reports(
                log, paper_workspace, support_dir
            )
        except render_ai_usage.MissingDependency:
            self.skipTest("ReportLab is not installed in this test environment")

        self.assertEqual(
            outputs,
            [
                support_dir / "AI工具使用详情.md",
                support_dir / "AI工具使用详情.pdf",
                paper_workspace / "AI工具使用声明.md",
            ],
        )
        self.assertIn(
            "人工智能工具使用详情", outputs[0].read_text(encoding="utf-8")
        )
        self.assertTrue(outputs[1].read_bytes().startswith(b"%PDF"))
        self.assertGreater(outputs[1].stat().st_size, 1000)
        self.assertFalse((paper_workspace / "AI工具未使用声明.md").exists())

    def test_non_conversational_disclosure_does_not_require_query(self) -> None:
        entry = {
            "tool": "GitHub Copilot",
            "model": "Code completion service",
            "version": "21 July 2026 version",
            "use_stage": "Stage 5 / solver implementation",
            "purpose": "Code auto-completion for plotting utilities.",
            "paper_sections": "Appendix",
            "disclosure": "Auto-completions were used while preparing plotting code.",
            "human_review": "The team read, executed, and tested every retained line.",
        }
        log = self.write_log("mcm", [entry])

        output = render_ai_usage.render_reports(
            log, self.root / "paper_workspace", self.root / "support_materials"
        )[0]

        report = output.read_text(encoding="utf-8")
        self.assertIn("**Disclosure:**", report)
        self.assertIn(entry["disclosure"], report)

    def test_explicit_empty_ledger_generates_no_use_statement(self) -> None:
        log = self.write_log("mcm", [])

        output = render_ai_usage.render_reports(
            log, self.root / "paper_workspace", self.root / "support_materials"
        )[0]

        self.assertIn(
            "did not use generative AI", output.read_text(encoding="utf-8")
        )

    def test_cumcm_empty_ledger_generates_inline_statement_only(self) -> None:
        log = self.write_log("cumcm", [])
        paper_workspace = self.root / "paper_workspace"
        support_dir = self.root / "support_materials"
        support_dir.mkdir()
        (support_dir / "AI工具使用详情.md").write_text("stale", encoding="utf-8")
        (support_dir / "AI工具使用详情.pdf").write_bytes(b"stale")

        outputs = render_ai_usage.render_reports(log, paper_workspace, support_dir)

        self.assertEqual(outputs, [paper_workspace / "AI工具未使用声明.md"])
        self.assertEqual(
            outputs[0].read_text(encoding="utf-8"),
            "本参赛队未使用任何 AI 工具。\n",
        )
        self.assertFalse((support_dir / "AI工具使用详情.pdf").exists())
        self.assertFalse((support_dir / "AI工具使用详情.md").exists())

    def test_missing_ledger_is_not_silently_treated_as_no_use(self) -> None:
        log = self.root / "decision_log.json"
        log.write_text(json.dumps({"competition": "mcm"}), encoding="utf-8")

        with self.assertRaisesRegex(
            render_ai_usage.LedgerValidationError, "compliance.ai_usage"
        ):
            render_ai_usage.load_ledger(log)

    def test_query_and_output_must_be_recorded_together(self) -> None:
        broken = dict(self.entry)
        broken.pop("output")
        log = self.write_log("mcm", [broken])

        with self.assertRaisesRegex(
            render_ai_usage.LedgerValidationError, "必须同时填写"
        ):
            render_ai_usage.load_ledger(log)

    def test_use_stage_is_required(self) -> None:
        broken = dict(self.entry)
        broken.pop("use_stage")
        log = self.write_log("mcm", [broken])

        with self.assertRaisesRegex(
            render_ai_usage.LedgerValidationError, "use_stage"
        ):
            render_ai_usage.load_ledger(log)

    def test_interaction_and_disclosure_are_mutually_exclusive(self) -> None:
        broken = dict(self.entry)
        broken["disclosure"] = "A second, ambiguous disclosure path."
        log = self.write_log("mcm", [broken])

        with self.assertRaisesRegex(
            render_ai_usage.LedgerValidationError, "不能同时填写"
        ):
            render_ai_usage.load_ledger(log)

    def test_missing_reportlab_error_has_install_command(self) -> None:
        log = self.write_log("cumcm", [self.entry])
        _, entries = render_ai_usage.load_ledger(log)
        output = self.root / "AI工具使用详情.pdf"

        with mock.patch.object(
            render_ai_usage,
            "_load_reportlab",
            side_effect=render_ai_usage.MissingDependency(
                render_ai_usage.REPORTLAB_ERROR
            ),
        ):
            with self.assertRaisesRegex(
                render_ai_usage.MissingDependency, "pip install reportlab"
            ):
                render_ai_usage.render_cumcm_pdf(entries, {}, output)


if __name__ == "__main__":
    unittest.main()
