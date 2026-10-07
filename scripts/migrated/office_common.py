# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Shared, deterministic helpers for CUMCM Word/PDF artifacts.

This module deliberately keeps artifact checks independent of Microsoft Word so
they can run on every teammate's machine and in CI.  Visual QA remains a
separate, mandatory gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "m": M_NS, "a": A_NS, "wp": WP_NS, "rel": REL_NS}

# 2026 CUMCM hard layout rules are A4 with margins of at least 25 mm.  The
# typography below is deliberately a neutral team default: the official rules
# do not prescribe fonts, sizes, spacing, or colour.
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
MIN_MARGIN_MM = 25.0
CUMCM_CONTENT_WIDTH_DXA = 9071

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/](?:[^\s<>\"']+[\\/]?)+"),
    re.compile(r"(?i)\bfile:///?[^\s<>\"']+"),
    re.compile(r"(?i)(?:^|\s)/(?:Users|home|mnt|var|tmp)/[^\s<>\"']+"),
)
IDENTITY_PATTERNS = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("mainland_mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("wechat_id", re.compile(r"(?i)\bwxid_[a-z0-9_]+\b")),
)
INTERNAL_TOKEN_PATTERNS = (
    ("codex_file_citation", re.compile(r":codex-file-citation\{[^}]+\}")),
    ("unresolved_formula_marker", re.compile(r"\[\[(?:FORMULA|OMML):[^\]]+\]\]")),
)


@dataclass(frozen=True)
class ArtifactFinding:
    check_id: str
    status: str
    severity: str
    message: str
    evidence: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()




def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()






















def extract_docx_text(path: str | Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = etree.fromstring(xml)
    paragraphs = []
    for paragraph in root.xpath(".//w:p", namespaces=NS):
        value = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
        if value:
            paragraphs.append(value)
    return "\n".join(paragraphs)


def scan_sensitive_text(text: str, *, check_identity: bool = True) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for pattern in ABSOLUTE_PATH_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(("absolute_path", match.group(0)[:160]))
    if check_identity:
        for label, pattern in IDENTITY_PATTERNS:
            for match in pattern.finditer(text):
                findings.append((label, match.group(0)[:160]))
    for label, pattern in INTERNAL_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            findings.append((label, match.group(0)[:160]))
    return findings


def docx_structural_facts(path: str | Path) -> dict[str, object]:
    artifact = Path(path)
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    with zipfile.ZipFile(artifact) as archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise ValueError(f"not a valid DOCX package: {artifact}")
        document_root = etree.fromstring(archive.read("word/document.xml"))
        formula_count = int(document_root.xpath("count(.//m:oMath)", namespaces=NS))
        bookmarks = document_root.xpath(".//w:bookmarkStart/@w:name", namespaces=NS)
        image_formula_hints: list[str] = []
        for node in document_root.xpath(".//wp:docPr", namespaces=NS):
            hint = " ".join(filter(None, (node.get("name"), node.get("title"), node.get("descr"))))
            if re.search(r"(?i)(formula|equation|math|公式|方程)", hint):
                image_formula_hints.append(hint)
        relationship_targets: list[str] = []
        for name in names:
            if name.endswith(".rels"):
                root = etree.fromstring(archive.read(name))
                relationship_targets.extend(root.xpath(".//rel:Relationship/@Target", namespaces=NS))
        media_names = sorted(name for name in names if name.startswith("word/media/"))
        comments_present = "word/comments.xml" in names
        tracked_change_count = int(
            document_root.xpath("count(.//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo)", namespaces=NS)
        )
    return {
        "filename": artifact.name,
        "sha256": sha256_file(artifact),
        "size_bytes": artifact.stat().st_size,
        "formula_count": formula_count,
        "formula_bookmarks": sorted(bookmarks),
        "image_formula_hints": image_formula_hints,
        "media_names": media_names,
        "comments_present": comments_present,
        "tracked_change_count": tracked_change_count,
        "relationship_targets": relationship_targets,
        "text": extract_docx_text(artifact),
    }


def findings_to_dict(findings: Iterable[ArtifactFinding]) -> list[dict[str, str]]:
    return [asdict(finding) for finding in findings]
