# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Render and audit a DOCX-derived PDF, including an explicit visual-QA record."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from .office_common import (
    ArtifactFinding,
    extract_docx_text,
    findings_to_dict,
    normalize_text,
    scan_sensitive_text,
    sha256_file,
)




A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.890
A4_TOLERANCE_PT = 3.0








def _a4_page_geometry(reader: PdfReader) -> tuple[bool, list[dict[str, float | int | bool]]]:
    records: list[dict[str, float | int | bool]] = []
    all_a4 = True
    for index, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        is_a4 = (
            abs(width - A4_WIDTH_PT) <= A4_TOLERANCE_PT
            and abs(height - A4_HEIGHT_PT) <= A4_TOLERANCE_PT
        ) or (
            abs(height - A4_WIDTH_PT) <= A4_TOLERANCE_PT
            and abs(width - A4_HEIGHT_PT) <= A4_TOLERANCE_PT
        )
        all_a4 = all_a4 and is_a4
        records.append({"page": index, "width_pt": width, "height_pt": height, "a4": is_a4})
    return all_a4, records


def _page_has_graphics(page: Any) -> bool:
    try:
        resources = page.get("/Resources")
        resources = resources.get_object() if resources else {}
        xobjects = resources.get("/XObject") if resources else None
        xobjects = xobjects.get_object() if xobjects else {}
        return bool(xobjects)
    except Exception:
        return False


def _font_facts(reader: PdfReader) -> list[dict[str, Any]]:
    found: dict[tuple[str, bool], dict[str, Any]] = {}
    for page in reader.pages:
        try:
            resources = page.get("/Resources")
            resources = resources.get_object() if resources else {}
            fonts = resources.get("/Font") if resources else None
            fonts = fonts.get_object() if fonts else {}
        except Exception:
            continue
        for reference in fonts.values():
            try:
                font = reference.get_object()
                base = str(font.get("/BaseFont", "unknown"))
                descriptor = font.get("/FontDescriptor")
                if not descriptor and font.get("/DescendantFonts"):
                    descendants = font.get("/DescendantFonts").get_object()
                    if descendants:
                        descriptor = descendants[0].get_object().get("/FontDescriptor")
                descriptor = descriptor.get_object() if descriptor else {}
                embedded = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
                found[(base, embedded)] = {"base_font": base, "embedded": embedded}
            except Exception:
                continue
    return sorted(found.values(), key=lambda item: (str(item["base_font"]), not bool(item["embedded"])))


def _paper_segments(page_texts: list[str]) -> dict[str, Any]:
    normalized = [normalize_text(text) for text in page_texts]
    first = normalized[0] if normalized else ""
    abstract_ok = normalize_text("摘要") in first and normalize_text("关键词") in first
    def has_body_heading(text: str) -> bool:
        for line in text.splitlines():
            heading = line.strip()
            # Inspect headings, not words mentioned in an abstract or paragraph.
            numbered = re.fullmatch(
                r"(?:一[、.．\s]+|1[、.．\s]+|第一章\s*)([^\d\W][^。；;!?！？]{0,45})",
                heading,
            )
            title = numbered.group(1).strip() if numbered else heading
            if normalize_text(title) in {"摘要", "关键词", "目录", "参考文献", "附录", "AI工具使用声明"}:
                continue
            if numbered or re.fullmatch(r"(?:问题重述|问题分析|题意分析|模型假设|符号说明|引言|模型建立)", title):
                return True
        return False

    first_has_body = has_body_heading(page_texts[0]) if page_texts else False
    toc_found = any(
        re.search(r"(?:^|\n)\s*目录\s*(?:\n|$)", text) for text in page_texts
    )
    body_start = next(
        (index for index, text in enumerate(page_texts, start=1) if has_body_heading(text)),
        None,
    )
    appendix_start = None
    appendix_page_counted_as_body = False
    for index, text in enumerate(page_texts, start=1):
        heading = re.search(r"(?:^|\n)\s*附录(?:\s|$|[一二三四五六七八九十A-Z0-9])", text)
        if heading:
            appendix_start = index
            # A page can contain a conclusion/references before its appendix.
            # Text extraction cannot reliably distinguish a short body prefix
            # from a header/footer, so nonempty prefixes count conservatively.
            appendix_page_counted_as_body = bool(text[:heading.start()].strip())
            break
    body_end = (appendix_start if appendix_page_counted_as_body else appendix_start - 1) if appendix_start else len(page_texts)
    body_pages = body_end - body_start + 1 if body_start else 0
    return {
        "abstract_page": 1 if page_texts else None,
        "abstract_page_ok": abstract_ok and not first_has_body,
        "body_start_page": body_start,
        "body_end_page": body_end if body_start else None,
        "body_pages": body_pages,
        "appendix_start_page": appendix_start,
        "appendix_page_counted_as_body": appendix_page_counted_as_body,
        "appendix_boundary_reason": (
            "visible prefix counted conservatively" if appendix_page_counted_as_body else
            "appendix starts at first visible content" if appendix_start else "no appendix heading"
        ),
        "toc_found": toc_found,
    }




def _source_anchor_coverage(docx_path: Path, pdf_text: str) -> tuple[float, list[str]]:
    source_lines = [line.strip() for line in extract_docx_text(docx_path).splitlines() if len(normalize_text(line)) >= 4]
    candidates: list[str] = []
    for line in source_lines:
        normalized = normalize_text(line)
        if normalized.startswith("[") or "office_formula.py" in line:
            continue
        candidates.append(normalized[:48])
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return 0.0, []
    normalized_pdf = normalize_text(pdf_text)
    missing = [anchor for anchor in candidates if anchor not in normalized_pdf]
    return (len(candidates) - len(missing)) / len(candidates), missing


def audit_pdf(
    pdf_path: str | Path,
    *,
    source_docx: str | Path | None = None,
    metadata_path: str | Path | None = None,
    visual_qa_path: str | Path | None = None,
    require_visual_qa: bool = True,
    minimum_text_anchor_coverage: float = 0.70,
    body_max_pages: int = 30,
    artifact_kind: str = "paper",
    require_a4: bool = False, check_identity: bool = True,
) -> dict[str, Any]:
    if artifact_kind not in {"paper", "supporting"}:
        raise ValueError("artifact_kind must be paper or supporting")
    artifact = Path(pdf_path)
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    reader = PdfReader(str(artifact))
    findings: list[ArtifactFinding] = []
    findings.append(
        ArtifactFinding(
            "pdf.readable",
            "pass" if len(reader.pages) > 0 and not reader.is_encrypted else "fail",
            "error",
            "PDF is readable, unencrypted, and has at least one page",
            json.dumps({"page_count": len(reader.pages), "encrypted": reader.is_encrypted}),
        )
    )
    page_texts = [page.extract_text() or "" for page in reader.pages]
    pdf_text = "\n".join(page_texts)
    nonempty_pages = [
        index
        for index, (page, text) in enumerate(zip(reader.pages, page_texts), start=1)
        if len(normalize_text(text)) >= 8 or _page_has_graphics(page)
    ]
    empty_pages = sorted(set(range(1, len(reader.pages) + 1)) - set(nonempty_pages))
    findings.append(
        ArtifactFinding(
            "pdf.nonempty_pages",
            "pass" if not empty_pages and len(normalize_text(pdf_text)) >= 80 else "fail",
            "error",
            "every PDF page has extractable content or graphics and the paper is not blank",
            json.dumps({"empty_pages": empty_pages, "text_characters": len(normalize_text(pdf_text))}),
        )
    )
    a4_ok, page_geometry = _a4_page_geometry(reader)
    findings.append(
        ArtifactFinding(
            "pdf.a4_geometry",
            "pass" if a4_ok or not require_a4 else "fail",
            "error",
            "all PDF MediaBoxes are A4",
            json.dumps(page_geometry[:40], ensure_ascii=False),
        )
    )
    segments: dict[str, Any] = {}
    if artifact_kind == "paper":
        segments = _paper_segments(page_texts)
        segment_ok = (
            segments["abstract_page_ok"]
            and segments["body_start_page"] == 2
            and not segments["toc_found"]
            and 0 < int(segments["body_pages"]) <= int(body_max_pages)
        )
        findings.append(
            ArtifactFinding(
                "pdf.paper_segments",
                "pass" if segment_ok else "fail",
                "error",
                "page 1 is the abstract, body starts on page 2, no contents page exists, and body pages stay within the sealed limit",
                json.dumps({**segments, "body_max_pages": body_max_pages}, ensure_ascii=False),
            )
        )
    glyph_ok = "\ufffd" not in pdf_text and "�" not in pdf_text
    findings.append(
        ArtifactFinding(
            "pdf.no_replacement_glyphs",
            "pass" if glyph_ok else "fail",
            "error",
            "extracted PDF text contains no Unicode replacement glyphs",
        )
    )
    fonts = _font_facts(reader)
    unembedded = [item["base_font"] for item in fonts if not item["embedded"]]
    findings.append(
        ArtifactFinding(
            "pdf.font_portability",
            "pass" if not unembedded else "fail",
            "warning",
            "all discovered PDF fonts are embedded or subset embedded",
            json.dumps({"fonts": fonts, "unembedded": unembedded}, ensure_ascii=False)[:4000],
        )
    )
    metadata_text = json.dumps(dict(reader.metadata or {}), ensure_ascii=False)
    sensitive = scan_sensitive_text(pdf_text + "\n" + metadata_text, check_identity=check_identity)
    findings.append(
        ArtifactFinding(
            "pdf.privacy",
            "pass" if not sensitive else "fail",
            "error",
            "no absolute path, identity, or internal token appears in extracted PDF content/metadata",
            json.dumps(sensitive, ensure_ascii=False),
        )
    )

    sidecar = Path(metadata_path) if metadata_path else artifact.with_suffix(artifact.suffix + ".metadata.json")
    metadata: dict[str, Any] = {}
    if sidecar.is_file():
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        hash_ok = metadata.get("sha256") == sha256_file(artifact)
        findings.append(ArtifactFinding("pdf.hash_binding", "pass" if hash_ok else "fail", "error", "PDF matches metadata SHA-256"))
        direction_ok = metadata.get("conversion_direction") == "DOCX_TO_PDF_ONLY" and metadata.get("source_docx_editable_master") is True
        findings.append(ArtifactFinding("pdf.one_way_derivative", "pass" if direction_ok else "fail", "error", "PDF is bound as a DOCX-only derivative"))
        formal_ok = metadata.get("history_class") != "formal_milestone" or bool(metadata.get("provenance_id"))
        findings.append(ArtifactFinding("pdf.provenance_binding", "pass" if formal_ok else "fail", "error", "formal PDF is bound to provenance_id"))
    else:
        findings.append(ArtifactFinding("pdf.hash_binding", "fail", "error", "PDF metadata sidecar is missing"))

    coverage = None
    missing_anchors: list[str] = []
    if source_docx:
        source = Path(source_docx)
        source_hash_ok = bool(metadata) and metadata.get("source_docx_sha256") == sha256_file(source)
        findings.append(ArtifactFinding("pdf.source_docx_binding", "pass" if source_hash_ok else "fail", "error", "PDF is bound to the exact DOCX master"))
        coverage, missing_anchors = _source_anchor_coverage(source, pdf_text)
        coverage_ok = coverage >= minimum_text_anchor_coverage
        findings.append(
            ArtifactFinding(
                "pdf.text_anchor_coverage",
                "pass" if coverage_ok else "fail",
                "error",
                f"DOCX/PDF text anchor coverage is at least {minimum_text_anchor_coverage:.0%}",
                json.dumps({"coverage": coverage, "missing_sample": missing_anchors[:10]}, ensure_ascii=False),
            )
        )

    if require_visual_qa:
        visual_ok = False
        evidence: dict[str, Any] = {}
        if visual_qa_path and Path(visual_qa_path).is_file():
            evidence = json.loads(Path(visual_qa_path).read_text(encoding="utf-8"))
            visual_ok = (
                evidence.get("source_pdf_sha256") == sha256_file(artifact)
                and evidence.get("status") == "pass"
                and evidence.get("inspected_pages") == list(range(1, len(reader.pages) + 1))
            )
        findings.append(
            ArtifactFinding(
                "pdf.visual_qa",
                "pass" if visual_ok else "fail",
                "error",
                "every rendered page has an explicit passing visual review",
                json.dumps(evidence, ensure_ascii=False)[:2000],
            )
        )

    passed = all(finding.status == "pass" for finding in findings if finding.severity == "error")
    return {
        "artifact": artifact.name,
        "artifact_kind": artifact_kind,
        "sha256": sha256_file(artifact),
        "page_count": len(reader.pages),
        "passed": passed,
        "text_anchor_coverage": coverage,
        "segments": segments,
        "fonts": fonts,
        "findings": findings_to_dict(findings),
    }






