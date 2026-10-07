"""Typed source notes and document identifiers, never result exemptions.

Only whole source directives are derived from authority. The surrounding prose
still needs ordinary Claim evidence. No arbitrary ignored span/text is accepted.
"""
from __future__ import annotations

import math
import re
import unicodedata
import json

SOURCE = re.compile(r"\[\[source:([A-Za-z][A-Za-z0-9_.-]*)\]\]")
TARGET = re.compile(r"\[\[(figure|table|formula|reference):([1-9][0-9]*)\]\]")
LABELS = {"figure": "图", "table": "表", "formula": "式", "reference": "文献"}


def _pointer(payload, path):
    if not isinstance(path, str) or not path.startswith("/") or re.search(r"~(?![01])", path):
        raise ValueError("Source requires a canonical JSON Pointer")
    value = payload
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("Invalid source array index")
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("Source pointer traverses a scalar")
    return value


def source_block_text(cp, binding):
    """Derive the entire visible note; caller-supplied prose is not trusted."""
    if not isinstance(binding, dict) or set(binding) != {"id", "kind", "source_id", "source_path"}:
        raise ValueError("Source binding fields are invalid")
    if not isinstance(binding["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", binding["id"]):
        raise ValueError("Invalid source binding ID")
    obj = cp["objects"].get(binding["source_id"], {})
    path, kind = binding["source_path"], binding["kind"]
    payload = obj.get("payload", {})
    value = _pointer(payload, path)
    if kind == "year":
        if obj.get("kind") != "RulesLock" or path not in {"/problem_year", "/rules_year"} or type(value) is not int or not 1000 <= value <= 9999:
            raise ValueError("Year must come from the current locked problem/rules year")
        label = "题目年份" if path == "/problem_year" else "规则核验年份"
    elif kind == "parameter":
        prefix = {"ModelSpec": "parameters", "ParameterSet": "entries"}.get(obj.get("kind"))
        if not prefix or not re.fullmatch(r"/" + prefix + r"/(0|[1-9][0-9]*)/current_value(?:/[^/]+)*", path):
            raise ValueError("Parameter note must reference a declared parameter value")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Parameter note requires a finite numeric value")
        entry_path, _, leaf_path = path.partition("/current_value")
        entry = _pointer(payload, entry_path)
        label = "模型参数 " + str(entry["symbol"]) + "（" + str(entry["meaning"]) + "）"
        if leaf_path:
            label += " · " + leaf_path
        value = str(value) + " " + str(entry.get("unit", "dimensionless"))
    elif kind == "formula":
        if obj.get("kind") != "ModelSpec" or not re.fullmatch(r"/formulas/(0|[1-9][0-9]*)/(expression|latex)", path) or not isinstance(value, str) or not value.strip():
            raise ValueError("Formula note must reference a declared ModelSpec expression")
        label = "模型公式"
    else:
        raise ValueError("Unknown source note kind")
    return "来源说明 · " + label + "：" + str(value)


def _contract(cp, source_bindings, structure, *, root=None):
    if not isinstance(source_bindings, list) or not isinstance(structure, list):
        raise ValueError("source_bindings and structure must be lists")
    notes, targets, dependencies = {}, {}, []
    for binding in source_bindings:
        visible = source_block_text(cp, binding)
        key = binding["id"]
        if key in notes:
            raise ValueError("Duplicate source binding ID")
        notes[key] = visible
        dependencies.append(binding["source_id"])
    for target in structure:
        if not isinstance(target, dict):
            raise ValueError("Structure declaration must be an object")
        kind, number = target.get("kind"), target.get("number")
        if kind not in LABELS or type(number) is not int or not 1 <= number <= 9999:
            raise ValueError("Invalid structure kind or number")
        key = (kind, str(number))
        if key in targets:
            raise ValueError("Duplicate structure identifier")
        if kind in {"figure", "table", "reference"}:
            if set(target) != {"kind", "number", "artifact_id"}:
                raise ValueError("Figure/table requires an exact artifact binding")
            obj = cp["objects"].get(target["artifact_id"], {})
            artifact_type = "reference_registry" if kind == "reference" else kind
            if obj.get("kind") != "ArtifactRecord" or obj.get("payload", {}).get("artifact_type") != artifact_type or not obj.get("files"):
                raise ValueError("Figure/table has no bound artifact of the declared kind")
            dependencies.append(target["artifact_id"])
            targets[key] = LABELS[kind] + " " + str(number)
            if kind == "reference":
                from copilot_runtime import safe_path, object_errors
                if root is None or len(obj["files"]) != 1:
                    raise ValueError("Reference projection requires a workspace and one bound registry file")
                issues = object_errors(root, cp, target["artifact_id"])
                if issues:
                    raise ValueError("; ".join(issues))
                registry = json.loads(safe_path(root, obj["files"][0]["path"]).read_text(encoding="utf-8"))
                from migrated.citation_audit import _validate_registry
                refs, _, marker, issues = _validate_registry(registry)
                matches = [entry for entry in refs if entry["number"] == number]
                if issues or marker != "[{number}]" or len(matches) != 1:
                    raise ValueError("Reference number is absent/ambiguous or its registry is invalid: " + "; ".join(issues))
                targets[key] = "[" + str(number) + "] " + matches[0]["title"]
        else:
            if set(target) != {"kind", "number", "source_id", "source_path"}:
                raise ValueError("Formula identifier requires an exact source binding")
            note = source_block_text(cp, {"id": "formula", "kind": "formula", "source_id": target["source_id"], "source_path": target["source_path"]})
            dependencies.append(target["source_id"])
            targets[key] = "式（" + str(number) + "） " + note
    return notes, targets, list(dict.fromkeys(dependencies))


def section_projection(cp, text, source_bindings=None, structure=None, *, root=None):
    """Return visible Markdown, preserving all result prose and Claim markers.

    This is a projection helper, not a validation API. Consumers must call
    prepare_section / the Delivery gate to establish current source integrity.
    """
    notes, targets, _ = _contract(cp, source_bindings or [], structure or [], root=root)
    text = SOURCE.sub(lambda m: notes[m[1]], text)
    return TARGET.sub(lambda m: targets[(m[1], m[2])], text)


def prepare_section(root, cp, text, source_bindings=None, structure=None):
    """Validate declarations and return prose still requiring Claim evidence."""
    from copilot_runtime import usable
    notes, targets, dependencies = _contract(cp, [] if source_bindings is None else source_bindings,
                                              [] if structure is None else structure, root=root)
    errors = []
    for oid in dependencies:
        if not usable(root, cp, oid):
            errors.append("Section source is missing or stale: " + oid)
    # A code listing cannot declare a figure or secretly consume a source note.
    visible = re.sub(r"```.*?```|~~~.*?~~~", "", text, flags=re.S)
    found_notes = SOURCE.findall(visible)
    found_targets = TARGET.findall(visible)
    if set(found_notes) != set(notes) or len(found_notes) != len(set(found_notes)):
        errors.append("Source directives must exactly match the declared unique source bindings")
    if set(found_targets) != set(targets) or len(found_targets) != len(set(found_targets)):
        errors.append("Structure directives must exactly match the declared unique targets")
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", visible):
        stripped = paragraph.strip()
        if SOURCE.fullmatch(stripped) or TARGET.fullmatch(stripped):
            continue
        if SOURCE.search(paragraph) or TARGET.search(paragraph):
            errors.append("Source/structure directive must occupy a whole paragraph")
        if "[[source:" in paragraph or re.search(r"\[\[(?:figure|table|formula|reference):", paragraph):
            errors.append("Malformed or misplaced source/structure directive")
        paragraphs.append(paragraph)
    prose = "\n\n".join(paragraphs)
    # Only the leading outline number is structural; all of the heading's body
    # remains checked. A unit-only heading is not an outline title.
    def heading(match):
        prefix, body = match[1], match[3]
        if re.match(r"(?:(?:m|s|kg|g|km|cm|mm|ms|h|hz|pa|kpa|mpa|w|kw|mw|mol|k|v|a)\b|[%℃°]|米|秒|分钟|小时|天|年|元|亿元|次|个|台|种|组|人|件|只|个百分点)", unicodedata.normalize("NFKC", body.strip()), re.I):
            return match[0]
        return prefix + body
    prose = re.sub(r"(?m)^(\s{0,3}#{1,6}\s+)([1-9][0-9]?(?:\.[1-9][0-9]?)*\.?)[ \t]+(.+)$", heading, prose)
    def reference(match):
        following = unicodedata.normalize("NFKC", prose[match.end():]).translate(str.maketrans({c: "-" for c in "−–—‐‑‒"}))
        if re.match(r"\s*(?:[eE]\s*[+-]?\s*\d|%|[.,]\d)", following):
            return match[0]
        label, number = match[1], match[2]
        kind = {"图": "figure", "表": "table", "式": "formula"}[label]
        if (kind, number) not in targets:
            errors.append("Undefined structure reference: " + match[0])
            return match[0]
        return label
    # Do not consume a prefix of an exponent, decimal, unit, percent or range;
    # otherwise the remaining e3 could look like an identifier to the lexer.
    prose = re.sub(r"(图|表)\s*([1-9][0-9]*)(?![0-9０-９A-Za-zｅＥ_.%％,，+＋-])", reference, prose)
    prose = re.sub(r"(式)\s*[（(]([1-9][0-9]*)[）)]", reference, prose)
    def citation(match):
        if ("reference", match[1]) not in targets:
            errors.append("Undefined reference identifier: " + match[0])
            return match[0]
        return "[文献]"
    # This namespace is enabled only by explicit registry declarations. Old
    # bracketed metric text keeps its previous numeric checks.
    if any(kind == "reference" for kind, _ in targets):
        prose = re.sub(r"(?<!\[)\[([1-9][0-9]*)\](?!\])", citation, prose)
    return prose, dependencies, list(dict.fromkeys(errors))
