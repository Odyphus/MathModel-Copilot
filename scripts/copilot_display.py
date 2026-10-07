"""Deterministic numeric presentation contracts over authoritative Result metrics.

This module writes nothing and grants no semantic or structural-number waiver.
The caller retains the Runtime's actual file, question and evidence checks.
"""
from __future__ import annotations

import copy
import math
import re
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext

from copilot_store import digest

VERSION = "0.1"
MAX_DECIMAL_PLACES = 12
MAX_CONTRACTS = 256
FIELDS = {"version", "result_id", "metric_path", "raw_value", "display_value",
          "format", "decimal_places", "rounding"}
ROUNDING = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP}
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
INVALID_STATUSES = {"stale", "superseded", "failed", "timeout", "interrupted", "missing_outputs"}


def _decimal(text, label):
    if not isinstance(text, str) or not 0 < len(text) <= 512 or not NUMBER.fullmatch(text):
        raise ValueError(f"Display {label} must be an explicit finite decimal string")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Display {label} is not a decimal") from exc
    # Bound expansion/precision cost independently of the ambient Decimal context.
    if not value.is_finite() or abs(value.adjusted()) > 1000 or abs(value.as_tuple().exponent) > 1000:
        raise ValueError(f"Display {label} is non-finite or outside supported numeric bounds")
    return value


def resolve_metric(metrics, pointer):
    """Read one exact RFC 6901 pointer relative to metrics, never an expression."""
    if not isinstance(pointer, str) or not pointer.startswith("/") or len(pointer) > 1024:
        raise ValueError("Display metric_path must be a JSON Pointer relative to Result.metrics")
    parts = pointer[1:].split("/")
    if len(parts) > 32 or any(re.search(r"~(?![01])", part) for part in parts):
        raise ValueError("Display metric_path has invalid escapes or excessive depth")
    value = metrics
    for encoded in parts:
        key = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and len(key) <= 10 and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ValueError(f"Display metric_path does not identify a metric: {pointer}")
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError("Display source metric must be a finite JSON number, not bool/text/container")
    return value


def _current_source(cp, result_id):
    """Check the authoritative object graph; physical files belong to Runtime."""
    objects, current = cp.get("objects", {}), cp.get("current", {})
    root = objects.get(result_id, {})
    if not isinstance(root, dict) or root.get("kind") != "ResultRecord" or root.get("status") != "verified":
        raise ValueError("Display source must be an authoritative verified ResultRecord")
    pending, active, complete = [(result_id, False)], set(), set()
    while pending:
        object_id, leaving = pending.pop()
        if leaving:
            active.remove(object_id)
            complete.add(object_id)
            continue
        if object_id in complete:
            continue
        if object_id in active:
            raise ValueError("Display source has a cyclic dependency")
        obj = objects.get(object_id)
        if not isinstance(obj, dict) or obj.get("id") != object_id:
            raise ValueError("Display source dependency is missing or has a mismatched ID")
        if not isinstance(obj.get("key"), str) or not isinstance(obj.get("status"), str):
            raise ValueError("Display source dependency key/status is invalid")
        if current.get(obj["key"]) != object_id or obj["status"] in INVALID_STATUSES:
            raise ValueError("Display source or a dependency is stale/non-current")
        try:
            payload_matches = isinstance(obj.get("payload"), dict) and digest(obj["payload"]) == obj.get("payload_hash")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("Display source payload is not a valid authoritative JSON record") from exc
        if not payload_matches:
            raise ValueError("Display source payload hash does not match the authoritative record")
        deps = obj.get("dependencies")
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError("Display source dependencies are invalid")
        active.add(object_id)
        pending.append((object_id, True))
        pending.extend((dep, False) for dep in reversed(deps))
    return root


def validate_display_contracts(cp, result_ids, contracts, *, source_errors=None):
    """Return audited numeric bindings, or raise ValueError for any bad contract.

    result_ids is the enclosing Claim's allowed Result dependency set. An
    optional source_errors(result_id) callback returns Runtime file/dependency
    errors; callers without it must enforce those checks at their trust gate.
    Empty contracts preserve the existing exact-number path. No tolerance,
    arbitrary scale, formatter program, or number-exemption parameter exists.
    """
    if not isinstance(cp, dict) or not isinstance(result_ids, (list, tuple)) or any(not isinstance(x, str) for x in result_ids):
        raise ValueError("Display validation requires authority and explicit Result IDs")
    if not isinstance(cp.get("objects"), dict) or not isinstance(cp.get("current"), dict):
        raise ValueError("Display validation requires authoritative object and current maps")
    if not isinstance(contracts, list) or len(contracts) > MAX_CONTRACTS:
        raise ValueError(f"Display contracts must be a list with at most {MAX_CONTRACTS} entries")
    if source_errors is not None and not callable(source_errors):
        raise ValueError("Display source_errors must be a trusted callable, not a caller status flag")
    bindings, fingerprints, checked = [], set(), {}
    for contract in contracts:
        if not isinstance(contract, dict) or set(contract) != FIELDS:
            raise ValueError("Display contract has missing or unknown parameters")
        if contract["version"] != VERSION:
            raise ValueError("Unsupported display contract version")
        result_id = contract["result_id"]
        if not isinstance(result_id, str) or result_id not in result_ids:
            raise ValueError("Display source is outside the enclosing Claim's declared Results")
        if not isinstance(contract["format"], str) or contract["format"] not in {"decimal", "percent"}:
            raise ValueError("Display format must be decimal or fraction-to-percent")
        if not isinstance(contract["rounding"], str) or contract["rounding"] not in ROUNDING:
            raise ValueError("Display rounding must be half_even or half_up")
        places = contract["decimal_places"]
        if type(places) is not int or not 0 <= places <= MAX_DECIMAL_PLACES:
            raise ValueError(f"Display decimal_places must be an integer between 0 and {MAX_DECIMAL_PLACES}")
        raw = _decimal(contract["raw_value"], "raw_value")
        shown = contract["display_value"]
        if not isinstance(shown, str) or len(shown) > 1024:
            raise ValueError("Display display_value must be a bounded explicit string")
        if not isinstance(contract["metric_path"], str):
            raise ValueError("Display metric_path must be a JSON Pointer string")
        if result_id not in checked:
            checked[result_id] = _current_source(cp, result_id)
            if source_errors is not None:
                errors = source_errors(result_id)
                if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
                    raise ValueError("Display source_errors callback must return an error list")
                if errors:
                    raise ValueError("Display source is not currently usable: " + "; ".join(errors))
        obj = checked[result_id]
        observed = resolve_metric(obj["payload"].get("metrics"), contract["metric_path"])
        actual = _decimal(str(observed), "source value")
        if raw != actual:
            raise ValueError("Display raw_value does not exactly match the named Result metric")
        mode = ROUNDING[contract["rounding"]]
        precision = max(64, len(actual.as_tuple().digits) + abs(actual.adjusted()) + places + 20)
        with localcontext(Context(prec=precision, rounding=mode, Emin=-999999, Emax=999999)):
            shift = 2 if contract["format"] == "percent" else 0
            scaled = actual.scaleb(shift)
            rounded = scaled.quantize(Decimal(1).scaleb(-places), rounding=mode)
            if actual != 0 and rounded == 0:
                raise ValueError("Display precision erases a non-zero source; increase decimal_places")
            expected = format(rounded, f".{places}f") + ("%" if shift else "")
            delta = format(rounded.scaleb(-shift) - actual, "f")
        if shown != expected:
            raise ValueError(f"Display value is not the declared deterministic rounding: expected {expected}")
        fingerprint = digest(contract)
        if fingerprint in fingerprints:
            raise ValueError("Duplicate display contract")
        fingerprints.add(fingerprint)
        bindings.append({"text": shown,
                         "sources": [{"result_id": result_id, "metric_path": contract["metric_path"], "value": observed}],
                         "display_contract": copy.deepcopy(contract), "derived_value": expected,
                         "rounding_delta": delta, "rounding_delta_basis": "source_metric",
                         "source_payload_hash": obj["payload_hash"]})
    return bindings
