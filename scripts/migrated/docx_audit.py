# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Structural gate for editable CUMCM DOCX artifacts.

This does not replace page rendering.  It verifies OOXML facts that a visual
inspection cannot reliably prove, including native equations, immutable hash
bindings, privacy, and AI-statement placement.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Iterable

from lxml import etree

from .office_common import (
    ArtifactFinding,
    NS,
    docx_structural_facts,
    findings_to_dict,
    normalize_text,
    scan_sensitive_text,
    sha256_file,
)
from .office_formula import formula_bookmark_name


FORMAL_MILESTONES = {"structure", "full_draft", "candidate_final", "final"}
PLACEHOLDER_PATTERN = re.compile(r"\[(?:填写|待补|由队伍填写|关键词\d|MS-Qx|Git提交|数据哈希|冻结后|正式数值|正式图表|参考文献|只写|现实对象|逐条|通过 office_formula|逐项解释|预测/拟合|每个结论|适用边界)[^\]]*\]")
A4_WIDTH_DXA = 11906
A4_HEIGHT_DXA = 16838
MIN_MARGIN_DXA = 1417
A4_TOLERANCE_DXA = 45
VISIBLE_INTERNAL_FORMULA_ID_PATTERN = re.compile(
    r"模型规格公式标识|(?<![A-Za-z0-9_])(?:F|C)-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9_])",
    flags=re.I,
)
GREEK_SYMBOL_PATTERN = re.compile(
    r"[Α-Ωα-ωϑϕϖϵ]|(?<![A-Za-z])(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)(?![A-Za-z])",
    flags=re.I,
)
READER_VISIBLE_MATH_SOURCE_PATTERNS = (
    ("latex delimiter", re.compile(r"\$[^$]+\$|\\\(|\\\)|\\\[|\\\]")),
    ("latex command", re.compile(r"\\[A-Za-z]+")),
    ("linear subscript", re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9({]")),
    ("linear exponent", re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9.)]+\^[+-]?[A-Za-z0-9({]")),
    ("ASCII comparison", re.compile(r"(?:>=|<=)|(?<![A-Za-z])[A-Za-z]\s*[<>]\s*[+-]?(?:\d|\.)")),
    (
        "ASCII Greek variable",
        re.compile(
            r"(?<![A-Za-z])(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|"
            r"lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)(?![A-Za-z])"
        ),
    ),
)
# Exclude only complete file-reference tokens, never their containing paragraph
# or table. Arithmetic suffixes and unknown extensions remain in the math scan.
FILE_REFERENCE_PATTERN = re.compile(
    r"(?<![\w./\\^])(?:[\w-]+[./\\])*[\w-]+\."
    r"(?:csv|tsv|txt|xlsx?|py|m|ipynb|json|ya?ml|docx?|pdf|png|svg|jpe?g|zip|rar|dat|mat)"
    r"(?![\w./\\^=+*<>$-])",
    flags=re.I,
)
OMML_RAW_SOURCE_PATTERN = re.compile(
    r"[_^\\${}]|(?:>=|<=)|(?<![A-Za-z])(?:alpha|beta|gamma|delta|eta|kappa|lambda|sigma|tau)(?![A-Za-z])"
)


def _document_root(path: Path):
    with zipfile.ZipFile(path) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def _page_layout_issues(path: Path) -> list[str]:
    issues: list[str] = []
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        sections = root.xpath(".//w:sectPr", namespaces=NS)
        if not sections:
            return ["missing section properties"]
        for index, section in enumerate(sections, start=1):
            size = section.xpath("./w:pgSz", namespaces=NS)
            if not size:
                issues.append(f"section {index}: missing page size")
                continue
            width = int(size[0].get(f"{{{NS['w']}}}w", "0"))
            height = int(size[0].get(f"{{{NS['w']}}}h", "0"))
            a4 = (
                abs(width - A4_WIDTH_DXA) <= A4_TOLERANCE_DXA
                and abs(height - A4_HEIGHT_DXA) <= A4_TOLERANCE_DXA
            ) or (
                abs(height - A4_WIDTH_DXA) <= A4_TOLERANCE_DXA
                and abs(width - A4_HEIGHT_DXA) <= A4_TOLERANCE_DXA
            )
            if not a4:
                issues.append(f"section {index}: page is not A4 ({width}x{height} DXA)")
            margins = section.xpath("./w:pgMar", namespaces=NS)
            if not margins:
                issues.append(f"section {index}: missing margins")
            else:
                for edge in ("top", "right", "bottom", "left"):
                    value = int(margins[0].get(f"{{{NS['w']}}}{edge}", "0"))
                    if value < MIN_MARGIN_DXA:
                        issues.append(
                            f"section {index}: {edge} margin {value} DXA is below 25 mm"
                        )
        first_page_number = sections[0].xpath("./w:pgNumType/@w:start", namespaces=NS)
        if first_page_number != ["1"]:
            issues.append("page numbering must start at Arabic 1 on the abstract page")

        footer_ok = False
        decorated_page_number = False
        for name in sorted(item for item in archive.namelist() if re.fullmatch(r"word/footer\d+\.xml", item)):
            footer = etree.fromstring(archive.read(name))
            for paragraph in footer.xpath(".//w:p", namespaces=NS):
                instructions = " ".join(
                    paragraph.xpath(".//w:fldSimple/@w:instr | .//w:instrText/text()", namespaces=NS)
                )
                if re.search(r"\bPAGE\b", instructions, flags=re.I):
                    alignment = paragraph.xpath("./w:pPr/w:jc/@w:val", namespaces=NS)
                    footer_ok = footer_ok or alignment == ["center"]
                    visible = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
                    decorated_page_number = decorated_page_number or "第" in visible or "页" in visible
        if not footer_ok:
            issues.append("footer lacks a centred PAGE field")
        if decorated_page_number:
            issues.append("page number must be a plain Arabic number, not '第 n 页'")
    return issues


def _paper_structure_issues(path: Path) -> tuple[list[str], bool]:
    root = _document_root(path)
    paragraph_records: list[tuple[int, str, bool]] = []
    heading_indices: list[int] = []
    break_before_indices: list[int] = []
    for index, paragraph in enumerate(root.xpath(".//w:body/w:p", namespaces=NS)):
        text = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS)).strip()
        has_page_break = bool(paragraph.xpath(".//w:br[@w:type='page']", namespaces=NS))
        paragraph_records.append((index, text, has_page_break))
        style = paragraph.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS)
        if style == ["Heading1"] or paragraph.xpath("./w:pPr/w:outlineLvl[@w:val='0']", namespaces=NS):
            heading_indices.append(index)
        if paragraph.xpath("./w:pPr/w:pageBreakBefore[not(@w:val) or @w:val='1' or @w:val='true']", namespaces=NS):
            break_before_indices.append(index)
    text_records = [(index, text) for index, text, _ in paragraph_records if text]
    normalized = [(index, normalize_text(text)) for index, text in text_records]
    issues: list[str] = []
    abstract_positions = [index for index, text in normalized if text == normalize_text("摘要")]
    keyword_positions = [index for index, text in normalized if text.startswith(normalize_text("关键词"))]
    body_positions = [
        index
        for index, text in normalized
        if text.startswith(normalize_text("一、问题重述"))
        or text.startswith(normalize_text("1问题重述"))
    ]
    if keyword_positions:
        # Official structure does not prescribe a fixed name for the first body section.
        body_positions = sorted(set(body_positions) | {i for i in heading_indices if i > keyword_positions[0]})
    if not abstract_positions:
        issues.append("missing abstract heading")
    if not keyword_positions:
        issues.append("missing keywords on the abstract page")
    if not body_positions:
        issues.append("missing body start heading")
    if abstract_positions and keyword_positions and abstract_positions[0] >= keyword_positions[0]:
        issues.append("abstract heading must precede keywords")
    if keyword_positions and body_positions and keyword_positions[0] >= body_positions[0]:
        issues.append("keywords must precede the body")
    if any(text == normalize_text("目录") or text.startswith(normalize_text("目录")) for _, text in normalized):
        issues.append("table of contents is forbidden")
    all_text = normalize_text("\n".join(text for _, text in text_records))
    if normalize_text("承诺书") in all_text or normalize_text("编号专用页") in all_text:
        issues.append("electronic paper must not contain the commitment or numbering page")
    page_break_indices = [index for index, _, has_break in paragraph_records if has_break]
    explicit_abstract_break = bool(
        page_break_indices
        and keyword_positions
        and body_positions
        and keyword_positions[0] <= page_break_indices[0] < body_positions[0]
    )
    explicit_abstract_break = explicit_abstract_break or bool(body_positions and body_positions[0] in break_before_indices)
    return issues, explicit_abstract_break


def _formula_inventory_issues(path: Path, expected_bookmarks: set[str]) -> list[str]:
    root = _document_root(path)
    issues: list[str] = []
    names = root.xpath(".//w:bookmarkStart/@w:name", namespaces=NS)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        issues.append("duplicate formula bookmarks: " + ", ".join(duplicates))
    for bookmark in sorted(expected_bookmarks):
        nodes = root.xpath(
            ".//w:bookmarkStart[@w:name=$name]", namespaces=NS, name=bookmark
        )
        if len(nodes) != 1:
            issues.append(f"{bookmark}: expected exactly one bookmark")
            continue
        paragraph = nodes[0].getparent()
        while paragraph is not None and paragraph.tag != f"{{{NS['w']}}}p":
            paragraph = paragraph.getparent()
        if paragraph is None or not paragraph.xpath(".//m:oMath", namespaces=NS):
            issues.append(f"{bookmark}: bookmark does not contain native OMML")
    sequence_fields = [
        value
        for value in root.xpath(".//w:fldSimple/@w:instr | .//w:instrText/text()", namespaces=NS)
        if re.search(r"\bSEQ\s+Equation\b", value, flags=re.I)
    ]
    if expected_bookmarks and len(sequence_fields) < len(expected_bookmarks):
        issues.append(
            f"equation numbering fields are incomplete: {len(sequence_fields)} < {len(expected_bookmarks)}"
        )
    return issues


def _image_semantics_issues(path: Path) -> list[str]:
    root = _document_root(path)
    issues: list[str] = []
    anchor_count = int(root.xpath("count(.//wp:anchor)", namespaces=NS))
    if anchor_count:
        issues.append(f"{anchor_count} floating image(s) found; paper figures must be inline")
    for node in root.xpath(".//wp:inline/wp:docPr", namespaces=NS):
        description = (node.get("descr") or node.get("title") or "").strip()
        if not description:
            issues.append(f"inline image {node.get('id', '?')} lacks a Figure ID/description")
    return issues


def _font_portability_issues(path: Path) -> list[str]:
    issues: list[str] = []
    with zipfile.ZipFile(path) as archive:
        if "word/styles.xml" not in archive.namelist():
            return ["styles.xml is missing"]
        styles = etree.fromstring(archive.read("word/styles.xml"))
        normal_fonts = styles.xpath(
            ".//w:style[@w:styleId='Normal']/w:rPr/w:rFonts/@w:eastAsia",
            namespaces=NS,
        )
        if not normal_fonts:
            issues.append("Normal style lacks an explicit East Asian font")
        suspicious = styles.xpath(
            ".//w:rFonts/@w:eastAsia", namespaces=NS
        )
        bad = sorted(
            {
                value
                for value in suspicious
                if value.casefold() in {"ms gothic", "arial", "calibri", "times new roman"}
            }
        )
        if bad:
            issues.append("suspicious CJK fallback font(s): " + ", ".join(bad))
    return issues


def _visible_internal_formula_id_issues(text: str) -> list[str]:
    return sorted(set(match.group(0) for match in VISIBLE_INTERNAL_FORMULA_ID_PATTERN.finditer(text)))


def _looks_like_math_symbol(value: str) -> bool:
    compact = value.strip()
    if not compact:
        return False
    if re.search(r"[_^\\{}=<>±×÷∑∫√̂()]", compact):
        return True
    if GREEK_SYMBOL_PATTERN.search(compact):
        return True
    if re.fullmatch(r"[A-Za-z]", compact):
        return True
    return bool("," in compact and re.search(r"(?:^|[,，]\s*)[A-Za-z](?:\b|_)", compact))


def _symbol_table_native_math_issues(path: Path) -> list[str]:
    root = _document_root(path)
    issues: list[str] = []
    for table_index, table in enumerate(root.xpath(".//w:tbl", namespaces=NS), start=1):
        rows = table.xpath("./w:tr", namespaces=NS)
        if not rows:
            continue
        header_cells = rows[0].xpath("./w:tc", namespaces=NS)
        if not header_cells:
            continue
        first_header = normalize_text("".join(header_cells[0].xpath(".//w:t/text()", namespaces=NS)))
        all_headers = normalize_text(
            " ".join("".join(cell.xpath(".//w:t/text()", namespaces=NS)) for cell in header_cells)
        )
        if first_header != normalize_text("符号") or not any(
            normalize_text(label) in all_headers for label in ("含义", "说明", "定义")
        ):
            continue
        for row_index, row in enumerate(rows[1:], start=2):
            cells = row.xpath("./w:tc", namespaces=NS)
            if not cells:
                continue
            symbol_cell = cells[0]
            if symbol_cell.xpath(".//m:oMath | .//m:oMathPara", namespaces=NS):
                continue
            plain_text = "".join(symbol_cell.xpath(".//w:t/text()", namespaces=NS)).strip()
            if _looks_like_math_symbol(plain_text):
                issues.append(
                    f"table {table_index} row {row_index}: math-like symbol {plain_text!r} is plain text"
                )
    return issues


def _reader_visible_math_source_issues(path: Path, *, file_reference_paths: Iterable[str] = ()) -> list[str]:
    root = _document_root(path)
    issues: list[str] = []
    in_appendix = False
    # Internal adapter input, derived only after paper-source projection and all
    # current object/file checks passed. No arbitrary ignore spans or regex widening.
    file_labels = {"文件：" + item for item in file_reference_paths}
    for index, paragraph in enumerate(root.xpath(".//w:p", namespaces=NS), start=1):
        text = "".join(
            paragraph.xpath(".//w:t[not(ancestor::m:oMath)]/text()", namespaces=NS)
        ).strip()
        if text == "附录" or re.match(r"^附录\s*[A-Za-z一二三四五六七八九十0-9](?:\s|[：:]|$)", text):
            in_appendix = True
        styles = paragraph.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS)
        if in_appendix and styles == ["CUMCMSourceCode"]:
            continue
        if in_appendix and text in file_labels:
            continue
        scan_text = FILE_REFERENCE_PATTERN.sub(" ", PLACEHOLDER_PATTERN.sub("", text)).strip()
        if not scan_text or re.match(r"^\[\d+\]", scan_text):
            continue
        labels = [
            label
            for label, pattern in READER_VISIBLE_MATH_SOURCE_PATTERNS
            if pattern.search(scan_text)
        ]
        if labels:
            issues.append(f"paragraph {index} ({', '.join(labels)}): {text[:160]!r}")
    return issues


def _native_math_build_issues(path: Path) -> list[str]:
    root = _document_root(path)
    issues: list[str] = []
    for index, math in enumerate(root.xpath(".//m:oMath", namespaces=NS), start=1):
        text = "".join(math.xpath(".//m:t/text()", namespaces=NS))
        reasons: list[str] = []
        if OMML_RAW_SOURCE_PATTERN.search(text):
            reasons.append("raw linear/LaTeX token")
        opening_delimiters = sum(text.count(char) for char in "[({")
        closing_delimiters = sum(text.count(char) for char in "])}")
        if opening_delimiters != closing_delimiters:
            reasons.append("unbalanced delimiter")
        if reasons:
            issues.append(f"math {index} ({', '.join(reasons)}): {text[:160]!r}")
    return issues


def _finding(check_id: str, passed: bool, message: str, *, severity: str = "error", evidence: str = "") -> ArtifactFinding:
    return ArtifactFinding(check_id, "pass" if passed else "fail", severity, message, evidence)


def _table_geometry_findings(path: Path) -> list[str]:
    issues: list[str] = []
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    available_widths: list[int] = []
    for section in root.xpath(".//w:sectPr", namespaces=NS):
        sizes = section.xpath("./w:pgSz", namespaces=NS)
        margins = section.xpath("./w:pgMar", namespaces=NS)
        if sizes and margins:
            page_width = int(sizes[0].get(f"{{{NS['w']}}}w", "0"))
            left = int(margins[0].get(f"{{{NS['w']}}}left", "0"))
            right = int(margins[0].get(f"{{{NS['w']}}}right", "0"))
            if page_width > left + right:
                available_widths.append(page_width - left - right)
    available_width = min(available_widths) if available_widths else 0
    for index, table in enumerate(root.xpath(".//w:tbl", namespaces=NS), start=1):
        tbl_w = table.xpath("./w:tblPr/w:tblW", namespaces=NS)
        tbl_ind = table.xpath("./w:tblPr/w:tblInd", namespaces=NS)
        tbl_layout = table.xpath("./w:tblPr/w:tblLayout/@w:type", namespaces=NS)
        grid_widths = [int(value) for value in table.xpath("./w:tblGrid/w:gridCol/@w:w", namespaces=NS) if value.isdigit()]
        if not tbl_w or tbl_w[0].get(f"{{{NS['w']}}}type") != "dxa":
            issues.append(f"table {index}: tblW is missing or not DXA")
            continue
        declared = tbl_w[0].get(f"{{{NS['w']}}}w")
        if not declared or not declared.isdigit() or not grid_widths or int(declared) != sum(grid_widths):
            issues.append(f"table {index}: tblW does not match tblGrid")
        elif available_width and int(declared) > available_width + 5:
            issues.append(
                f"table {index}: width {declared} DXA exceeds section width {available_width} DXA"
            )
        if not tbl_ind or tbl_ind[0].get(f"{{{NS['w']}}}type") != "dxa":
            issues.append(f"table {index}: tblInd is missing or not DXA")
        if tbl_layout != ["fixed"]:
            issues.append(f"table {index}: tblLayout is not fixed")
        if tbl_ind:
            indent = int(tbl_ind[0].get(f"{{{NS['w']}}}w", "0"))
            declared_width = int(declared) if declared and declared.isdigit() else 0
            if indent < 0 or (available_width and declared_width + indent > available_width + 5):
                issues.append(f"table {index}: indent causes the table to exceed the text area")
        for row_index, row in enumerate(table.xpath("./w:tr", namespaces=NS), start=1):
            grid_position = 0
            for cell_index, cell in enumerate(row.xpath("./w:tc", namespaces=NS), start=1):
                width_values = cell.xpath("./w:tcPr/w:tcW/@w:w", namespaces=NS)
                span_values = cell.xpath("./w:tcPr/w:gridSpan/@w:val", namespaces=NS)
                span = int(span_values[0]) if span_values and span_values[0].isdigit() else 1
                if not width_values or not width_values[0].isdigit() or grid_position + span > len(grid_widths):
                    issues.append(f"table {index} row {row_index} cell {cell_index}: invalid tcW/gridSpan")
                    grid_position += span
                    continue
                expected_width = sum(grid_widths[grid_position : grid_position + span])
                if int(width_values[0]) != expected_width:
                    issues.append(f"table {index} row {row_index} cell {cell_index}: tcW does not match spanned tblGrid")
                grid_position += span
            if grid_position != len(grid_widths):
                issues.append(f"table {index} row {row_index}: gridSpan coverage does not match tblGrid")
    return issues


def audit_docx(
    path: str | Path,
    *,
    expected_formula_ids: Iterable[str] = (),
    metadata_path: str | Path | None = None,
    final_mode: bool = False,
    require_ai_before_references: bool = False,
    check_identity: bool = True,
    visual_qa_path: str | Path | None = None,
    require_visual_qa: bool = False,
    artifact_kind: str = "paper",
    evaluation_mode: str = "formal_contest",
    file_reference_paths: Iterable[str] = (),
) -> dict[str, object]:
    from .workflow_policy import mode_of
    evaluation_mode = mode_of({"evaluation_mode": evaluation_mode})
    if artifact_kind not in {"paper", "supporting"}:
        raise ValueError("artifact_kind must be paper or supporting")
    artifact = Path(path)
    facts = docx_structural_facts(artifact)
    findings: list[ArtifactFinding] = []

    findings.append(_finding("docx.package", True, "DOCX package and document.xml are readable"))
    if artifact_kind == "paper":
        layout_issues = _page_layout_issues(artifact)
        findings.append(
            _finding(
                "docx.official_page_layout",
                not layout_issues,
                "all sections are A4 with margins >=25 mm and centred Arabic PAGE numbering from 1",
                evidence=json.dumps(layout_issues, ensure_ascii=False),
            )
        )
        structure_issues, explicit_abstract_break = _paper_structure_issues(artifact)
        findings.append(
            _finding(
                "docx.abstract_and_toc",
                not structure_issues,
                "the electronic paper starts with an abstract section and contains no contents/identity pages",
                evidence=json.dumps(structure_issues, ensure_ascii=False),
            )
        )
        findings.append(
            _finding(
                "docx.abstract_page_break",
                explicit_abstract_break,
                "an explicit page break keeps title, abstract, and keywords on the dedicated first page",
                severity="error" if final_mode else "warning",
                evidence=json.dumps({"explicit_break": explicit_abstract_break}),
            )
        )
    sensitive = scan_sensitive_text(
        str(facts["text"]) + "\n" + "\n".join(str(value) for value in facts["relationship_targets"]),
        check_identity=check_identity,
    )
    findings.append(
        _finding(
            "docx.privacy",
            not sensitive,
            "no absolute path, internal token, or disallowed identity was found" if not sensitive else "privacy/internal-token findings detected",
            evidence=json.dumps(sensitive, ensure_ascii=False),
        )
    )

    if artifact_kind == "paper":
        visible_formula_ids = _visible_internal_formula_id_issues(str(facts["text"]))
        findings.append(
            _finding(
                "docx.no_visible_internal_formula_ids",
                not visible_formula_ids,
                "internal ModelSpec/formula audit IDs are hidden metadata, not reader-visible paper text",
                evidence=json.dumps(visible_formula_ids, ensure_ascii=False),
            )
        )
        symbol_math_issues = _symbol_table_native_math_issues(artifact)
        findings.append(
            _finding(
                "docx.symbol_table_native_math",
                not symbol_math_issues,
                "math-like entries in symbol-definition tables use inline native OMML",
                evidence=json.dumps(symbol_math_issues, ensure_ascii=False),
            )
        )
        visible_math_source_issues = _reader_visible_math_source_issues(artifact, file_reference_paths=file_reference_paths)
        findings.append(
            _finding(
                "docx.no_reader_visible_math_source",
                not visible_math_source_issues,
                "reader-visible prose and tables contain no LaTeX or linear-equation source",
                evidence=json.dumps(visible_math_source_issues, ensure_ascii=False),
            )
        )
        native_math_build_issues = _native_math_build_issues(artifact)
        findings.append(
            _finding(
                "docx.native_math_fully_built",
                not native_math_build_issues,
                "every native OMML object is fully structured and contains no unbuilt source tokens",
                evidence=json.dumps(native_math_build_issues, ensure_ascii=False),
            )
        )

    expected_bookmarks = {formula_bookmark_name(value) for value in expected_formula_ids}
    actual_bookmarks = set(facts["formula_bookmarks"])
    missing_formula_ids = sorted(expected_bookmarks - actual_bookmarks)
    findings.append(
        _finding(
            "docx.native_formula_inventory",
            not missing_formula_ids and int(facts["formula_count"]) >= len(expected_bookmarks),
            "all declared formulas are native OMML with stable IDs",
            evidence=json.dumps({"missing": missing_formula_ids, "formula_count": facts["formula_count"]}, ensure_ascii=False),
        )
    )
    formula_inventory_issues = _formula_inventory_issues(artifact, expected_bookmarks)
    findings.append(
        _finding(
            "docx.formula_ids_and_numbering",
            not formula_inventory_issues,
            "each declared formula bookmark contains OMML and has a live SEQ Equation number",
            evidence=json.dumps(formula_inventory_issues, ensure_ascii=False),
        )
    )
    image_formula_hints = list(facts["image_formula_hints"])
    media_formula_names = [
        name for name in facts["media_names"] if re.search(r"(?i)(formula|equation|math|公式|方程)", str(name))
    ]
    findings.append(
        _finding(
            "docx.no_formula_screenshots",
            not image_formula_hints and not media_formula_names,
            "no image is labelled or named as a formula; declared formulas are OMML",
            evidence=json.dumps(image_formula_hints + media_formula_names, ensure_ascii=False),
        )
    )
    if artifact_kind == "paper":
        image_issues = _image_semantics_issues(artifact)
        findings.append(
            _finding(
                "docx.image_semantics",
                not image_issues,
                "paper images are inline and carry a stable Figure ID/description",
                severity="error" if final_mode else "warning",
                evidence=json.dumps(image_issues, ensure_ascii=False),
            )
        )
    font_issues = _font_portability_issues(artifact)
    findings.append(
        _finding(
            "docx.font_portability",
            not font_issues,
            "the document has an explicit CJK body font and no suspicious fallback",
            severity="warning",
            evidence=json.dumps(font_issues, ensure_ascii=False),
        )
    )

    geometry_issues = _table_geometry_findings(artifact)
    findings.append(
        _finding(
            "docx.table_geometry",
            not geometry_issues,
            "all tables use matching fixed DXA geometry",
            evidence=json.dumps(geometry_issues, ensure_ascii=False),
        )
    )
    findings.append(
        _finding(
            "docx.review_residue",
            not facts["comments_present"] and int(facts["tracked_change_count"]) == 0,
            "no comments or tracked changes remain",
            evidence=json.dumps(
                {"comments_present": facts["comments_present"], "tracked_change_count": facts["tracked_change_count"]}
            ),
        )
    )

    text = str(facts["text"])
    if final_mode:
        placeholders = sorted(set(PLACEHOLDER_PATTERN.findall(text)))
        findings.append(
            _finding(
                "docx.no_placeholders",
                not placeholders,
                "no workflow placeholder remains in final-mode DOCX",
                evidence=json.dumps(placeholders, ensure_ascii=False),
            )
        )
    if require_ai_before_references:
        from .cumcm_ai_declaration import ai_section_positions
        ai_pos, references_pos = ai_section_positions(text)
        findings.append(
            _finding(
                "docx.ai_statement_position",
                ai_pos >= 0 and references_pos >= 0 and ai_pos < references_pos,
                "AI-use statement is present before references",
                evidence=json.dumps({"ai_position": ai_pos, "references_position": references_pos}),
            )
        )
        from .cumcm_ai_declaration import classify_ai_declaration
        declaration_status, declaration_note = classify_ai_declaration(text, evaluation_mode=evaluation_mode)
        statement_ok = declaration_status in {"used", "not_used"}
        findings.append(
            _finding(
                "docx.ai_statement_official_wording",
                statement_ok,
                "Official sentence frame or explicit non-contest evaluation disclosure matches its mode",
                evidence=json.dumps({"matched": statement_ok, "evaluation_mode": evaluation_mode, "note": declaration_note}, ensure_ascii=False),
            )
        )

    metadata: dict[str, object] = {}
    sidecar = Path(metadata_path) if metadata_path else artifact.with_suffix(artifact.suffix + ".metadata.json")
    if sidecar.is_file():
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        hash_matches = metadata.get("sha256") == sha256_file(artifact)
        findings.append(_finding("docx.hash_binding", hash_matches, "DOCX matches its metadata SHA-256"))
        milestone = metadata.get("milestone")
        history_class = metadata.get("history_class")
        eligible = bool(metadata.get("formal_history_eligible"))
        milestone_consistent = (
            milestone in FORMAL_MILESTONES and eligible and history_class == "formal_milestone"
        ) or (milestone == "working" and not eligible and history_class == "working_build")
        findings.append(
            _finding(
                "docx.milestone_history",
                milestone_consistent,
                "only declared paper milestones are eligible for formal history",
                evidence=json.dumps({"milestone": milestone, "history_class": history_class, "eligible": eligible}),
            )
        )
        stable_ids = bool(metadata.get("artifact_id")) and (
            history_class != "formal_milestone" or bool(metadata.get("provenance_id"))
        )
        findings.append(
            _finding(
                "docx.stable_ids",
                stable_ids,
                "ArtifactRecord and formal provenance identifiers are bound",
                evidence=json.dumps(
                    {
                        "artifact_id": metadata.get("artifact_id"),
                        "provenance_id": metadata.get("provenance_id"),
                    }
                ),
            )
        )
        run_ok = not metadata.get("formal_values_present") or bool(metadata.get("run_id"))
        findings.append(
            _finding(
                "docx.formal_value_run_binding",
                run_ok,
                "formal numerical values are bound to a formal run_id",
                evidence=json.dumps(
                    {"formal_values_present": metadata.get("formal_values_present"), "run_id": metadata.get("run_id")}
                ),
            )
        )
    else:
        findings.append(_finding("docx.hash_binding", False, "metadata sidecar is missing"))

    if require_visual_qa:
        qa: dict[str, object] = {}
        visual_ok = False
        if visual_qa_path and Path(visual_qa_path).is_file():
            qa = json.loads(Path(visual_qa_path).read_text(encoding="utf-8"))
            page_count = int(qa.get("page_count", 0))
            visual_ok = (
                qa.get("source_docx_sha256") == sha256_file(artifact)
                and qa.get("status") == "pass"
                and qa.get("inspected_pages") == list(range(1, page_count + 1))
                and page_count > 0
            )
        findings.append(
            _finding(
                "docx.visual_qa",
                visual_ok,
                "every rendered DOCX page has an explicit passing visual review",
                evidence=json.dumps(qa, ensure_ascii=False)[:2000],
            )
        )

    passed = all(finding.status == "pass" or finding.severity != "error" for finding in findings)
    return {
        "artifact": artifact.name,
        "sha256": facts["sha256"],
        "passed": passed,
        "visual_qa_required": require_visual_qa,
        "metadata": metadata,
        "facts": {key: value for key, value in facts.items() if key not in {"text", "relationship_targets"}},
        "findings": findings_to_dict(findings),
    }


def assert_docx_ready(*args, **kwargs) -> dict[str, object]:
    report = audit_docx(*args, **kwargs)
    if not report["passed"]:
        failed = [item["check_id"] for item in report["findings"] if item["status"] == "fail" and item["severity"] == "error"]
        raise RuntimeError("DOCX NOT READY: " + ", ".join(failed))
    return report




