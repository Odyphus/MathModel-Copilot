"""Version-bound paper sections, delivery audits and local whitelist packages."""
from __future__ import annotations

import copy
import io
import json
import re
import zipfile
import zlib
from pathlib import Path, PurePosixPath

import copilot_domain as domain
import copilot_document_checks as documents
from copilot_packs import load_pack, build_rules_lock, verify_rules_lock
from copilot_runtime import Runtime, _put, safe_path, bind_file, file_errors, usable, requirement_status, numeric_tokens, claim_assurance
from copilot_store import digest, utc_now
from copilot_section import prepare_section
from migrated.supporting_materials import audit_supporting_zip, _safe_relative_path, FORBIDDEN_COMPONENTS


MARKER = re.compile(r"\[\[claim:([A-Za-z0-9_.:@-]+)\]\]")
ROLES = {"paper", "code", "data", "figure", "table", "instructions", "evidence", "supporting_archive"}
MANIFEST_ARCHIVE_NAME = "delivery-manifest.json"


def _delivery_path_error(reference):
    _, issue = _safe_relative_path(reference)
    if issue:
        return issue
    if {part.casefold() for part in PurePosixPath(reference).parts} & FORBIDDEN_COMPONENTS:
        return "Delivery path contains a private or temporary directory"
    if reference.casefold() == MANIFEST_ARCHIVE_NAME.casefold():
        return "Delivery path occupies the reserved package manifest name"
    return None


def audit_delivery_zip(path):
    """Check a local dossier, separately from the contest supporting archive.

    The retained supporting checker intentionally excludes the final paper;
    a dossier includes that paper and therefore uses this generic envelope.
    """
    errors, members, manifest = [], [], {}
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                errors.append("ZIP CRC failed: " + bad)
            infos = archive.infolist()
            members = [item.filename for item in infos]
            if len(members) != len({name.casefold() for name in members}):
                errors.append("Duplicate or case-colliding ZIP members")
            for item in infos:
                issue = _safe_relative_path(item.filename)[1]
                if issue or item.is_dir() or item.flag_bits & 1 or item.external_attr >> 16 & 0o170000 == 0o120000:
                    errors.append("Unsafe ZIP member: " + item.filename)
            manifest = json.loads(archive.read(MANIFEST_ARCHIVE_NAME))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != "0.1" or manifest.get("kind") != "local_delivery_dossier":
                raise ValueError("Invalid delivery manifest schema")
            records = manifest.get("files")
            if not isinstance(records, list) or not records:
                raise ValueError("ZIP manifest has no explicit file whitelist")
            expected = {}
            for record in records:
                if not isinstance(record, dict) or record.get("role") not in ROLES:
                    raise ValueError("ZIP manifest has an invalid file record")
                relative = record.get("path")
                if _delivery_path_error(relative):
                    raise ValueError("Unsafe manifest member path")
                if relative in expected:
                    errors.append("Duplicate manifest path")
                expected[relative] = record
            if set(members) != set(expected) | {MANIFEST_ARCHIVE_NAME}:
                errors.append("ZIP file set differs from the explicit whitelist")
            for relative, record in expected.items():
                data = archive.read(relative)
                if len(data) != record.get("byte_size") or domain.sha256_bytes(data) != record.get("sha256"):
                    errors.append("ZIP member bytes/hash mismatch: " + relative)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        errors.append("ZIP verification failed: " + str(exc))
    return {"passed": not errors, "errors": errors, "members": members, "manifest": manifest}


def _read(root, reference):
    return json.loads(safe_path(root, reference).read_text(encoding="utf-8"))


def _ids(cp, values, kind, root):
    if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
        return [f"{kind} IDs must be a nonempty list"]
    errors = []
    if len(set(values)) != len(values):
        errors.append(f"Duplicate {kind} IDs")
    for item in values:
        if cp["objects"].get(item, {}).get("kind") != kind or not usable(root, cp, item, verified=True):
            errors.append(f"{kind} is missing, unverified or stale: {item}")
    return errors


def _section_errors(root, cp, text, claim_ids, source_bindings=None, structure=None):
    errors = _ids(cp, claim_ids, "EvidenceMapEntry", root)
    if errors:
        return errors
    markers = set(MARKER.findall(text))
    if markers != set(claim_ids):
        errors.append("Section claim markers must exactly match the declared EvidenceMap IDs")
    # Explicit source notes and identifiers are validated before they are
    # separated from result prose. A type label never exempts arbitrary text.
    try:
        visible, _, issues = prepare_section(root, cp, text, source_bindings, structure)
        errors.extend(issues)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return errors + ["Invalid section source/structure contract: " + str(exc)]
    for paragraph in re.split(r"\n\s*\n", visible):
        prose = "\n".join(re.sub(r"^\s{0,3}#{1,6}\s+", "", line) for line in paragraph.splitlines())
        ids = MARKER.findall(prose)
        clean = MARKER.sub("", prose)
        numbers = set(numeric_tokens(clean))
        if numbers and not ids:
            errors.append("Unsupported numerical paragraph lacks an EvidenceMap marker")
        supported = set()
        for claim_id in ids:
            obj = cp["objects"].get(claim_id, {})
            claim = obj.get("payload", {}).get("claim", "")
            if claim and re.sub(r"\s+", "", claim) not in re.sub(r"\s+", "", clean):
                errors.append(f"Section does not retain the referenced claim text: {claim_id}")
            sources = [dep for dep in obj.get("dependencies", []) if cp["objects"].get(dep, {}).get("kind") == "ResultRecord"]
            assurance = claim_assurance(cp, obj.get("payload", {}), sources)
            if not assurance["verified"]:
                errors.append(f"Claim lacks checked content evidence: {claim_id}")
            supported.update(item["text"] for item in assurance["numeric_bindings"])
        if numbers - supported:
            errors.append("Unsupported numerical values in section: " + ", ".join(sorted(numbers - supported)))
    return list(dict.fromkeys(errors))


def _basis(log):
    cp = log["copilot"]
    meta = log.get("problem_meta", {})
    return {"requirements": digest(cp["requirements"]),
            "ai_usage": digest(log.get("compliance", {}).get("ai_usage")),
            "questions": log["stages"]["5"].get("qi_count"),
            "project": {key: meta.get(key) for key in ("problem_year", "rules_year", "evaluation_mode")},
            "rules_lock": digest(cp.get("rules_lock")),
            "sections": {key: obj_id for key, obj_id in cp["current"].items()
                         if cp["objects"][obj_id]["kind"] == "PaperSection"}}


def _audit_blockers(root, log):
    cp = log.get("copilot", {})
    delivery = cp.get("delivery", {})
    audit_id = delivery.get("audit_id")
    if not audit_id or not usable(root, cp, audit_id, verified=True):
        return ["No current passing delivery audit"]
    audit = cp["objects"][audit_id]["payload"]
    errors = []
    if audit.get("basis") != _basis(log):
        errors.append("Delivery audit basis changed; audit the current project again")
    errors.extend(verify_rules_lock(root, cp.get("rules_lock")))
    if not requirement_status(root, log)["complete"]:
        errors.append("Requirement Matrix is incomplete")
    return errors


def _package_errors(root, cp, package_id):
    if not package_id or not usable(root, cp, package_id, verified=True):
        return ["No current verified delivery package"]
    package = cp["objects"][package_id]["payload"]
    try:
        path = safe_path(root, package["path"])
        report = audit_delivery_zip(path)
        errors = list(report.get("errors", []))
        with zipfile.ZipFile(path) as archive:
            inner = json.loads(archive.read(MANIFEST_ARCHIVE_NAME))
        if digest(inner) != package["manifest_hash"]:
            errors.append("Package manifest changed")
        return errors
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, zlib.error) as exc:
        return [str(exc)]


def submission_status(root, log) -> dict:
    cp = log.get("copilot")
    if not cp:
        return {"ready": False, "state": "generated", "blockers": ["Copilot authority has not been initialized"]}
    delivery = cp.get("delivery", {})
    state = delivery.get("state", "generated")
    blockers = _audit_blockers(root, log)
    if state in {"frozen", "awaiting_submission", "submitted", "receipt_received"}:
        if not usable(root, cp, delivery.get("freeze_id", ""), verified=True):
            blockers.append("No current freeze bound to this audit")
    if state in {"awaiting_submission", "submitted", "receipt_received"} or delivery.get("package_id"):
        blockers.extend(_package_errors(root, cp, delivery.get("package_id")))
    if state in {"awaiting_submission", "submitted", "receipt_received"}:
        events = delivery.get("events", [])
        if not events or not usable(root, cp, events[-1], verified=True):
            blockers.append("Submission state has no current version-bound event evidence")
    audit = cp["objects"].get(delivery.get("audit_id"), {}).get("payload", {})
    formal = log.get("problem_meta", {}).get("evaluation_mode") == "formal_contest"
    if not formal:
        blockers.append("Historical/research checks are not formal submission readiness")
    blockers.extend(audit.get("formal_blockers", []))
    if state not in {"awaiting_submission", "submitted", "receipt_received"}:
        blockers.append("Package has not entered awaiting_submission")
    return {"ready": not blockers and formal and state == "awaiting_submission",
            "state": state, "blockers": list(dict.fromkeys(blockers)),
            "audit_id": delivery.get("audit_id"), "package_id": delivery.get("package_id")}


def _policy(pack):
    rules = pack["rules"]
    def value(key, default=None):
        return rules.get(key, {}).get("value", default)
    return {"profile": pack.get("document_profile", "cumcm" if pack["id"] == "cumcm" else "generic"),
            "paper_max_bytes": value("paper_max_bytes"), "supporting_max_bytes": value("support_max_bytes"),
            "body_max_pages": value("main_text_max_pages", value("solution_max_pages")),
            "anonymity_required": value("anonymity", True), "require_visual_qa": True,
            "require_a4": value("paper_size") == "A4",
            "ai_before_references": value("ai_declaration_position") == "before_references"}


def _review(root, reference, kind, files, formal=False):
    proof = _read(root, reference)
    if not isinstance(proof, dict) or proof.get("kind") != kind or proof.get("result") != "pass":
        raise ValueError(f"{kind} review lacks a structured passing record")
    if proof.get("actor_kind") not in ({"human"} if formal else {"human", "agent_evaluator"}):
        raise ValueError(f"{kind} review has no applicable reviewer kind")
    if not proof.get("reviewer") or not proof.get("reviewed_at") or not isinstance(proof.get("notes"), list) or not any(isinstance(n, str) and n.strip() for n in proof["notes"]):
        raise ValueError(f"{kind} review requires reviewer, time and inspection notes")
    given = {item.get("path"): str(item.get("sha256", "")).upper() for item in proof.get("files", []) if isinstance(item, dict)}
    if given != {item["path"]: item["sha256"] for item in files}:
        raise ValueError(f"{kind} review is not bound to the exact delivery file set")
    return bind_file(root, reference)


def _limit_error(pack, key, actual):
    rule = pack["rules"].get(key)
    if rule is None:
        return None
    limit, comparison = rule.get("value"), rule.get("comparison", "lte")
    if type(limit) is not int or limit <= 0 or comparison not in {"lt", "lte"}:
        return f"Unsupported pack limit definition: {key}"
    if type(actual) is not int or actual > limit or (actual == limit and comparison == "lt"):
        return f"Actual {key} is unknown or violates {comparison} {limit}: {actual}"
    return None


def _normalized(text):
    return re.sub(r"\s+", "", text).casefold()


def _ai_checks(root, log, pack, manifest, paper_text, page_texts):
    """Compare the retained AI ledger against actual disclosure file contents."""
    from render_ai_usage import validate_entries, render_cumcm_no_use_statement, render_cumcm_use_statement, render_mcm_markdown
    errors, files, facts = [], [], {}
    try:
        entries = validate_entries(log.get("compliance", {}).get("ai_usage"), competition=pack["id"])
        rules, disclosure_text = pack["rules"], paper_text
        for entry in entries:
            for reference in entry.evidence:
                files.append(bind_file(root, reference))
        if rules.get("ai_declaration_position", {}).get("value") == "before_references":
            official = bool(manifest.get("paper_source")) or log.get("problem_meta", {}).get("evaluation_mode") == "formal_contest"
            statement = render_cumcm_use_statement(entries, official=official) if entries else render_cumcm_no_use_statement(official=official)
            from migrated.cumcm_ai_declaration import ai_section_positions
            start, refs = ai_section_positions(paper_text)
            section_text = "\n".join(paper_text.splitlines()[start + 1:refs]) if 0 <= start < refs else ""
            if not section_text or _normalized(statement) not in _normalized(section_text):
                errors.append("AI declaration does not match the actual ledger before references")
            if entries:
                archives = [e for e in manifest.get("files", []) if e.get("role") == "supporting_archive"]
                if len(archives) != 1:
                    errors.append("AI use requires the actual supporting ZIP with its details PDF")
                    disclosure_text = ""
                else:
                    details_name = rules.get("ai_details_filename", {}).get("value")
                    with zipfile.ZipFile(safe_path(root, archives[0]["path"])) as archive:
                        candidates = [p for p in archive.namelist() if PurePosixPath(p).name == details_name]
                        if len(candidates) != 1:
                            raise ValueError("Supporting ZIP lacks a unique pack-named AI details PDF")
                        from pypdf import PdfReader
                        reader = PdfReader(io.BytesIO(archive.read(candidates[0])))
                        disclosure_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                        facts["details_pdf"] = candidates[0]
        elif rules.get("ai_report_position", {}).get("value") == "after_solution":
            if entries:
                supplied = manifest.get("ai_disclosure", {})
                pages = supplied.get("report_pages")
                last = supplied.get("solution_last_page")
                if not page_texts or type(last) is not int or last < 1 or not isinstance(pages, list) or pages != list(range(last + 1, len(page_texts) + 1)) or not pages:
                    raise ValueError("AI report requires actual trailing PDF page interval after solution_last_page")
                if "reportonuseofai" not in _normalized(page_texts[pages[0] - 1]):
                    errors.append("Declared AI report interval does not start at its actual PDF heading")
                disclosure_text = "\n".join(page_texts[p - 1] for p in pages)
                facts.update(solution_pages=last, report_pages=pages)
            elif _normalized(render_mcm_markdown([], {})) not in _normalized(paper_text):
                errors.append("No-use disclosure is absent from the final paper")
            else:
                facts["solution_pages"] = len(page_texts) or None
        elif "ai_disclosure_passed" in pack.get("required_checks", []):
            errors.append("Selected pack has no implemented AI disclosure policy; resolve the rule explicitly")
        normalized = _normalized(disclosure_text)
        for entry in entries:
            fields = [entry.tool, entry.model, entry.version, entry.purpose, entry.use_stage,
                      entry.human_review, entry.query, entry.output, entry.disclosure, entry.process_summary,
                      entry.adoption, *entry.paper_sections]
            if any(value and _normalized(value) not in normalized for value in fields):
                errors.append("AI disclosure omits or differs from the recorded tool, interaction or human review")
        facts["entries"] = len(entries)
    except (ValueError, KeyError, OSError, TypeError, AttributeError, zipfile.BadZipFile, zlib.error) as exc:
        errors.append(str(exc))
    return {"passed": not errors, "errors": errors, **facts}, files


def _rule_review(root, reference, pack, files, keys):
    bound = _review(root, reference, "rules", files, formal=True)
    proof = _read(root, reference)
    if proof.get("pack_digest") != digest(pack):
        raise ValueError("Human rule review is not bound to the locked Competition Pack")
    records = proof.get("rules", {})
    for key in keys:
        record = records.get(key, {})
        if record.get("rule_digest") != digest(pack["rules"][key]) or record.get("result") != "pass" or not record.get("notes"):
            raise ValueError("No version-bound human assessment of pack rule: " + key)
    return bound


class Delivery:
    def __init__(self, root):
        self.runtime = Runtime(root)
        self.root = self.runtime.root

    def lock_rules(self, revision, pack, problem_year, rules_year, evaluation_mode, source_snapshots, reviewer, actor="integrator"):
        if not isinstance(pack, dict):
            if isinstance(pack, str) and not Path(pack).is_absolute() and ("/" in pack or pack.endswith(".json")):
                pack = str(safe_path(self.root, pack))
            pack = load_pack(pack)
        def change(log):
            lock = build_rules_lock(pack, problem_year, rules_year, evaluation_mode, source_snapshots, reviewer, self.root)
            meta = log["problem_meta"]
            for key, value in (("problem_year", problem_year), ("rules_year", rules_year), ("evaluation_mode", evaluation_mode)):
                if meta.get(key) not in (None, value):
                    raise ValueError(f"Rules lock conflicts with project {key}")
                meta[key] = value
            files = [bind_file(self.root, item["path"]) for item in lock["source_snapshots"]]
            oid = _put(log, "RulesLock", "rules.lock", lock, files=files, status="verified")
            log["copilot"]["rules_lock"] = lock
            return {"rules_lock_id": oid, "record_hash": lock["record_hash"]}
        return self.runtime._tx(revision, actor, "Lock selected rules snapshots", change)

    def section(self, revision, key, path, claim_ids, actor="writer", *, source_bindings=None, structure=None):
        def change(log):
            target = safe_path(self.root, path)
            if target.suffix.lower() not in {".md", ".txt"}:
                raise ValueError("PaperSection source must be Markdown or plain text")
            text = target.read_text(encoding="utf-8")
            errors = _section_errors(self.root, log["copilot"], text, claim_ids, source_bindings, structure)
            if errors:
                raise ValueError("; ".join(errors))
            _, source_ids, _ = prepare_section(self.root, log["copilot"], text, source_bindings, structure)
            payload = {"path": path, "claim_ids": claim_ids, "marker_protocol": "[[claim:versioned-object-id]]"}
            if source_bindings is not None or structure is not None:
                payload.update(source_bindings=source_bindings or [], structure=structure or [], source_protocol="0.1")
            oid = _put(log, "PaperSection", key, payload, list(dict.fromkeys(claim_ids + source_ids)), [bind_file(self.root, path)], "verified")
            log["copilot"]["delivery"]["state"] = "generated"
            return {"section_id": oid}
        return self.runtime._tx(revision, actor, "Register evidence-bound paper section", change)

    def audit(self, revision, manifest, actor="qa"):
        def change(log):
            cp = log["copilot"]
            errors, formal_blockers, reports, inputs = [], [], {}, []
            payload, files, deps = {}, [], []
            try:
                payload = copy.deepcopy(_read(self.root, manifest) if isinstance(manifest, str) else manifest)
                if not isinstance(payload, dict):
                    raise ValueError("Delivery manifest must be an object")
                if isinstance(manifest, str):
                    inputs.append(bind_file(self.root, manifest))
                lock = cp.get("rules_lock")
                lock_errors = verify_rules_lock(self.root, lock)
                errors.extend(lock_errors)
                if not isinstance(lock, dict) or not isinstance(lock.get("pack"), dict):
                    raise ValueError("A current rules lock is required")
                for key in ("problem_year", "rules_year", "evaluation_mode"):
                    if lock.get(key) != log["problem_meta"].get(key):
                        errors.append(f"Project and rules lock disagree on {key}")
                pack, policy = lock["pack"], _policy(lock["pack"])
                formal = lock["evaluation_mode"] == "formal_contest"
                coverage = requirement_status(self.root, log)
                reports["requirements"] = coverage
                if not coverage["complete"]:
                    errors.append("Requirement Matrix has missing/unverified questions or outputs")
                sections, claims = payload.get("sections"), payload.get("claims")
                errors.extend(_ids(cp, sections, "PaperSection", self.root))
                errors.extend(_ids(cp, claims, "EvidenceMapEntry", self.root))
                sections = sections if isinstance(sections, list) else []
                claims = claims if isinstance(claims, list) else []
                deps = [item for item in sections + claims if isinstance(item, str) and item in cp["objects"]]
                rule_id = cp["current"].get("rules.lock")
                if rule_id:
                    deps.append(rule_id)
                current_sections = set(_basis(log)["sections"].values())
                if set(sections) != current_sections:
                    errors.append("Manifest must include every current PaperSection")
                section_claims = set()
                for oid in sections:
                    obj = cp["objects"].get(oid, {})
                    info = obj.get("payload", {})
                    if obj.get("kind") == "PaperSection":
                        section_claims.update(info["claim_ids"])
                        errors.extend(_section_errors(self.root, cp, safe_path(self.root, info["path"]).read_text(encoding="utf-8"), info["claim_ids"], info.get("source_bindings"), info.get("structure")))
                if section_claims != set(claims):
                    errors.append("Delivery claim set must exactly match its sections")
                covered = {req for oid in claims for req in cp["objects"].get(oid, {}).get("payload", {}).get("requirement_ids", [])}
                required = {key for key, req in cp["requirements"].items() if req.get("active", True)}
                if not required <= covered:
                    errors.append("Paper claims do not cover all active requirements")
                entries = payload.get("files")
                if not isinstance(entries, list) or not entries:
                    raise ValueError("Manifest requires an explicit file whitelist")
                seen, papers = set(), []
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("role") not in ROLES:
                        raise ValueError("Each delivery file requires a supported role")
                    path = entry.get("path")
                    kind = "run_instructions" if entry["role"] == "instructions" else entry["role"] if entry["role"] in {"code", "data", "figure", "table", "evidence"} else "other"
                    target = safe_path(self.root, path)
                    issue = _delivery_path_error(path)
                    if issue:
                        raise ValueError(issue)
                    if path.casefold() in seen or path == MANIFEST_ARCHIVE_NAME:
                        raise ValueError("Duplicate, case-colliding or reserved delivery filename")
                    seen.add(path.casefold())
                    bound = bind_file(self.root, path)
                    files.append({**bound, "role": entry["role"], "kind": kind})
                    if entry["role"] == "paper":
                        papers.append(entry)
                    if entry["role"] == "supporting_archive":
                        support_formats = pack["rules"].get("support_formats", {}).get("value")
                        if support_formats is not None and target.suffix.lower().lstrip(".") not in support_formats:
                            errors.append("Supporting archive format is not allowed by the pack")
                        issue = _limit_error(pack, "support_max_bytes", bound["byte_size"])
                        if issue:
                            errors.append(issue)
                        reports[path] = audit_supporting_zip(target, max_zip_bytes=policy.get("supporting_max_bytes"))
                        if not reports[path]["passed"]:
                            errors.extend(reports[path]["errors"])
                if len(papers) != 1:
                    raise ValueError("Manifest must select exactly one final paper")
                inputs.extend({k: item[k] for k in ("path", "sha256", "byte_size")} for item in files)
                paper = papers[0]
                path = safe_path(self.root, paper["path"])
                issue = _limit_error(pack, "paper_max_bytes", path.stat().st_size)
                if issue:
                    errors.append(issue)
                formats = pack["rules"].get("paper_formats", {}).get("value", ["docx", "pdf"])
                if path.suffix.lstrip(".").lower() not in formats:
                    errors.append("Paper format is not allowed by the selected pack")
                extra = {}
                for key in ("metadata_path", "visual_qa_path", "source_docx", "rendered_pdf", "render_receipt", "render_metadata_path", "render_visual_qa_path"):
                    if paper.get(key):
                        extra[key] = safe_path(self.root, paper[key])
                        inputs.append(bind_file(self.root, paper[key]))
                if "metadata_path" not in extra:
                    errors.append("Explicit version-bound paper metadata_path is required")
                source_contract = payload.get("paper_source")
                document_file_refs = ()
                typed_sections = any(cp["objects"].get(oid, {}).get("payload", {}).get("source_protocol") for oid in sections)
                displayed_claims = any(cp["objects"].get(oid, {}).get("payload", {}).get("display_contracts") for oid in claims)
                if source_contract is not None:
                    from copilot_paper_source import audit_paper_source
                    if isinstance(source_contract, str):
                        inputs.append(bind_file(self.root, source_contract))
                        source_contract = _read(self.root, source_contract)
                    docx_path = paper["path"] if path.suffix.lower() == ".docx" else paper.get("source_docx")
                    if not docx_path:
                        raise ValueError("Paper-source audit requires the actual DOCX source")
                    source_report = audit_paper_source(self.root, cp, sections, docx_path, source_contract)
                    reports["paper_source"] = source_report
                    inputs.extend(source_report.get("files", []))
                    deps.extend(source_report.get("dependencies", []))
                    if not source_report.get("passed"):
                        errors.extend(source_report.get("errors") or ["Paper-source projection failed"])
                    else:
                        document_file_refs = tuple(item["path"] for item in source_report["files"])
                elif typed_sections or displayed_claims:
                    errors.append("Typed-source/display sections require a paper_source projection contract")
                page_texts = []
                if path.suffix.lower() == ".docx":
                    report = documents.audit_docx(path, policy=policy, metadata_path=extra.get("metadata_path"),
                        visual_qa_path=extra.get("visual_qa_path"), evaluation_mode=lock["evaluation_mode"],
                        file_reference_paths=document_file_refs)
                    from migrated.office_common import docx_structural_facts
                    paper_text = docx_structural_facts(path)["text"]
                elif path.suffix.lower() == ".pdf":
                    report = documents.audit_pdf(path, policy=policy, source_docx=extra.get("source_docx"),
                        metadata_path=extra.get("metadata_path"), visual_qa_path=extra.get("visual_qa_path"))
                    from pypdf import PdfReader
                    page_texts = [page.extract_text() or "" for page in PdfReader(path).pages]
                    paper_text = "\n".join(page_texts)
                else:
                    raise ValueError("No executed document checker for the selected paper format")
                reports["paper"] = report
                if not report.get("passed"):
                    failed = [item.get("check_id", "document") for item in report.get("findings", []) if item.get("status") != "pass" and item.get("severity") == "error"]
                    errors.extend(report.get("errors", []) or ["Paper checker failed: " + ", ".join(failed)])
                for oid in claims:
                    claim = cp["objects"].get(oid, {}).get("payload", {}).get("claim", "")
                    if claim and re.sub(r"\s+", "", claim) not in re.sub(r"\s+", "", paper_text):
                        errors.append(f"Final paper omits evidence-bound claim: {oid}")
                if "visual_qa_path" not in extra:
                    errors.append("Visual QA evidence is missing")
                else:
                    visual = json.loads(extra["visual_qa_path"].read_text(encoding="utf-8"))
                    if not visual.get("reviewer") or not visual.get("notes") or visual.get("actor_kind") not in {"human", "agent_evaluator"}:
                        errors.append("Visual QA lacks reviewer identity/type and inspection notes")
                    if visual.get("actor_kind") != "human":
                        formal_blockers.append("Formal visual review requires a human reviewer")
                    rendered = visual.get("rendered_pages", [])
                    if not rendered or {row.get("page") for row in rendered} != set(visual.get("inspected_pages", [])):
                        errors.append("Visual QA lacks actual rendered files for every inspected page")
                    for row in rendered:
                        bound = bind_file(self.root, row["path"])
                        if bound["sha256"] != str(row.get("sha256", "")).upper():
                            errors.append("Rendered page hash changed")
                        from PIL import Image
                        with Image.open(safe_path(self.root, row["path"])) as page_image:
                            page_image.verify()
                        inputs.append(bound)
                reviews = payload.get("reviews", [])
                for kind in ("anonymity", "content"):
                    selected = [r for r in reviews if isinstance(r, dict) and r.get("kind") == kind]
                    if len(selected) != 1:
                        errors.append(f"Missing unique version-bound {kind} review")
                    else:
                        inputs.append(_review(self.root, selected[0]["path"], kind, files, formal))
                archives = [e for e in entries if e["role"] == "supporting_archive"]
                separate_support = pack["rules"].get("separate_support_archive", {}).get("value")
                if separate_support is True and (len(archives) != 1 or not payload.get("supporting_manifest")):
                    errors.append("Selected pack requires one actual supporting archive and its manifest")
                if payload.get("supporting_manifest"):
                    reference = payload["supporting_manifest"]
                    target = safe_path(self.root, reference)
                    inputs.append(bind_file(self.root, reference))
                    if len(archives) > 1:
                        raise ValueError("A supporting manifest can select only one supporting archive")
                    reports["supporting"] = documents.audit_supporting_materials(self.root, target, policy=policy,
                        zip_path=safe_path(self.root, archives[0]["path"]) if archives else None,
                        docx_path=(path if path.suffix.lower() == ".docx" else extra.get("source_docx")) if policy["profile"] == "cumcm" else None)
                    if not reports["supporting"]["passed"]:
                        errors.append("Supporting-materials manifest failed the migrated audit")
                elif pack["rules"].get("separate_support_archive", {}).get("value") is not False and any(e["role"] != "paper" for e in entries):
                    errors.append("Supporting files require a checked supporting_manifest")
                if payload.get("citation_registry"):
                    target = safe_path(self.root, payload["citation_registry"])
                    inputs.append(bind_file(self.root, payload["citation_registry"]))
                    citation_docx = path if path.suffix.lower() == ".docx" else extra.get("source_docx")
                    if not citation_docx:
                        formal_blockers.append("Citation checker requires the editable DOCX master")
                    else:
                        reports["citations"] = documents.audit_citations(citation_docx, target)
                        if not reports["citations"].get("passed"):
                            errors.append("Reference registry/citation audit failed")
                elif payload.get("reference_applicability"):
                    reference = payload["reference_applicability"]
                    inputs.append(_review(self.root, reference, "references_not_applicable", files, formal))
                    proof = _read(self.root, reference)
                    if not proof.get("reason"):
                        errors.append("Reference applicability needs an inspected-content reason")
                else:
                    formal_blockers.append("References need a checked registry or a version-bound not-applicable review")
                if "render_receipt" not in extra:
                    formal_blockers.append("No actual Word/TeX render receipt bound to the final paper")
                else:
                    receipt = json.loads(extra["render_receipt"].read_text(encoding="utf-8"))
                    rendered_pdf = extra.get("rendered_pdf", path if path.suffix.lower() == ".pdf" else None)
                    if type(receipt.get("exit_code")) is not int or receipt.get("exit_code") != 0 or not isinstance(receipt.get("command"), list) or not receipt["command"] or not receipt.get("renderer") or not rendered_pdf:
                        formal_blockers.append("Render receipt does not establish a completed render")
                    else:
                        receipt_files = receipt.get("files", [])
                        if file_errors(self.root, receipt_files) or not {paper["path"], rendered_pdf.relative_to(self.root).as_posix()} <= {f.get("path") for f in receipt_files}:
                            formal_blockers.append("Render receipt is not bound to the current source/PDF")
                        if not receipt.get("log_path") or not receipt.get("log_sha256"):
                            formal_blockers.append("Render execution log is missing")
                        else:
                            bound = bind_file(self.root, receipt["log_path"])
                            if bound["sha256"] != str(receipt["log_sha256"]).upper():
                                formal_blockers.append("Render execution log hash changed")
                            inputs.append(bound)
                        if path.suffix.lower() == ".docx":
                            if not extra.get("render_metadata_path") or not extra.get("render_visual_qa_path"):
                                formal_blockers.append("DOCX rendering needs the actual PDF metadata and visual QA evidence")
                            else:
                                reports["rendered_pdf"] = documents.audit_pdf(rendered_pdf, policy=policy, source_docx=path,
                                    metadata_path=extra["render_metadata_path"], visual_qa_path=extra["render_visual_qa_path"])
                                if not reports["rendered_pdf"].get("passed"):
                                    formal_blockers.append("Actual DOCX-derived PDF has not passed the migrated PDF audit")
                                from pypdf import PdfReader
                                page_texts = [page.extract_text() or "" for page in PdfReader(rendered_pdf).pages]
                ai_report, ai_files = _ai_checks(self.root, log, pack, payload, paper_text, page_texts)
                reports["ai_disclosure"] = ai_report
                inputs.extend(ai_files)
                if not ai_report["passed"]:
                    if "ai_disclosure_passed" in pack.get("required_checks", []):
                        errors.extend(ai_report["errors"])
                    else:
                        formal_blockers.extend(ai_report["errors"])
                page_report = reports.get("rendered_pdf", report)
                page_errors = []
                if "main_text_max_pages" in pack["rules"]:
                    count = page_report.get("segments", {}).get("body_pages") if policy["profile"] == "cumcm" else page_report.get("page_count")
                    issue = _limit_error(pack, "main_text_max_pages", count)
                    if issue:
                        page_errors.append(issue)
                if "solution_max_pages" in pack["rules"]:
                    count = page_report.get("page_count")
                    if pack["rules"].get("ai_report_counted_in_page_limit", {}).get("value") is False:
                        count = ai_report.get("solution_pages", count)
                    issue = _limit_error(pack, "solution_max_pages", count)
                    if issue:
                        page_errors.append(issue)
                errors.extend(page_errors)
                supported = {
                    "rules_verified": not lock_errors,
                    "anonymity_passed": any(f.get("check_id", "").endswith(".privacy") and f.get("status") == "pass" for f in report.get("findings", [])) and policy["anonymity_required"],
                    "page_limit_passed": not page_errors and any(k in pack["rules"] for k in ("main_text_max_pages", "solution_max_pages")),
                    "ai_disclosure_passed": ai_report["passed"],
                    "supporting_materials_passed": reports.get("supporting", {}).get("passed", False) or (separate_support is False and not archives),
                }
                reports["required_checks"] = {key: {"status": "pass" if supported.get(key) else "fail", "executed": key in supported} for key in pack.get("required_checks", [])}
                for key in pack.get("required_checks", []):
                    if key not in supported:
                        errors.append("Required pack check has no implemented evaluator: " + key)
                    elif not supported[key]:
                        errors.append("Required pack check did not pass: " + key)
                automated_rules = {"paper_formats", "paper_max_bytes", "support_max_bytes", "support_formats", "main_text_max_pages", "solution_max_pages",
                    "anonymity", "ai_declaration_position", "ai_details_filename", "ai_report_position", "ai_report_counted_in_page_limit", "separate_support_archive"}
                if policy["profile"] == "cumcm":
                    automated_rules.update({"first_page", "table_of_contents"})
                manual_rules = [key for key, rule in pack["rules"].items() if rule.get("origin") == "official_rule" and key not in automated_rules]
                if manual_rules:
                    if payload.get("rule_review"):
                        inputs.append(_rule_review(self.root, payload["rule_review"], pack, files, manual_rules))
                    else:
                        formal_blockers.append("No automatic evaluator or bound human rule review for: " + ", ".join(manual_rules))
                if formal:
                    errors.extend(formal_blockers)
                errors.extend(file_errors(self.root, inputs))
            except (ValueError, OSError, KeyError, TypeError, AttributeError, ImportError, zipfile.BadZipFile, zlib.error) as exc:
                errors.append(str(exc))
            passed = not errors
            result = {"passed": passed, "errors": list(dict.fromkeys(errors)), "formal_blockers": list(dict.fromkeys(formal_blockers)),
                      "reports": reports, "manifest": payload, "files": files, "basis": _basis(log), "audited_at": utc_now()}
            oid = _put(log, "DeliveryAudit", "delivery.audit", result, sorted(set(deps)), inputs,
                       "verified" if passed else "failed")
            cp["delivery"].update(state="checked" if passed else "generated", audit_id=oid, freeze_id=None, package_id=None)
            return {"audit_id": oid, **result}
        return self.runtime._tx(revision, actor, "Audit current paper and delivery evidence", change)

    def freeze(self, revision, actor="integrator"):
        def change(log):
            errors = _audit_blockers(self.root, log)
            if errors:
                raise ValueError("; ".join(errors))
            cp, delivery = log["copilot"], log["copilot"]["delivery"]
            oid = _put(log, "DeliveryFreeze", "delivery.freeze", {"audit_id": delivery["audit_id"], "basis": _basis(log), "frozen_at": utc_now()},
                       [delivery["audit_id"]], status="verified")
            delivery.update(state="frozen", freeze_id=oid, package_id=None)
            return {"freeze_id": oid, "state": "frozen"}
        return self.runtime._tx(revision, actor, "Freeze the current checked delivery", change)

    def package(self, revision, relative_path, actor="integrator"):
        def change(log):
            cp, delivery = log["copilot"], log["copilot"]["delivery"]
            errors = _audit_blockers(self.root, log)
            if not usable(self.root, cp, delivery.get("freeze_id", ""), verified=True):
                errors.append("Freeze the current audit before packaging")
            if errors:
                raise ValueError("; ".join(errors))
            target = safe_path(self.root, relative_path, exists=False)
            if target.suffix.lower() != ".zip" or target.exists():
                raise ValueError("Package requires a new .zip path; existing assets are not overwritten")
            if _delivery_path_error(relative_path):
                raise ValueError("Package output path is reserved or unsafe")
            audit = cp["objects"][delivery["audit_id"]]["payload"]
            entries = [{"path": item["path"], "kind": item["kind"], "role": item["role"],
                        "sha256": item["sha256"], "byte_size": item["byte_size"]}
                       for item in audit["files"]]
            inner = {"schema_version": "0.1", "kind": "local_delivery_dossier", "purpose": "local delivery dossier; not an upload receipt",
                     "files": entries, "audit_id": delivery["audit_id"], "freeze_id": delivery["freeze_id"]}
            target.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                archive = zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED)
                created = True
                with archive:
                    archive.writestr(MANIFEST_ARCHIVE_NAME, json.dumps(inner, ensure_ascii=False, indent=2))
                    for entry in entries:
                        data = safe_path(self.root, entry["path"]).read_bytes()
                        if domain.sha256_bytes(data) != entry["sha256"]:
                            raise ValueError("Input changed during packaging")
                        archive.writestr(entry["path"], data)
                checked = audit_delivery_zip(target)
                if not checked["passed"]:
                    raise ValueError("; ".join(checked["errors"]))
            except Exception:
                if created:
                    target.unlink(missing_ok=True)  # Only this newly-created package.
                raise
            oid = _put(log, "DeliveryPackage", "delivery.package", {"path": relative_path,
                "manifest_hash": digest(inner), "crc_checked": True, "members": checked["members"]},
                [delivery["freeze_id"]], [bind_file(self.root, relative_path)], "verified")
            delivery.update(package_id=oid, state="frozen")
            return {"package_id": oid, "path": relative_path, "sha256": domain.sha256_file(target), "state": "frozen"}
        return self.runtime._tx(revision, actor, "Build and verify local whitelist delivery ZIP", change)

    def event(self, revision, state, evidence_path=None, actor_kind="human", actor="integrator"):
        def change(log):
            cp, delivery = log["copilot"], log["copilot"]["delivery"]
            errors = _audit_blockers(self.root, log) + _package_errors(self.root, cp, delivery.get("package_id"))
            audit = cp["objects"].get(delivery.get("audit_id"), {}).get("payload", {})
            errors.extend(audit.get("formal_blockers", []))
            if log["problem_meta"].get("evaluation_mode") != "formal_contest":
                errors.append("Historical/research projects cannot enter formal submission states")
            previous = delivery.get("state", "generated")
            if previous in {"awaiting_submission", "submitted"}:
                prior_id = (delivery.get("events") or [None])[-1]
                prior = cp["objects"].get(prior_id, {})
                if (prior.get("kind") != "DeliveryEvent" or prior.get("payload", {}).get("state") != previous
                        or not usable(self.root, cp, prior_id, verified=True)):
                    errors.append("Previous delivery event is missing, mismatched or no longer valid")
            allowed = {"frozen": "awaiting_submission", "awaiting_submission": "submitted", "submitted": "receipt_received"}
            if allowed.get(previous) != state:
                errors.append(f"Invalid delivery transition {previous} -> {state}")
            if errors:
                raise ValueError("; ".join(errors))
            files = []
            evidence = None
            if state in {"submitted", "receipt_received"}:
                if actor_kind != "human" or not evidence_path:
                    raise ValueError("External submission/receipt events require an explicit human evidence record")
                evidence = _read(self.root, evidence_path)
                package = cp["objects"][delivery["package_id"]]["files"][0]
                if not isinstance(evidence, dict) or evidence.get("state") != state or str(evidence.get("package_sha256", "")).upper() != package["sha256"] or not evidence.get("external_reference") or not evidence.get("recorded_at"):
                    raise ValueError("External evidence does not identify this package and submission event")
                receipt = bind_file(self.root, evidence.get("receipt_path"))
                if receipt["sha256"] != str(evidence.get("receipt_sha256", "")).upper():
                    raise ValueError("External receipt bytes do not match the recorded hash")
                files = [bind_file(self.root, evidence_path), receipt]
            record = {"state": state, "previous": previous, "actor_kind": actor_kind, "actor": actor,
                      "recorded_at": utc_now(), "evidence": evidence, "files": files}
            events = delivery.setdefault("events", [])
            deps = [delivery["package_id"]] + ([events[-1]] if previous in {"awaiting_submission", "submitted"} and events else [])
            event_id = _put(log, "DeliveryEvent", "delivery.event." + str(len(events) + 1), record, deps, files, "verified")
            delivery.setdefault("events", []).append(event_id)
            delivery["state"] = state
            return {"event_id": event_id, "state": state, "performed_upload": False}
        return self.runtime._tx(revision, actor, "Record explicit delivery state evidence", change)
