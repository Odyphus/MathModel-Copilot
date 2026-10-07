"""Read-only competition-selected adapters for migrated document checks.

No function writes workflow state, generates a review, or records a signoff.
The caller supplies the selected Competition Pack policy and registers results
through the sole Store. Optional Office dependencies are loaded only on use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import zipfile

from copilot_domain import sha256_file


def _policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(policy, Mapping):
        raise ValueError("A Competition Pack document policy is required")
    value = dict(policy)
    profile = value.get("profile", "generic")
    if profile not in {"generic", "cumcm"}:
        raise ValueError(f"Unsupported document checker profile: {profile}")
    for key in ("paper_max_bytes", "supporting_max_bytes", "body_max_pages"):
        limit = value.get(key)
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError(f"{key} must be a positive integer or null")
    for key in ("anonymity_required", "require_visual_qa", "require_a4", "ai_before_references"):
        if key in value and not isinstance(value[key], bool):
            raise ValueError(f"{key} must be boolean")
    if profile != "cumcm" and value.get("ai_before_references"):
        raise ValueError("The official AI declaration checker requires a CUMCM document profile")
    return value


def _unavailable(check: str, exc: Exception) -> dict[str, Any]:
    return {"passed": False, "status": "not_executed", "checker": check,
            "errors": [f"Optional checker dependency unavailable: {exc}"]}


def _finish(report: Mapping[str, Any], path: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    errors = list(result.get("errors", []))
    limit = policy.get("paper_max_bytes")
    if limit is not None and path.stat().st_size > limit:
        errors.append(f"Document exceeds pack byte limit: {path.stat().st_size} > {limit}")
    result.update({"passed": bool(result.get("passed")) and not errors,
                   "errors": errors, "sha256": sha256_file(path),
                   "byte_size": path.stat().st_size, "policy": dict(policy)})
    result["status"] = "pass" if result["passed"] else "fail"
    return result


def audit_docx(
    path: str | Path, *, policy: Mapping[str, Any],
    expected_formula_ids: tuple[str, ...] = (), metadata_path: str | Path | None = None,
    visual_qa_path: str | Path | None = None, evaluation_mode: str = "formal_contest",
    file_reference_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Audit OOXML and bound metadata; CUMCM layout runs only when selected."""
    config = _policy(policy)
    try:
        from migrated.docx_audit import audit_docx as migrated_audit
    except ImportError as exc:
        return _unavailable("docx", exc)
    report = migrated_audit(
        path, expected_formula_ids=expected_formula_ids, metadata_path=metadata_path,
        final_mode=True, require_ai_before_references=config.get("ai_before_references", False),
        check_identity=config.get("anonymity_required", False),
        require_visual_qa=config.get("require_visual_qa", True),
        visual_qa_path=visual_qa_path,
        artifact_kind="paper" if config.get("profile") == "cumcm" else "supporting",
        evaluation_mode=evaluation_mode,
        file_reference_paths=file_reference_paths,
    )
    return _finish(report, Path(path), config)


def audit_pdf(
    path: str | Path, *, policy: Mapping[str, Any], source_docx: str | Path | None = None,
    metadata_path: str | Path | None = None, visual_qa_path: str | Path | None = None,
) -> dict[str, Any]:
    """Audit an actual DOCX-derived PDF, retaining source/hash/visual checks.

    The retained checker verifies the Word derivative path. TeX compilation is
    supplied by the inherited render_paper tool and is not certified here.
    """
    config = _policy(policy)
    if config.get("profile") == "cumcm" and config.get("body_max_pages") is None:
        raise ValueError("CUMCM document profile requires the locked body_max_pages")
    try:
        from migrated.pdf_audit import audit_pdf as migrated_audit
    except ImportError as exc:
        return _unavailable("pdf", exc)
    report = migrated_audit(
        path, source_docx=source_docx, metadata_path=metadata_path,
        visual_qa_path=visual_qa_path, require_visual_qa=config.get("require_visual_qa", True),
        body_max_pages=config.get("body_max_pages") or 1,
        artifact_kind="paper" if config.get("profile") == "cumcm" else "supporting",
        require_a4=config.get("require_a4", False),
        check_identity=config.get("anonymity_required", False),
    )
    return _finish(report, Path(path), config)


def audit_citations(docx_path: str | Path, registry_path: str | Path) -> dict[str, Any]:
    """Reuse the original bidirectional ReferenceRegistry/CitationMap check."""
    from migrated.citation_audit import audit_citations as migrated_audit
    result = migrated_audit(docx_path, registry_path)
    result["migrated_status"] = result.get("status")
    # The retained checker uses PASS/READY, not the other adapters' passed flag.
    # Keep the original verdict and fail closed for incomplete/contradictory reports.
    result["passed"] = (
        result.get("hard_gate_status") == "PASS" and result.get("status") == "READY"
        and isinstance(result.get("findings"), list) and bool(result["findings"])
        and all(item.get("status") == "pass" for item in result["findings"]
                if item.get("severity") == "error")
    )
    result["status"] = "pass" if result["passed"] else "fail"
    return result


def audit_supporting_materials(
    project_root: str | Path, manifest_path: str | Path, *, policy: Mapping[str, Any],
    zip_path: str | Path | None = None, docx_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify whitelist, actual bytes/CRC, and optionally CUMCM appendix code."""
    config = _policy(policy)
    from migrated.supporting_materials import validate_manifest, audit_supporting_zip, audit_docx_appendix
    checks = {"manifest": validate_manifest(
        manifest_path, project_root,
        no_program_statement=config.get("no_program_statement"),
        no_supporting_statement=config.get("no_supporting_statement"),
        check_identity=config.get("anonymity_required", False),
    )}
    if zip_path is not None:
        checks["zip"] = audit_supporting_zip(zip_path, max_zip_bytes=config.get("supporting_max_bytes"))
        if checks["zip"].get("passed"):
            # Independently valid internal and external manifests may still
            # describe different snapshots. Bind this audit to the selected one.
            from migrated.supporting_materials import load_manifest, _load_text_payload, MANIFEST_ARCHIVE_NAME
            with zipfile.ZipFile(zip_path) as archive:
                inner = _load_text_payload(archive.read(MANIFEST_ARCHIVE_NAME).decode("utf-8-sig"))
            if inner != load_manifest(manifest_path):
                checks["zip"]["passed"] = False
                checks["zip"].setdefault("errors", []).append("ZIP manifest differs from the current selected manifest")
    if docx_path is not None:
        if config.get("profile") != "cumcm":
            checks["appendix"] = {"passed": False, "status": "not_executed",
                                  "errors": ["The full-source appendix checker requires the CUMCM profile"]}
        else:
            checks["appendix"] = audit_docx_appendix(docx_path, manifest_path, project_root)
    passed = all(check.get("passed") for check in checks.values())
    return {"passed": passed, "status": "pass" if passed else "fail", "checks": checks,
            "policy": config, "manifest_sha256": sha256_file(Path(manifest_path))}
