#!/usr/bin/env python3
"""Regression tests for fail-closed final-paper front matter rendering."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_render_paper():
    path = ROOT / "scripts" / "render_paper.py"
    spec = importlib.util.spec_from_file_location("render_guard_render_paper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render_paper = load_render_paper()


def has_cumcm_latex_toolchain() -> bool:
    """Only run integration tests when both XeLaTeX and ctexart are available."""
    if not shutil.which("xelatex") or not shutil.which("kpsewhich"):
        return False
    result = subprocess.run(
        ["kpsewhich", "ctexart.cls"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def write_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / render_paper.CUMCM_NO_AI_FILENAME).write_text("本参赛队未使用任何 AI 工具。\n", encoding="utf-8")
    for section, filename in render_paper.SECTION_TO_FILE.items():
        content = f"Rendered {section}.\n" if section == "abstract" else (
            f"# {section}\n\nRendered {section}.\n"
        )
        (path / filename).write_text(content, encoding="utf-8")


def write_compilable_cumcm_workspace(
    path: Path,
    *,
    abstract_extra: str = "",
    body_extra: str = "",
) -> None:
    """Create small valid fragments for an optional real XeLaTeX smoke test."""
    path.mkdir(parents=True, exist_ok=True)
    (path / render_paper.CUMCM_NO_AI_FILENAME).write_text("本参赛队未使用任何 AI 工具。\n", encoding="utf-8")
    content = {
        "abstract": "本文建立一个可复核的测试模型。" + abstract_extra,
        "1_problem_restate": "# 问题重述\n\n测试问题。",
        "2_problem_analysis": "# 问题分析\n\n分析测试。",
        "3_assumptions": "# 模型假设\n\n假设成立。",
        "4_notation": "# 符号说明\n\n符号定义。",
        "5_models": "# 模型建立\n\n模型结果。" + body_extra,
        "6_sensitivity": "# 灵敏度分析\n\n结果稳定。",
        "7_evaluation": "# 模型评价\n\n边界明确。",
        "8_references": "# 参考文献\n\n测试参考文献。",
        "appendix_code": "# 附录\n\n本测试不含支撑代码。",
    }
    for section, filename in render_paper.SECTION_TO_FILE.items():
        (path / filename).write_text(content[section] + "\n", encoding="utf-8")


class RenderMetadataTests(unittest.TestCase):
    def test_cumcm_state_metadata_fills_title_and_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            write_workspace(workspace)
            metadata = render_paper.resolve_paper_metadata({
                "competition": "cumcm",
                "paper_metadata": {
                    "title": "韧性评估 & 优化_模型",
                    "keywords": ["韧性", "风险 & 稳健性", "多目标优化"],
                },
            })

            main_path, engine = render_paper.fill_template(
                "cumcm",
                workspace,
                root / "out",
                prefer_pandoc=False,
                paper_metadata=metadata,
                allow_placeholders=False,
            )
            text = main_path.read_text(encoding="utf-8")

            self.assertEqual(engine, "xelatex")
            self.assertIn(r"韧性评估 \& 优化\_模型", text)
            self.assertIn(r"韧性；风险 \& 稳健性；多目标优化", text)
            self.assertNotIn("MATHMODEL_CUMCM_", text)
            self.assertEqual(
                render_paper.find_unresolved_front_matter_placeholders(text), []
            )

    def test_mcm_state_metadata_fills_every_token_and_escapes_latex(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            write_workspace(workspace)
            state = {
                "competition": "mcm",
                "paper_metadata": {
                    "mcm_control_number": "2400123",
                    "problem": "A",
                    "title": "Signals & Systems_2027",
                    "keywords": ["keyword extraction", "risk & robustness"],
                },
            }
            metadata = render_paper.resolve_paper_metadata(state)

            main_path, _ = render_paper.fill_template(
                "mcm",
                workspace,
                root / "out",
                prefer_pandoc=False,
                paper_metadata=metadata,
                allow_placeholders=False,
            )
            text = main_path.read_text(encoding="utf-8")

            self.assertEqual(text.count("2400123"), 2)
            self.assertIn(r"Signals \& Systems\_2027", text)
            self.assertIn(r"keyword extraction, risk \& robustness", text)
            self.assertEqual(
                render_paper.find_unresolved_front_matter_placeholders(text), []
            )

    def test_diangong_cli_values_override_state_and_fill_repeated_title(self) -> None:
        state = {
            "paper_metadata": {
                "diangong_registration_number": "XXXX",
                "problem": "X",
                "title": "赛题论文题目",
                "keywords": ["关键词1"],
            }
        }
        metadata = render_paper.resolve_paper_metadata(
            state,
            {
                "diangong_registration_number": "DG-2027-0188",
                "problem": "B",
                "title": "配电网韧性评估与优化",
                "keywords": "配电网；韧性；多目标优化",
            },
        )
        template = (
            ROOT / "templates" / "latex" / "diangong" / "main.tex"
        ).read_text(encoding="utf-8")
        rendered = render_paper.fill_paper_metadata(
            template, "diangong", metadata, allow_placeholders=False
        )

        self.assertIn("DG-2027-0188", rendered)
        self.assertEqual(rendered.count("配电网韧性评估与优化"), 2)
        self.assertIn("配电网；韧性；多目标优化", rendered)
        self.assertEqual(
            render_paper.find_unresolved_front_matter_placeholders(rendered), []
        )

    def test_missing_or_legacy_placeholder_values_fail_closed(self) -> None:
        bad_cases = (
            ({}, "缺少 MCM control number"),
            ({
                "mcm_control_number": "XXXX",
                "problem": "X",
                "title": "TITLE OF YOUR PAPER",
                "keywords": ["keyword1", "keyword2"],
            }, "仍是占位符"),
        )
        for metadata, message in bad_cases:
            with self.subTest(metadata=metadata):
                with self.assertRaisesRegex(ValueError, message):
                    render_paper.prepare_paper_metadata(
                        "mcm", metadata, allow_placeholders=False
                    )

    def test_preview_tokens_cannot_reach_compile_process(self) -> None:
        template = (
            ROOT / "templates" / "latex" / "mcm" / "main.tex"
        ).read_text(encoding="utf-8")
        preview = render_paper.fill_paper_metadata(
            template, "mcm", {}, allow_placeholders=True
        )
        self.assertIn("MATHMODEL_MCM_CONTROL_NUMBER", preview)

        with tempfile.TemporaryDirectory() as temp:
            tex_path = Path(temp) / "main.tex"
            tex_path.write_text(preview, encoding="utf-8")
            with mock.patch.object(render_paper.subprocess, "run") as run:
                self.assertFalse(render_paper.compile_pdf(tex_path, "pdflatex"))
                run.assert_not_called()

    def test_cumcm_formal_render_requires_title_and_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            write_workspace(workspace)

            with self.assertRaisesRegex(ValueError, "缺少 title/论文题目"):
                render_paper.fill_template(
                    "cumcm",
                    workspace,
                    root / "out",
                    prefer_pandoc=False,
                    paper_metadata={},
                    allow_placeholders=False,
                )

    def test_cumcm_structural_preview_allows_explicit_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            write_workspace(workspace)
            main_path, engine = render_paper.fill_template(
                "cumcm",
                workspace,
                root / "out",
                prefer_pandoc=False,
                allow_placeholders=True,
            )
            self.assertEqual(engine, "xelatex")
            self.assertTrue(main_path.is_file())
            self.assertIn(
                "MATHMODEL_CUMCM_TITLE", main_path.read_text(encoding="utf-8")
            )

    def test_cumcm_template_is_anonymous_rules_aligned_and_guarded(self) -> None:
        legacy_template_name = "cumcm" + "thesis"
        legacy_template_dir = (
            ROOT / "templates" / "latex" / "cumcm" / legacy_template_name
        )
        template = (
            ROOT / "templates" / "latex" / "cumcm" / "main.tex"
        ).read_text(encoding="utf-8")
        markers = render_paper.SECTION_MARKER_RE.findall(template)

        self.assertFalse(legacy_template_dir.exists())
        self.assertIn(r"\documentclass[UTF8,12pt,a4paper,fontset=fandol]{ctexart}", template)
        self.assertIn(r"\usepackage[margin=2.5cm]{geometry}", template)
        self.assertNotIn(r"\tableofcontents", template)
        self.assertNotIn(r"\author", template)
        self.assertNotIn(legacy_template_name, template.lower())
        self.assertEqual(
            set(markers),
            set(render_paper.SECTION_TO_FILE) | {"cumcm_no_ai_statement"},
        )
        self.assertEqual(len(markers), len(set(markers)))
        self.assertIn("CUMCM abstract must fit on the first page", template)
        self.assertIn("CUMCM body exceeds 30 pages", template)
        self.assertIn(r"\ifnum\value{mathmodelbodypages}>30", template)
        self.assertIn("MATHMODEL:OPTIONAL cumcm_no_ai_statement BEGIN", template)


@unittest.skipUnless(
    has_cumcm_latex_toolchain(),
    "XeLaTeX with ctexart.cls is not installed",
)
class CumcmLatexGuardTests(unittest.TestCase):
    metadata = {
        "title": "测试论文标题",
        "keywords": ["测试", "稳健性", "复核"],
    }

    def render_and_compile(
        self,
        root: Path,
        *,
        abstract_extra: str = "",
        body_extra: str = "",
    ) -> bool:
        workspace = root / "paper_workspace"
        write_compilable_cumcm_workspace(
            workspace,
            abstract_extra=abstract_extra,
            body_extra=body_extra,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            main_path, _ = render_paper.fill_template(
                "cumcm",
                workspace,
                root / "out",
                prefer_pandoc=False,
                paper_metadata=self.metadata,
                allow_placeholders=False,
            )
            return render_paper.compile_pdf(main_path, "xelatex", runs=1)

    def test_original_template_compiles_a_short_electronic_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(self.render_and_compile(Path(temp)))

    def test_abstract_overflow_fails_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(
                self.render_and_compile(
                    Path(temp), abstract_extra="\n\n\\newpage\n\n第二页摘要。"
                )
            )

    def test_body_over_thirty_pages_fails_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            overflow = "".join("\n\\newpage\n正文测试。\n" for _ in range(31))
            self.assertFalse(self.render_and_compile(Path(temp), body_extra=overflow))


class RenderCliTests(unittest.TestCase):
    def run_cli(self, workspace: Path, output: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "render_paper.py"),
                "--competition",
                "mcm",
                "--workspace",
                str(workspace),
                "--output-dir",
                str(output),
                "--no-pandoc",
                "--no-compile",
                *extra,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_no_compile_is_still_strict_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            output = root / "out"
            write_workspace(workspace)

            result = self.run_cli(workspace, output)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("正式渲染已停止", result.stdout)
            self.assertFalse(output.exists())

    def test_explicit_cli_metadata_renders_a_clean_structural_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            output = root / "out"
            write_workspace(workspace)

            result = self.run_cli(
                workspace,
                output,
                "--control-number",
                "2500999",
                "--problem",
                "C",
                "--title",
                "A Robust Network Model",
                "--keywords",
                "network;robustness;simulation",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = (output / "main.tex").read_text(encoding="utf-8")
            self.assertIn("2500999", text)
            self.assertNotIn("MATHMODEL_MCM_", text)

    def test_placeholder_preview_requires_explicit_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            output = root / "out"
            write_workspace(workspace)

            result = self.run_cli(workspace, output, "--allow-placeholders")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("模板预览保留显式", result.stdout)
            self.assertIn(
                "MATHMODEL_MCM_CONTROL_NUMBER",
                (output / "main.tex").read_text(encoding="utf-8"),
            )

    def test_default_state_is_bound_to_workspace_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "paper_workspace"
            write_workspace(workspace)
            state_path = root / "state" / "decision_log.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "competition": "mcm",
                        "paper_metadata": {
                            "mcm_control_number": "2600777",
                            "problem": "D",
                            "title": "Workspace-Bound State",
                            "keywords": ["policy", "simulation"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = root / "out"

            result = self.run_cli(workspace, output)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "2600777", (output / "main.tex").read_text(encoding="utf-8")
            )


class DecisionLogSchemaTests(unittest.TestCase):
    def test_dynamic_counts_and_unobservable_token_usage_default_to_null(self) -> None:
        state = json.loads(
            (ROOT / "templates" / "shared" / "decision_log.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsNone(state["budget"]["tokens_used"])
        self.assertIsNone(state["budget"]["tokens_cap"])
        self.assertIsNone(state["stages"]["9"]["anti_patterns_check"]["total"])
        self.assertIn("paper_metadata", state)


if __name__ == "__main__":
    unittest.main()
