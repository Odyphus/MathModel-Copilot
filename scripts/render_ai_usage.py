#!/usr/bin/env python3
"""Render competition-ready AI usage disclosures from ``decision_log.json``.

The source ledger is ``decision_log.compliance.ai_usage``.  Its deliberately
small schema is:

    {
      "compliance": {
        "ai_usage": [
          {
            "tool": "OpenAI ChatGPT",
            "model": "GPT-5",
            "version": "21 July 2026 version",
            "used_at": "2026-07-21T14:30:00+08:00",  # optional
            "use_stage": "Stage 7 / model evaluation",
            "purpose": "Language polishing",
            "paper_sections": ["Abstract", "Section 7"],
            "query": "Complete, exact input",       # see alternative below
            "output": "Complete, exact output",
            "human_review": "How the team checked and corrected it",
            "adoption": "What was ultimately retained",  # optional
            "evidence": ["state/ai/AI-001.txt"]            # optional
          }
        ]
      }
    }

``tool``, ``model``, ``version``, ``use_stage``, ``purpose``,
``paper_sections`` and ``human_review`` are required. A conversational or
generative entry must also
contain both ``query`` and ``output``.  Translation, code completion, or other
non-conversational use may instead contain one plain-language ``disclosure``.
CUMCM 2026 also accepts ``process_summary`` with a process explanation and
optional typical interactions; complete raw interactions are not mandatory.
Ledger order is retained as chronological order.  An explicit empty list means
that no AI-assisted tool was used; a missing path is treated as an error.

Outputs are placed where the paper renderer expects them:
  * cumcm with AI use: ``support_materials/AI工具使用详情.{md,pdf}`` and
    ``paper_workspace/AI工具使用声明.md`` (before references)
  * cumcm without AI use: ``paper_workspace/AI工具未使用声明.md``
  * mcm: ``paper_workspace/11_ai_use_report.md``

ReportLab is imported only for the CUMCM PDF, so the MCM path has no external
Python dependency.  Use ``--markdown-only`` to inspect CUMCM Markdown without
creating the PDF.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from copilot_store import Store

CUMCM_MARKDOWN_FILENAME = "AI工具使用详情.md"
CUMCM_PDF_FILENAME = "AI工具使用详情.pdf"
CUMCM_NO_USE_FILENAME = "AI工具未使用声明.md"
CUMCM_USE_FILENAME = "AI工具使用声明.md"
MCM_MARKDOWN_FILENAME = "11_ai_use_report.md"

REPORTLAB_ERROR = (
    "生成 CUMCM《AI工具使用详情.pdf》需要 ReportLab。"
    "请先运行：python -m pip install reportlab"
)


class LedgerValidationError(ValueError):
    """The decision log does not contain a usable, explicit AI usage ledger."""


class MissingDependency(RuntimeError):
    """An optional dependency required by the selected output is unavailable."""


@dataclass(frozen=True)
class AIUsageEntry:
    tool: str
    model: str
    version: str
    purpose: str
    use_stage: str
    paper_sections: Sequence[str]
    human_review: str
    used_at: str = ""
    query: str = ""
    output: str = ""
    disclosure: str = ""
    process_summary: str = ""
    adoption: str = ""
    evidence: Sequence[str] = ()

    @property
    def display_name(self) -> str:
        return f"{self.tool} ({self.model})"


def resolve_decision_log_path(cli_arg: Optional[str] = None) -> Path:
    """Resolve CLI > MATHMODEL_STATE_DIR > CUMCM_STATE_DIR > cwd/state."""
    if cli_arg:
        return Path(cli_arg)
    state_dir = os.environ.get("MATHMODEL_STATE_DIR") or os.environ.get(
        "CUMCM_STATE_DIR"
    )
    if state_dir:
        return Path(state_dir) / "decision_log.json"
    return Path.cwd() / "state" / "decision_log.json"


def _require_nonempty_string(raw: Dict[str, Any], key: str, entry_no: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LedgerValidationError(
            f"compliance.ai_usage[{entry_no}] 的 {key!r} 必须是非空字符串"
        )
    return value.strip()


def _optional_string(raw: Dict[str, Any], key: str, entry_no: int) -> str:
    value = raw.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LedgerValidationError(
            f"compliance.ai_usage[{entry_no}] 的 {key!r} 必须是字符串"
        )
    return value.strip()


def _string_list(
    raw: Dict[str, Any], key: str, entry_no: int, *, required: bool
) -> Sequence[str]:
    value = raw.get(key)
    if isinstance(value, str):
        items = [value.strip()] if value.strip() else []
    elif isinstance(value, list):
        items = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise LedgerValidationError(
                    f"compliance.ai_usage[{entry_no}] 的 {key!r} 只能包含非空字符串"
                )
            items.append(item.strip())
    elif value is None and not required:
        items = []
    else:
        expected = "非空字符串或字符串数组" if required else "字符串或字符串数组"
        raise LedgerValidationError(
            f"compliance.ai_usage[{entry_no}] 的 {key!r} 必须是{expected}"
        )
    if required and not items:
        raise LedgerValidationError(
            f"compliance.ai_usage[{entry_no}] 的 {key!r} 不能为空"
        )
    return tuple(items)


def validate_entries(raw_entries: Any, competition: str = "mcm") -> List[AIUsageEntry]:
    """Validate and normalize the raw ``compliance.ai_usage`` list."""
    if not isinstance(raw_entries, list):
        raise LedgerValidationError("decision_log.compliance.ai_usage 必须是数组")

    entries: List[AIUsageEntry] = []
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise LedgerValidationError(
                f"compliance.ai_usage[{index}] 必须是 JSON 对象"
            )

        query = _optional_string(raw, "query", index)
        output = _optional_string(raw, "output", index)
        disclosure = _optional_string(raw, "disclosure", index)
        process_summary = _optional_string(raw, "process_summary", index)
        if process_summary and competition != "cumcm":
            raise LedgerValidationError("process_summary 替代原始交互仅适用于 CUMCM；其他赛事按其规则记录")
        if bool(query) != bool(output):
            raise LedgerValidationError(
                f"compliance.ai_usage[{index}] 的 'query' 与 'output' 必须同时填写"
            )
        if disclosure and query:
            raise LedgerValidationError(
                f"compliance.ai_usage[{index}] 不能同时填写 'query'/'output' 与 'disclosure'"
            )
        if not disclosure and not process_summary and not (query and output):
            raise LedgerValidationError(
                f"compliance.ai_usage[{index}] 必须填写完整 'query' + 'output'，"
                "或为非对话式工具填写 'disclosure'；CUMCM 可填写 'process_summary' 过程说明"
            )

        entries.append(
            AIUsageEntry(
                tool=_require_nonempty_string(raw, "tool", index),
                model=_require_nonempty_string(raw, "model", index),
                version=_require_nonempty_string(raw, "version", index),
                used_at=_optional_string(raw, "used_at", index),
                use_stage=_require_nonempty_string(raw, "use_stage", index),
                purpose=_require_nonempty_string(raw, "purpose", index),
                paper_sections=_string_list(
                    raw, "paper_sections", index, required=True
                ),
                query=query,
                output=output,
                disclosure=disclosure,
                process_summary=process_summary,
                human_review=_require_nonempty_string(raw, "human_review", index),
                adoption=_optional_string(raw, "adoption", index),
                evidence=_string_list(raw, "evidence", index, required=False),
            )
        )
    return entries


def load_ledger(path: Path, competition: str = None) -> tuple[Dict[str, Any], List[AIUsageEntry]]:
    """Load a decision log and require an explicit compliance ledger path."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LedgerValidationError(f"找不到 decision log：{path}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerValidationError(
            f"decision log 不是有效 JSON：{path}（{exc}）"
        ) from exc

    if not isinstance(data, dict):
        raise LedgerValidationError("decision log 根节点必须是 JSON 对象")
    if "copilot" in data:
        try:
            data = Store(path).read()
        except (OSError, ValueError) as exc:
            raise LedgerValidationError(str(exc)) from exc
    compliance = data.get("compliance")
    if not isinstance(compliance, dict) or "ai_usage" not in compliance:
        raise LedgerValidationError(
            "decision log 缺少 compliance.ai_usage；"
            "请明确记录 [] 表示未使用 AI 工具，不能据缺失字段推断未使用"
        )
    return data, validate_entries(compliance["ai_usage"], competition or data.get("competition", "mcm"))


def resolve_competition(cli_arg: Optional[str], decision_log: Dict[str, Any]) -> str:
    """Resolve CLI > MATHMODEL_COMPETITION > decision log."""
    competition = (
        cli_arg
        or os.environ.get("MATHMODEL_COMPETITION")
        or decision_log.get("competition")
    )
    if competition not in {"cumcm", "mcm"}:
        raise LedgerValidationError(
            "AI 使用报告目前支持 competition='cumcm' 或 'mcm'；"
            f"当前值为 {competition!r}"
        )
    return str(competition)


def _escape_table_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _fenced_block(text: str, language: str = "text") -> str:
    """Return a Markdown fence longer than any backtick run in the payload."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _problem_context(decision_log: Dict[str, Any], chinese: bool) -> str:
    meta = decision_log.get("problem_meta")
    if not isinstance(meta, dict):
        return ""
    parts = [str(meta.get(key)).strip() for key in ("year", "letter", "title") if meta.get(key)]
    if not parts:
        return ""
    label = "赛题" if chinese else "Problem"
    return f"**{label}:** {' · '.join(parts)}\n\n"


def render_cumcm_markdown(
    entries: Sequence[AIUsageEntry], decision_log: Dict[str, Any]
) -> str:
    if not entries:
        raise LedgerValidationError(
            "CUMCM 空台账应生成参考文献前的未使用声明，而不是 AI 工具使用详情"
        )
    lines = ["# 人工智能工具使用详情", ""]
    context = _problem_context(decision_log, True)
    if context:
        lines.extend([context.rstrip(), ""])
    lines.extend(
        [
            "本表依据台账导出 AI 工具、用途、使用环节、过程说明或典型交互及人工核验记录。导出不代表已核验，团队成员对最终提交内容承担全部责任。",
            "",
            "| 序号 | 工具与模型 | 版本 | 使用环节与目的 | 涉及章节 |",
            "|---:|---|---|---|---|",
        ]
    )
    for index, entry in enumerate(entries, 1):
        lines.append(
            "| {index} | {tool} | {version} | {purpose} | {sections} |".format(
                index=index,
                tool=_escape_table_cell(entry.display_name),
                version=_escape_table_cell(entry.version),
                purpose=_escape_table_cell(f"{entry.use_stage}：{entry.purpose}"),
                sections=_escape_table_cell("；".join(entry.paper_sections)),
            )
        )

    for index, entry in enumerate(entries, 1):
        lines.extend(
            [
                "",
                f"## {index}. {entry.display_name}",
                "",
                f"- **版本：** {entry.version}",
                f"- **使用时间：** {entry.used_at or '未单独记录'}",
                f"- **使用环节：** {entry.use_stage}",
                f"- **使用目的：** {entry.purpose}",
                f"- **涉及章节：** {'；'.join(entry.paper_sections)}",
                "",
            ]
        )
        if entry.process_summary:
            lines.extend(["### 使用过程说明", "", entry.process_summary, ""])
        if entry.query and entry.output:
            lines.extend(
                [
                    "### 记录的输入 / 提示词",
                    "",
                    _fenced_block(entry.query),
                    "",
                    "### 记录的输出",
                    "",
                    _fenced_block(entry.output),
                    "",
                ]
            )
        elif entry.disclosure:
            lines.extend(["### 使用说明", "", entry.disclosure, ""])
        lines.extend(["### 人工核验与修订", "", entry.human_review, ""])
        if entry.adoption:
            lines.extend(["### 最终采用方式", "", entry.adoption, ""])
        if entry.evidence:
            lines.extend(
                ["### 可追溯记录", "", "；".join(f"`{p}`" for p in entry.evidence), ""]
            )
    return "\n".join(lines).rstrip() + "\n"


def render_cumcm_no_use_statement(*, official=False) -> str:
    """Keep legacy output stable; current rules-bound delivery opts in explicitly."""
    if official:
        from migrated.cumcm_ai_declaration import AI_UNUSED_DECLARATION
        return AI_UNUSED_DECLARATION + "\n"
    return "本参赛队未使用任何 AI 工具。\n"


def render_cumcm_use_statement(entries: Sequence[AIUsageEntry], *, official=False) -> str:
    tools = "；".join(dict.fromkeys(f"{entry.tool}（{entry.model}，{entry.version}）" for entry in entries))
    purposes = "；".join(dict.fromkeys(entry.purpose for entry in entries))
    if official:
        from migrated.cumcm_ai_declaration import AI_USED_DECLARATION_PREFIX, AI_USED_DECLARATION_SUFFIX
        if not entries or not purposes.strip():
            raise ValueError("Official used-AI declaration requires actual ledger purposes")
        return AI_USED_DECLARATION_PREFIX + purposes + AI_USED_DECLARATION_SUFFIX + "\n"
    return f"本参赛队使用了以下 AI 工具：{tools}。使用目的：{purposes}。使用过程及人工核验记录见支撑材料《AI工具使用详情》。\n"


def render_mcm_markdown(
    entries: Sequence[AIUsageEntry], decision_log: Dict[str, Any]
) -> str:
    # The MCM LaTeX template supplies the Report on Use of AI heading.
    lines: List[str] = []
    context = _problem_context(decision_log, False)
    if context:
        lines.append(context.rstrip())
        lines.append("")
    if not entries:
        lines.extend(
            [
                "The team did not use generative AI, AI-assisted translation, code completion, or other AI-assisted tools in preparing this submission.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "The entries below record AI use and the team's reported human review. Exporting this report does not itself verify the material. The team remains responsible for the submitted work.",
            "",
        ]
    )
    for index, entry in enumerate(entries, 1):
        lines.extend(
            [
                f"## {index}. {entry.tool} ({entry.version}, {entry.model})",
                "",
                f"**Purpose:** {entry.purpose}",
                "",
                f"**Workflow stage:** {entry.use_stage}",
                "",
                f"**Sections affected:** {', '.join(entry.paper_sections)}",
                "",
            ]
        )
        if entry.used_at:
            lines.extend([f"**Date/time used:** {entry.used_at}", ""])
        if entry.query and entry.output:
            lines.extend(
                [
                    "**Query:**",
                    "",
                    _fenced_block(entry.query),
                    "",
                    "**Output:**",
                    "",
                    _fenced_block(entry.output),
                    "",
                ]
            )
        else:
            lines.extend(["**Disclosure:**", "", entry.disclosure, ""])
        lines.extend(["**Human verification and revisions:**", "", entry.human_review, ""])
        if entry.adoption:
            lines.extend(["**Material incorporated:**", "", entry.adoption, ""])
    return "\n".join(lines).rstrip() + "\n"


def _load_reportlab() -> Dict[str, Any]:
    """Import ReportLab lazily and return the components used by the renderer."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("reportlab"):
            raise
        raise MissingDependency(REPORTLAB_ERROR) from exc
    return locals()


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _pdf_safe_text(text: str) -> str:
    clean = _CONTROL_CHAR_RE.sub("", text)
    return html.escape(clean).replace("\n", "<br/>")


def render_cumcm_pdf(
    entries: Sequence[AIUsageEntry], decision_log: Dict[str, Any], output_path: Path
) -> Path:
    """Render an A4 Chinese disclosure PDF with embedded CID font support."""
    if not entries:
        raise LedgerValidationError(
            "CUMCM 未使用 AI 时需在参考文献前声明，不应生成使用详情 PDF"
        )
    rl = _load_reportlab()
    colors = rl["colors"]
    A4 = rl["A4"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    pdfmetrics = rl["pdfmetrics"]
    UnicodeCIDFont = rl["UnicodeCIDFont"]
    PageBreak = rl["PageBreak"]
    Paragraph = rl["Paragraph"]
    SimpleDocTemplate = rl["SimpleDocTemplate"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    TA_CENTER = rl["TA_CENTER"]
    TA_LEFT = rl["TA_LEFT"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    pdfmetrics.registerFontFamily(
        font_name,
        normal=font_name,
        bold=font_name,
        italic=font_name,
        boldItalic=font_name,
    )

    base = ParagraphStyle(
        "ChineseBody",
        fontName=font_name,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#263247"),
        alignment=TA_LEFT,
        wordWrap="CJK",
        splitLongWords=True,
        spaceAfter=4,
    )
    title = ParagraphStyle(
        "ChineseTitle",
        parent=base,
        fontSize=19,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#102A43"),
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "ChineseH2",
        parent=base,
        fontSize=13,
        leading=19,
        textColor=colors.HexColor("#0B7285"),
        spaceBefore=9,
        spaceAfter=6,
        keepWithNext=True,
    )
    label = ParagraphStyle(
        "ChineseLabel",
        parent=base,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#334E68"),
        spaceBefore=5,
        keepWithNext=True,
    )
    payload = ParagraphStyle(
        "ChinesePayload",
        parent=base,
        fontSize=9,
        leading=13,
        leftIndent=5 * mm,
        rightIndent=2 * mm,
        borderColor=colors.HexColor("#D9E2EC"),
        borderWidth=0.5,
        borderPadding=5,
        backColor=colors.HexColor("#F7F9FC"),
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "ChineseSmall",
        parent=base,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#52606D"),
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="人工智能工具使用详情",
        author="参赛团队",
    )

    def paragraph(text: str, style: Any = base) -> Any:
        return Paragraph(_pdf_safe_text(text), style)

    story: List[Any] = [paragraph("人工智能工具使用详情", title)]
    meta = decision_log.get("problem_meta")
    if isinstance(meta, dict):
        context_parts = [
            str(meta.get(key)).strip()
            for key in ("year", "letter", "title")
            if meta.get(key)
        ]
        if context_parts:
            story.extend(
                [paragraph("赛题：" + " · ".join(context_parts), small), Spacer(1, 3 * mm)]
            )

    story.extend(
        [
            paragraph(
                "本报告按实际使用顺序记录 AI 工具、用途、使用环节、过程说明或典型交互及人工核验记录。导出不代表已核验。"
                "团队成员对最终提交内容承担全部责任。"
            ),
            Spacer(1, 3 * mm),
        ]
    )
    if entries:
        header_style = ParagraphStyle(
            "SummaryHeader",
            parent=small,
            alignment=TA_CENTER,
            textColor=colors.white,
        )
        table_data: List[List[Any]] = [
            [
                paragraph("序号", header_style),
                paragraph("工具与模型", header_style),
                paragraph("版本", header_style),
                paragraph("使用环节与目的", header_style),
                paragraph("涉及章节", header_style),
            ]
        ]
        for index, entry in enumerate(entries, 1):
            table_data.append(
                [
                    paragraph(str(index), small),
                    paragraph(entry.display_name, small),
                    paragraph(entry.version, small),
                    paragraph(f"{entry.use_stage}：{entry.purpose}", small),
                    paragraph("；".join(entry.paper_sections), small),
                ]
            )
        summary = Table(
            table_data,
            colWidths=[10 * mm, 37 * mm, 30 * mm, 61 * mm, 38 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        summary.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B7285")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BCCCDC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ]
            )
        )
        story.extend([summary, PageBreak()])

        for index, entry in enumerate(entries, 1):
            story.extend(
                [
                    paragraph(f"{index}. {entry.display_name}", h2),
                    paragraph(f"版本：{entry.version}", base),
                    paragraph(f"使用时间：{entry.used_at or '未单独记录'}", base),
                    paragraph(f"使用环节：{entry.use_stage}", base),
                    paragraph(f"使用目的：{entry.purpose}", base),
                    paragraph(f"涉及章节：{'；'.join(entry.paper_sections)}", base),
                ]
            )
            if entry.process_summary:
                story.extend([paragraph("使用过程说明", label), paragraph(entry.process_summary, payload)])
            if entry.query and entry.output:
                story.extend(
                    [
                        paragraph("记录的输入 / 提示词", label),
                        paragraph(entry.query, payload),
                        paragraph("记录的输出", label),
                        paragraph(entry.output, payload),
                    ]
                )
            elif entry.disclosure:
                story.extend(
                    [paragraph("使用说明", label), paragraph(entry.disclosure, payload)]
                )
            story.extend(
                [
                    paragraph("人工核验与修订", label),
                    paragraph(entry.human_review, payload),
                ]
            )
            if entry.adoption:
                story.extend(
                    [paragraph("最终采用方式", label), paragraph(entry.adoption, payload)]
                )
            if entry.evidence:
                story.extend(
                    [
                        paragraph("可追溯记录", label),
                        paragraph("；".join(entry.evidence), payload),
                    ]
                )
            if index != len(entries):
                story.append(Spacer(1, 5 * mm))

    def page_footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setTitle("人工智能工具使用详情")
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#829AB1"))
        canvas.drawString(17 * mm, 9 * mm, "人工智能工具使用详情")
        canvas.drawRightString(A4[0] - 17 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output_path


def render_reports(
    decision_log_path: Path,
    paper_workspace: Path,
    support_dir: Path,
    competition: Optional[str] = None,
    *,
    markdown_only: bool = False,
) -> List[Path]:
    """Render all outputs for one competition and return their paths."""
    decision_log, entries = load_ledger(decision_log_path, competition)
    selected = resolve_competition(competition, decision_log)
    if selected == "mcm":
        if markdown_only:
            raise LedgerValidationError("--markdown-only 仅用于 CUMCM")
        paper_workspace.mkdir(parents=True, exist_ok=True)
        md_path = paper_workspace / MCM_MARKDOWN_FILENAME
        md_path.write_text(
            render_mcm_markdown(entries, decision_log), encoding="utf-8"
        )
        return [md_path]

    if not entries:
        for stale_path in (
            support_dir / CUMCM_MARKDOWN_FILENAME,
            support_dir / CUMCM_PDF_FILENAME,
            paper_workspace / CUMCM_USE_FILENAME,
        ):
            stale_path.unlink(missing_ok=True)
        paper_workspace.mkdir(parents=True, exist_ok=True)
        statement_path = paper_workspace / CUMCM_NO_USE_FILENAME
        statement_path.write_text(render_cumcm_no_use_statement(), encoding="utf-8")
        return [statement_path]

    support_dir.mkdir(parents=True, exist_ok=True)
    paper_workspace.mkdir(parents=True, exist_ok=True)
    (paper_workspace / CUMCM_NO_USE_FILENAME).unlink(missing_ok=True)
    md_path = support_dir / CUMCM_MARKDOWN_FILENAME
    md_path.write_text(
        render_cumcm_markdown(entries, decision_log), encoding="utf-8"
    )
    statement_path = paper_workspace / CUMCM_USE_FILENAME
    statement_path.write_text(render_cumcm_use_statement(entries), encoding="utf-8")
    outputs = [md_path]
    if not markdown_only:
        outputs.append(
            render_cumcm_pdf(
                entries, decision_log, support_dir / CUMCM_PDF_FILENAME
            )
        )
    else:
        (support_dir / CUMCM_PDF_FILENAME).unlink(missing_ok=True)
    return outputs + [statement_path]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 decision_log.compliance.ai_usage 生成竞赛 AI 使用报告",
        epilog=(
            "最小字段：tool, model, version, use_stage, purpose, paper_sections, human_review；"
            "并填写 query+output，或对翻译/代码补全等非对话式用途填写 disclosure。"
            "CUMCM 可用 process_summary 记录使用过程；使用与未使用均需在参考文献前声明。"
            "显式 [] 表示未使用，字段缺失会报错。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--decision-log",
        help="decision_log.json 路径（默认 state/decision_log.json）",
    )
    parser.add_argument(
        "--competition",
        choices=("cumcm", "mcm"),
        help="覆盖日志中的 competition",
    )
    parser.add_argument(
        "--paper-workspace",
        default="paper_workspace",
        help="论文装配目录（默认 paper_workspace）",
    )
    parser.add_argument(
        "--support-dir",
        default="support_materials",
        help="支撑材料目录（默认 support_materials）",
    )
    parser.add_argument(
        "--markdown-only",
        action="store_true",
        help="CUMCM 仅生成 Markdown，不生成 PDF",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outputs = render_reports(
            resolve_decision_log_path(args.decision_log),
            Path(args.paper_workspace),
            Path(args.support_dir),
            args.competition,
            markdown_only=args.markdown_only,
        )
    except (LedgerValidationError, MissingDependency) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    for path in outputs:
        print(f"[OK] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
