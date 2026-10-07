# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Deterministically audit CUMCM DOCX citations against a structured registry.

The registry is the source of truth.  The DOCX is inspected only at explicitly
declared Word bookmarks, so bracketed numbers elsewhere in prose, tables, or
formulas cannot be mistaken for citations.  First-appearance ordering is a
team quality preference and never an official hard rule.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
BOOKMARK_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
CURRENT_REFERENCE_STANDARD = "GB/T 7714-2025"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_registry(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("YAML 注册表需要 PyYAML；也可改用 JSON") from exc
        else:
            payload = yaml.safe_load(text)
    if not isinstance(payload, Mapping):
        raise ValueError("ReferenceRegistry 顶层必须是对象")
    return payload


def _normalized_doi(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text.rstrip(". ,;，；")


def _normalized_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _normalized_marker(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text)


def _normalized_language(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().replace("_", "-")
    if not text:
        return ""
    parts = text.split("-")
    return "-".join(
        [parts[0].lower(), *(part.upper() if len(part) == 2 else part for part in parts[1:])]
    )


def _is_chinese_language(value: Any) -> bool:
    return _normalized_language(value).lower().startswith("zh")


def _finding(
    check_id: str,
    passed: bool,
    *,
    severity: str,
    message: str,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def _extract_bookmarks(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    issues: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                return {}, [f"DOCX ZIP CRC 失败：{bad_member}"]
            try:
                xml = archive.read("word/document.xml")
            except KeyError:
                return {}, ["DOCX 缺少 word/document.xml"]
    except (OSError, zipfile.BadZipFile) as exc:
        return {}, [f"DOCX 无法读取：{exc}"]

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return {}, [f"word/document.xml 无法解析：{exc}"]

    active: dict[str, dict[str, Any]] = {}
    bookmarks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    position = 0
    for node in root.iter():
        if node.tag == f"{{{W_NS}}}bookmarkStart":
            bookmark_id = str(node.attrib.get(f"{{{W_NS}}}id", ""))
            name = str(node.attrib.get(f"{{{W_NS}}}name", ""))
            if not bookmark_id or not name:
                issues.append("存在缺少 id 或 name 的 bookmarkStart")
                continue
            if bookmark_id in active:
                issues.append(f"bookmark id 重复开启：{bookmark_id}")
                continue
            active[bookmark_id] = {
                "name": name,
                "position": position,
                "text_parts": [],
            }
            position += 1
        elif node.tag == f"{{{W_NS}}}t":
            value = node.text or ""
            for record in active.values():
                record["text_parts"].append(value)
        elif node.tag == f"{{{W_NS}}}bookmarkEnd":
            bookmark_id = str(node.attrib.get(f"{{{W_NS}}}id", ""))
            record = active.pop(bookmark_id, None)
            if record is None:
                issues.append(f"bookmarkEnd 无匹配 bookmarkStart：{bookmark_id}")
                continue
            bookmarks[str(record["name"])].append(
                {
                    "position": int(record["position"]),
                    "text": "".join(record["text_parts"]),
                }
            )
    for bookmark_id, record in sorted(active.items()):
        issues.append(
            f"bookmarkStart 未闭合：{record['name']} (id={bookmark_id})"
        )
    for name, occurrences in sorted(bookmarks.items()):
        if len(occurrences) > 1:
            issues.append(f"bookmark name 重复：{name}")
    return dict(bookmarks), issues


def _validate_registry(
    payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[str]]:
    errors: list[str] = []
    if str(payload.get("schema_version", "")) != "1.0":
        errors.append("schema_version 必须为 1.0")
    if payload.get("record_type") != "reference_registry":
        errors.append("record_type 必须为 reference_registry")

    style = payload.get("citation_style", {})
    if not isinstance(style, Mapping):
        style = {}
        errors.append("citation_style 必须为对象")
    marker_format = str(style.get("marker_format", "[{number}]"))
    if marker_format.count("{number}") != 1:
        errors.append("citation_style.marker_format 必须且只能包含一个 {number}")
    else:
        try:
            marker_format.format(number=1)
        except (IndexError, KeyError, ValueError) as exc:
            errors.append(f"citation_style.marker_format 无法解析：{exc}")

    no_external_sources = payload.get("no_external_sources", False)
    if not isinstance(no_external_sources, bool):
        errors.append("no_external_sources 必须为布尔值")
        no_external_sources = False
    raw_references = payload.get("references", [])
    raw_citations = payload.get("citations", [])
    if not isinstance(raw_references, list):
        errors.append("references 必须是列表")
        raw_references = []
    if not isinstance(raw_citations, list):
        errors.append("citations 必须是列表")
        raw_citations = []
    if no_external_sources and (raw_references or raw_citations):
        errors.append("no_external_sources=true 时 references/citations 必须为空")
    if not no_external_sources and (not raw_references or not raw_citations):
        errors.append(
            "存在外部来源时 references/citations 均须非空；确无外部来源时显式设置 no_external_sources=true"
        )

    references: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_references, start=1):
        if not isinstance(raw, Mapping):
            errors.append(f"references[{index}] 必须为对象")
            continue
        item = dict(raw)
        reference_id = str(item.get("reference_id", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        anchor = str(item.get("bibliography_anchor", "")).strip()
        number = item.get("number")
        if not reference_id:
            errors.append(f"references[{index}] 缺少 reference_id")
        if not title:
            errors.append(f"references[{index}] 缺少 title")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            errors.append(f"references[{index}].number 必须为正整数")
        if not BOOKMARK_NAME_RE.fullmatch(anchor):
            errors.append(f"references[{index}].bibliography_anchor 不是可解析 Word 书签名")
        item.update(
            {
                "reference_id": reference_id,
                "title": title,
                "bibliography_anchor": anchor,
                "number": number,
            }
        )
        references.append(item)

    citations: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_citations, start=1):
        if not isinstance(raw, Mapping):
            errors.append(f"citations[{index}] 必须为对象")
            continue
        item = dict(raw)
        citation_id = str(item.get("citation_id", "")).strip().upper()
        reference_id = str(item.get("reference_id", "")).strip().upper()
        claim_id = str(item.get("claim_id", "")).strip().upper()
        anchor = str(item.get("anchor", "")).strip()
        number = item.get("number")
        if not citation_id:
            errors.append(f"citations[{index}] 缺少 citation_id")
        if not reference_id:
            errors.append(f"citations[{index}] 缺少 reference_id")
        if not claim_id:
            errors.append(f"citations[{index}] 缺少 claim_id")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            errors.append(f"citations[{index}].number 必须为正整数")
        if not BOOKMARK_NAME_RE.fullmatch(anchor):
            errors.append(f"citations[{index}].anchor 不是可解析 Word 书签名")
        item.update(
            {
                "citation_id": citation_id,
                "reference_id": reference_id,
                "claim_id": claim_id,
                "anchor": anchor,
                "number": number,
            }
        )
        citations.append(item)
    return references, citations, marker_format, errors


def audit_citations(
    docx_path: str | Path,
    registry_path: str | Path,
) -> dict[str, Any]:
    """Return a deterministic citation audit report for one DOCX and registry."""

    docx = Path(docx_path)
    registry = Path(registry_path)
    findings: list[dict[str, Any]] = []
    try:
        payload = _load_registry(registry)
        references, citations, marker_format, registry_errors = _validate_registry(
            payload
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        references, citations, marker_format = [], [], "[{number}]"
        registry_errors = [str(exc)]
    findings.append(
        _finding(
            "citation.registry.schema",
            not registry_errors,
            severity="error",
            message="ReferenceRegistry/CitationMap 结构可解析",
            evidence=registry_errors,
        )
    )

    bookmarks, bookmark_issues = _extract_bookmarks(docx)
    findings.append(
        _finding(
            "citation.docx.bookmarks",
            not bookmark_issues,
            severity="error",
            message="DOCX 书签结构完整且书签名唯一",
            evidence=bookmark_issues,
        )
    )

    if registry_errors:
        return _finish_report(docx, registry, findings, references, citations)

    reference_ids = [str(item["reference_id"]) for item in references]
    citation_ids = [str(item["citation_id"]) for item in citations]
    reference_numbers = [int(item["number"]) for item in references]
    reference_anchors = [str(item["bibliography_anchor"]) for item in references]
    citation_anchors = [str(item["anchor"]) for item in citations]
    identity_issues: list[str] = []
    for label, values in (
        ("reference_id", reference_ids),
        ("citation_id", citation_ids),
        ("reference number", reference_numbers),
        ("bookmark anchor", reference_anchors + citation_anchors),
    ):
        duplicates = sorted(
            str(value) for value, count in Counter(values).items() if count > 1
        )
        if duplicates:
            identity_issues.append(f"{label} 重复：{', '.join(duplicates)}")
    expected_numbers = list(range(1, len(references) + 1))
    if sorted(reference_numbers) != expected_numbers:
        identity_issues.append(
            f"文后编号必须唯一且连续为 1..{len(references)}；实际为 {sorted(reference_numbers)}"
        )
    findings.append(
        _finding(
            "citation.registry.identities",
            not identity_issues,
            severity="error",
            message="引用、文献编号和 Word 锚点均唯一可解析",
            evidence=identity_issues,
        )
    )

    duplicate_issues: list[str] = []
    doi_groups: dict[str, list[str]] = defaultdict(list)
    title_groups: dict[str, list[str]] = defaultdict(list)
    for item in references:
        reference_id = str(item["reference_id"])
        doi = _normalized_doi(item.get("doi"))
        title = _normalized_title(item.get("title"))
        if doi:
            doi_groups[doi].append(reference_id)
        if title:
            title_groups[title].append(reference_id)
    for doi, ids in sorted(doi_groups.items()):
        if len(ids) > 1:
            duplicate_issues.append(f"DOI {doi} 重复：{', '.join(ids)}")
    for ids in sorted(title_groups.values()):
        if len(ids) > 1:
            duplicate_issues.append(f"规范化题名重复：{', '.join(ids)}")
    findings.append(
        _finding(
            "citation.registry.duplicates",
            not duplicate_issues,
            severity="error",
            message="正式参考文献不存在重复 DOI 或重复题名",
            evidence=duplicate_issues,
        )
    )

    by_reference = {str(item["reference_id"]): item for item in references}
    citation_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    link_issues: list[str] = []
    for citation in citations:
        reference_id = str(citation["reference_id"])
        reference = by_reference.get(reference_id)
        if reference is None:
            link_issues.append(
                f"{citation['citation_id']} 指向不存在的文献 {reference_id}"
            )
            continue
        citation_links[reference_id].append(citation)
        if citation["number"] != reference["number"]:
            link_issues.append(
                f"{citation['citation_id']} 编号 {citation['number']} 与 {reference_id} 编号 {reference['number']} 不一致"
            )
    for reference_id in reference_ids:
        if not citation_links.get(reference_id):
            link_issues.append(f"文后条目 {reference_id} 未被正文 CitationMap 引用")
    findings.append(
        _finding(
            "citation.registry.bidirectional",
            not link_issues,
            severity="error",
            message="正文 CitationMap 与文后 ReferenceRegistry 双向对应",
            evidence=link_issues,
        )
    )

    verification_issues: list[str] = []
    for item in references:
        reference_id = str(item["reference_id"])
        if item.get("verification_status") != "verified":
            verification_issues.append(f"{reference_id} verification_status 不是 verified")
        if item.get("adoption_status") != "adopted":
            verification_issues.append(f"{reference_id} adoption_status 不是 adopted")
        if not HASH_RE.fullmatch(str(item.get("verification_record_hash", ""))):
            verification_issues.append(f"{reference_id} 缺少有效 verification_record_hash")
    findings.append(
        _finding(
            "citation.sources.verified",
            not verification_issues,
            severity="error",
            message="所有进入正文与文后的来源均有已核验、已采用记录",
            evidence=verification_issues,
        )
    )

    docx_anchor_issues: list[str] = []
    citation_positions: list[tuple[int, str, int]] = []
    if not bookmark_issues:
        for reference in references:
            anchor = str(reference["bibliography_anchor"])
            occurrence = bookmarks.get(anchor, [])
            if len(occurrence) != 1:
                docx_anchor_issues.append(f"文后书签 {anchor} 未唯一解析")
                continue
            expected_marker = marker_format.format(number=reference["number"])
            visible_entry = _normalized_marker(occurrence[0]["text"])
            if not visible_entry.startswith(_normalized_marker(expected_marker)):
                docx_anchor_issues.append(
                    f"文后书签 {anchor} 可见编号不是 {expected_marker}"
                )
            if _normalized_title(reference["title"]) not in _normalized_title(
                occurrence[0]["text"]
            ):
                docx_anchor_issues.append(
                    f"文后书签 {anchor} 未包含注册题名 {reference['title']}"
                )
        for citation in citations:
            anchor = str(citation["anchor"])
            occurrence = bookmarks.get(anchor, [])
            if len(occurrence) != 1:
                docx_anchor_issues.append(f"正文引文书签 {anchor} 未唯一解析")
                continue
            expected_marker = marker_format.format(number=citation["number"])
            if _normalized_marker(occurrence[0]["text"]) != _normalized_marker(
                expected_marker
            ):
                docx_anchor_issues.append(
                    f"正文引文书签 {anchor} 可见编号不是 {expected_marker}"
                )
            citation_positions.append(
                (
                    int(occurrence[0]["position"]),
                    str(citation["reference_id"]),
                    int(citation["number"]),
                )
            )
    findings.append(
        _finding(
            "citation.docx.anchor_binding",
            not docx_anchor_issues,
            severity="error",
            message="注册表中的正文与文后锚点在 DOCX 中唯一存在，编号与文献题名一致",
            evidence=docx_anchor_issues,
        )
    )

    first_seen: list[tuple[str, int]] = []
    seen_references: set[str] = set()
    for _, reference_id, number in sorted(citation_positions):
        if reference_id not in seen_references:
            seen_references.add(reference_id)
            first_seen.append((reference_id, number))
    order_numbers = [number for _, number in first_seen]
    order_ok = order_numbers == sorted(order_numbers)
    findings.append(
        _finding(
            "citation.quality.first_appearance_order",
            order_ok,
            severity="warning",
            message="参考文献编号按正文首次出现顺序排列（团队默认，不是官方硬规则）",
            evidence={
                "policy": "team_default_quality_only",
                "first_seen": first_seen,
            },
        )
    )

    style = payload.get("citation_style", {})
    declared_standard = str(style.get("standard", "")).strip() if isinstance(style, Mapping) else ""
    findings.append(
        _finding(
            "citation.quality.current_standard",
            not references or declared_standard == CURRENT_REFERENCE_STANDARD,
            severity="warning",
            message="参考文献著录采用当前国家标准 GB/T 7714-2025（团队默认，不是竞赛官方硬规则）",
            evidence={
                "policy": "team_default_quality_only_not_official_rule",
                "expected": CURRENT_REFERENCE_STANDARD,
                "declared": declared_standard,
            },
        )
    )

    language_counts: Counter[str] = Counter()
    language_issues: list[str] = []
    for item in references:
        reference_id = str(item["reference_id"])
        source_language = _normalized_language(item.get("source_language"))
        bibliography_language = _normalized_language(item.get("bibliography_language"))
        foreign_reason = str(item.get("foreign_source_reason", "")).strip()
        official_chinese_title = str(item.get("official_chinese_title", "")).strip()
        language_counts[source_language or "missing"] += 1
        if not source_language:
            language_issues.append(f"{reference_id} 缺少 source_language")
            continue
        if not bibliography_language:
            language_issues.append(f"{reference_id} 缺少 bibliography_language")
        elif bibliography_language.casefold() != source_language.casefold() and not official_chinese_title:
            language_issues.append(
                f"{reference_id} 文后著录语言与来源语言不一致，且未登记可核验的官方中文题名"
            )
        if not _is_chinese_language(source_language) and not foreign_reason:
            language_issues.append(f"{reference_id} 为外文来源但未说明 foreign_source_reason")
    findings.append(
        _finding(
            "citation.quality.original_language",
            not language_issues,
            severity="warning",
            message="中文来源使用中文著录；外文原始来源保留原文题名并说明采用理由",
            evidence={
                "policy": "preserve_source_language_no_silent_title_translation",
                "issues": language_issues,
            },
        )
    )

    chinese_count = sum(
        count for language, count in language_counts.items() if _is_chinese_language(language)
    )
    findings.append(
        _finding(
            "citation.quality.chinese_source_priority",
            True,
            severity="warning",
            message="记录来源语言分布；优先中文权威检索，同时保留必要一手证据，不按比例判断质量",
            evidence={
                "policy": "team_default_quality_only_no_fixed_official_ratio",
                "chinese_references": chinese_count,
                "total_references": len(references),
                "language_counts": dict(sorted(language_counts.items())),
            },
        )
    )
    return _finish_report(docx, registry, findings, references, citations)


def _finish_report(
    docx: Path,
    registry: Path,
    findings: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    citations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    hard_failed = any(
        item.get("severity") == "error" and item.get("status") == "fail"
        for item in findings
    )
    quality_warning = any(
        item.get("severity") == "warning" and item.get("status") == "fail"
        for item in findings
    )
    return {
        "schema_version": "1.0",
        "artifact_type": "CitationAuditReport",
        "status": "NOT_READY" if hard_failed else "READY",
        "hard_gate_status": "FAIL" if hard_failed else "PASS",
        "quality_status": "WARN" if quality_warning else "PASS",
        "policy": {
            "source_of_truth": "ReferenceRegistry/CitationMap",
            "first_appearance_order": "team_default_quality_only_not_official_rule",
            "reference_standard": "GB/T_7714_2025_team_default_not_official_rule",
            "language_priority": "chinese_sources_first_preserve_original_language",
            "unregistered_bracket_numbers": "ignored",
        },
        "docx": {
            "filename": docx.name,
            "sha256": _sha256(docx) if docx.is_file() else "",
        },
        "registry": {
            "filename": registry.name,
            "sha256": _sha256(registry) if registry.is_file() else "",
        },
        "counts": {
            "references": len(references),
            "citations": len(citations),
            "reference_languages": dict(
                sorted(
                    Counter(
                        _normalized_language(item.get("source_language")) or "missing"
                        for item in references
                    ).items()
                )
            ),
        },
        "findings": list(findings),
    }




