"""Competition metadata and file-bound rules locks, independent of state storage.

Limits live in pack.json. A rules lock proves the consistency of local snapshots,
their declared source/year and a reviewer record; it is not official acceptance
or an automatic judgment that a human has correctly interpreted every rule.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from copilot_domain import canonical_json, seal_record, sha256_bytes, sha256_file, verify_sealed_record


PACK_ROOT = Path(__file__).resolve().parents[1] / "competitions"
MODES = {"formal_contest", "historical_benchmark", "open_research"}
ORIGINS = {"official_rule", "maintainer_default", "team_default", "empirical_observation"}
LOAD_META = {"_pack_path", "_pack_file_sha256", "_resource_hashes"}
HASH = re.compile(r"[0-9A-Fa-f]{64}\Z")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*\Z")


def _year(value):
    return type(value) is int and 1900 <= value <= 2200


def _url(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _relative(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    return not path.is_absolute() and not windows.is_absolute() and not windows.drive and ".." not in path.parts and path.parts != () and str(path) != "."


def _timestamp(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date() <= datetime.now(timezone.utc).date()
    except ValueError:
        try:
            return date.fromisoformat(value) <= datetime.now(timezone.utc).date()
        except ValueError:
            return False


def _payload(pack):
    return {key: copy.deepcopy(value) for key, value in pack.items() if key not in LOAD_META}


def _json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"Duplicate JSON key: {key}")
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant)


def validate_pack(pack) -> list[str]:
    errors = []
    if not isinstance(pack, dict):
        return ["Pack must be an object"]
    if pack.get("schema_version") != "0.1":
        errors.append("Unsupported pack schema_version")
    if not isinstance(pack.get("id"), str) or not IDENTIFIER.fullmatch(pack["id"]):
        errors.append("Pack id must be a stable lowercase identifier")
    for key in ("name", "version"):
        if not isinstance(pack.get(key), str) or not pack[key].strip():
            errors.append(f"Pack {key} must be nonempty")
    aliases = pack.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(x, str) or not IDENTIFIER.fullmatch(x) for x in aliases):
        errors.append("Pack aliases must be lowercase identifier strings")
    if pack.get("rules_year") is not None and not _year(pack["rules_year"]):
        errors.append("Pack rules_year must be a valid year or null")
    if not isinstance(pack.get("rules_status"), str) or pack["rules_status"] not in {"baseline", "unverified"}:
        errors.append("Pack rules_status must be baseline or unverified")
    sources = pack.get("official_sources")
    source_ids = set()
    source_urls = set()
    if not isinstance(sources, list):
        errors.append("official_sources must be an array")
        sources = []
    for source in sources:
        if not isinstance(source, dict):
            errors.append("Each official source must be an object")
            continue
        identifier = source.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in source_ids:
            errors.append("Official source IDs must be unique identifiers")
        else:
            source_ids.add(identifier)
        if not _url(source.get("url")) or source.get("url") in source_urls:
            errors.append("Official source URLs must be unique HTTP(S) URLs")
        else:
            source_urls.add(source["url"])
        if source.get("origin") != "official_rule":
            errors.append("official_sources entries must be marked official_rule")
        if source.get("rules_year") != pack.get("rules_year") or not _year(source.get("rules_year")):
            errors.append("Official source rules_year must match the pack")
        if type(source.get("required_for_lock")) is not bool:
            errors.append("Each official source must declare required_for_lock")
        if source.get("checked_at") is not None and not _timestamp(source["checked_at"]):
            errors.append("Official source checked_at must be a nonfuture ISO date/time or null")
    rules = pack.get("rules")
    if not isinstance(rules, dict):
        errors.append("rules must be an object")
        rules = {}
    for name, rule in rules.items():
        if not isinstance(rule, dict) or "value" not in rule:
            errors.append(f"Rule {name} requires a value and provenance")
            continue
        if not isinstance(rule.get("origin"), str) or rule["origin"] not in ORIGINS:
            errors.append(f"Rule {name} has an invalid origin")
        references = rule.get("source_ids")
        if not isinstance(references, list) or any(not isinstance(i, str) or i not in source_ids for i in references):
            errors.append(f"Rule {name} has invalid source_ids")
        elif rule.get("origin") == "official_rule" and not references:
            errors.append(f"Official rule {name} requires source_ids")
        if rule.get("origin") != "official_rule" and not isinstance(rule.get("note"), str):
            errors.append(f"Nonofficial rule {name} requires a note explaining the default/observation")
    checks = pack.get("required_checks")
    if not isinstance(checks, list) or any(not isinstance(x, str) or not IDENTIFIER.fullmatch(x) for x in checks):
        errors.append("required_checks must contain stable string identifiers")
    elif len(checks) != len(set(checks)):
        errors.append("required_checks must not contain duplicates")
    resources = pack.get("resources")
    if not isinstance(resources, dict):
        errors.append("resources must be an object")
    else:
        for name, resource in resources.items():
            if not _relative(resource):
                errors.append(f"Resource {name} must be a path inside the pack directory")
    try:
        canonical_json(_payload(pack))
    except (TypeError, ValueError, RuntimeError) as exc:
        errors.append(f"Pack is not finite JSON: {exc}")
    return errors


def _load_file(path):
    path = path.resolve(strict=True)
    data = _json(path)
    if isinstance(data, dict) and any(key in data for key in LOAD_META):
        raise ValueError("Pack files cannot supply loader metadata")
    errors = validate_pack(data)
    if errors:
        raise ValueError("; ".join(errors))
    hashes = {}
    for name, resource in data["resources"].items():
        target = (path.parent / resource).resolve(strict=True)
        if not target.is_relative_to(path.parent) or not target.is_file():
            raise ValueError(f"Resource escapes pack directory or is not a file: {resource}")
        hashes[name] = {"path": resource, "sha256": sha256_file(target)}
    data.update(_pack_path=str(path), _pack_file_sha256=sha256_file(path), _resource_hashes=hashes)
    return data


def load_pack(name_or_path) -> dict:
    """Discover installed pack manifests and aliases, or read an explicit path."""
    candidate = Path(name_or_path)
    if candidate.is_file() or candidate.is_dir():
        return _load_file(candidate / "pack.json" if candidate.is_dir() else candidate)
    requested = str(name_or_path).lower()
    if not IDENTIFIER.fullmatch(requested):
        raise ValueError(f"Unknown pack path/name: {name_or_path}")
    matches = []
    for path in sorted(PACK_ROOT.glob("*/pack.json")):
        pack = _load_file(path)
        if requested == pack["id"] or requested in pack["aliases"]:
            matches.append(pack)
    if len(matches) != 1:
        raise ValueError(f"Pack name/alias must resolve exactly once: {name_or_path}")
    return matches[0]


def _workspace_file(root, value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Snapshot path must be nonempty")
    given = Path(value)
    if not given.is_absolute() and not _relative(value):
        raise ValueError(f"Snapshot path traversal is not allowed: {value}")
    target = (given if given.is_absolute() else root / given).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"Snapshot is outside the workspace or not a file: {value}")
    return target


def _year_errors(pack, problem_year, rules_year, evaluation_mode):
    errors = []
    if not _year(problem_year) or not _year(rules_year):
        errors.append("problem_year and rules_year must be explicit valid years")
    if not isinstance(evaluation_mode, str) or evaluation_mode not in MODES:
        errors.append("evaluation_mode must be formal_contest, historical_benchmark or open_research")
    if evaluation_mode == "formal_contest" and problem_year != rules_year:
        errors.append("formal_contest requires matching problem_year and rules_year")
    if pack.get("rules_year") != rules_year:
        errors.append("rules_year does not match the loaded pack baseline")
    if pack.get("rules_status") != "baseline":
        errors.append("Pack rules remain unverified")
    return errors


def _snapshots(root, pack, source_snapshots, rules_year):
    if not isinstance(source_snapshots, list) or not source_snapshots:
        raise ValueError("Rules lock requires local source snapshots, not a verified flag")
    declared = {item["url"]: item for item in pack["official_sources"]}
    referenced = {source_id for rule in pack["rules"].values() for source_id in rule["source_ids"]}
    required = {item["url"] for item in declared.values()
                if item["required_for_lock"] or item["id"] in referenced}
    if not required:
        raise ValueError("Pack has no required official rule sources; generic/custom rules remain unverified")
    accepted = []
    seen = set()
    for item in source_snapshots:
        if not isinstance(item, dict) or item.get("url") not in declared:
            raise ValueError("Snapshot URL is not a declared official source")
        url = item["url"]
        if url in seen:
            raise ValueError("Duplicate rule source snapshot")
        seen.add(url)
        if item.get("rules_year", rules_year) != rules_year:
            raise ValueError("Snapshot rules_year does not match the rules lock")
        if not _timestamp(item.get("verified_at")):
            raise ValueError("Each source requires a nonfuture verified_at date/time")
        expected = item.get("sha256")
        if not isinstance(expected, str) or not HASH.fullmatch(expected):
            raise ValueError("Each source requires an explicit SHA-256")
        path = _workspace_file(root, item.get("path"))
        if path.stat().st_size == 0:
            raise ValueError("Empty rule snapshots cannot establish a rules baseline")
        actual = sha256_file(path)
        if actual != expected.upper():
            raise ValueError(f"Rule snapshot SHA-256 mismatch: {item['path']}")
        accepted.append({"source_id": declared[url]["id"], "url": url,
                         "path": path.relative_to(root).as_posix(), "sha256": actual,
                         "size_bytes": path.stat().st_size, "rules_year": rules_year,
                         "verified_at": item["verified_at"]})
    if required - seen:
        raise ValueError("Missing required official sources: " + ", ".join(sorted(required - seen)))
    return sorted(accepted, key=lambda row: row["source_id"])


def _fresh_pack(pack, root):
    errors = validate_pack(pack)
    if errors:
        raise ValueError("; ".join(errors))
    if not pack.get("_pack_path"):
        raise ValueError("Load the pack from its actual manifest before locking rules")
    actual = _load_file(Path(pack["_pack_path"]))
    if canonical_json(_payload(actual)) != canonical_json(_payload(pack)):
        raise ValueError("Pack changed since loading; persist custom edits and load again")
    path = Path(actual["_pack_path"])
    if path.is_relative_to(PACK_ROOT.resolve()):
        locator = {"kind": "installed", "id": actual["id"]}
    elif path.is_relative_to(root):
        locator = {"kind": "workspace", "path": path.relative_to(root).as_posix()}
    else:
        raise ValueError("Custom pack manifest must be within the workspace before rules locking")
    return actual, locator


def build_rules_lock(pack, problem_year, rules_year, evaluation_mode, source_snapshots=None, reviewer=None, workspace=None) -> dict:
    """Return a sealed record after checking real files; caller persists it via Store."""
    if workspace is None or not Path(workspace).is_dir():
        raise ValueError("Rules lock requires an existing workspace")
    root = Path(workspace).resolve()
    actual, locator = _fresh_pack(pack, root)
    errors = _year_errors(actual, problem_year, rules_year, evaluation_mode)
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append("Rules lock requires an explicit reviewer record")
    if errors:
        raise ValueError("; ".join(errors))
    snapshots = _snapshots(root, actual, source_snapshots, rules_year)
    payload = _payload(actual)
    return seal_record({"kind": "rules_lock", "status": "locked", "pack_id": actual["id"],
                        "pack": payload, "pack_sha256": sha256_bytes(canonical_json(payload)),
                        "pack_file_sha256": actual["_pack_file_sha256"], "pack_locator": locator,
                        "resource_hashes": actual["_resource_hashes"], "problem_year": problem_year,
                        "rules_year": rules_year, "evaluation_mode": evaluation_mode,
                        "source_snapshots": snapshots, "reviewer": reviewer.strip(),
                        "locked_at": datetime.now(timezone.utc).isoformat(),
                        "verification_scope": "snapshot_integrity_and_declared_rules_baseline"})


def verify_rules_lock(root, lock) -> list[str]:
    """Fail closed on malformed records, changed packs, paths, years or snapshots."""
    if not isinstance(lock, dict):
        return ["Rules lock must be an object"]
    errors = []
    try:
        errors.extend(verify_sealed_record(lock))
        if lock.get("kind") != "rules_lock" or lock.get("status") != "locked":
            errors.append("Record is not a locked rules record")
        if not isinstance(lock.get("reviewer"), str) or not lock["reviewer"].strip():
            errors.append("Missing rules reviewer")
        if not _timestamp(lock.get("locked_at")):
            errors.append("Invalid locked_at")
        workspace = Path(root).resolve(strict=True)
        locator = lock.get("pack_locator", {})
        if not isinstance(locator, dict):
            raise ValueError("Invalid pack locator")
        if locator.get("kind") == "installed":
            identifier = locator.get("id")
            if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
                raise ValueError("Installed pack locator must contain a canonical identifier, not a path")
            actual = load_pack(identifier)
            if actual["id"] != identifier or not Path(actual["_pack_path"]).is_relative_to(PACK_ROOT.resolve()):
                raise ValueError("Installed pack locator does not resolve inside the pack registry")
        elif locator.get("kind") == "workspace":
            actual = load_pack(_workspace_file(workspace, locator.get("path")))
        else:
            raise ValueError("Missing pack locator")
        payload = _payload(actual)
        if lock.get("pack_id") != actual["id"] or lock.get("pack") != payload:
            errors.append("Pack identity/content changed")
        if lock.get("pack_sha256") != sha256_bytes(canonical_json(payload)):
            errors.append("Pack semantic SHA-256 mismatch")
        if lock.get("pack_file_sha256") != actual["_pack_file_sha256"]:
            errors.append("Pack manifest bytes changed")
        if lock.get("resource_hashes") != actual["_resource_hashes"]:
            errors.append("Pack resource files changed")
        errors.extend(_year_errors(actual, lock.get("problem_year"), lock.get("rules_year"), lock.get("evaluation_mode")))
        snapshots = _snapshots(workspace, actual, lock.get("source_snapshots"), lock.get("rules_year"))
        if snapshots != lock.get("source_snapshots"):
            errors.append("Rule snapshot metadata changed")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        errors.append(str(exc))
    return errors
