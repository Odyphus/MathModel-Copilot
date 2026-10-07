"""Migrated CUMCM 1.6.0 contracts and stateless checks.

This module never reads or writes a workflow state. Its dataclasses are data
contracts, not evidence that an execution, review, or human decision happened.
See docs/MIGRATION.md for exact source hashes, symbols, and adaptations.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"


PARAMETER_CATEGORIES = {"estimated", "human_set", "external", "derived"}


MODEL_STATUSES = {"draft", "under_review", "frozen", "superseded"}


class WorkflowError(RuntimeError):
    """Expected user-facing workflow error."""


ANONYMOUS_TEAM_ROLES = {"modeler", "coder", "writer", "integrator", "reviewer", "agent_evaluator"}


def _anonymous_collaborator_errors(
    values: Sequence[str], *, field_name: str
) -> list[str]:
    errors: list[str] = []
    for value in values:
        identifier = str(value).strip()
        if not identifier:
            errors.append(f"{field_name} 含空成员标识")
        elif not re.fullmatch(r"member_[1-9][0-9]*", identifier) and identifier not in ANONYMOUS_TEAM_ROLES:
            errors.append(
                f"{field_name} 必须使用 member_N 或匿名角色，不得写姓名：{identifier}"
            )
    return errors


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    value = _normalize_canonical(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalize_canonical(value: Any) -> Any:
    """Normalize values before canonical JSON hashing.

    JSON has no portable representation for NaN/Infinity, and negative zero is
    semantically indistinguishable from zero in this workflow.  Rejecting the
    former and normalizing the latter prevents cross-machine hash drift.
    """

    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise WorkflowError("规范 JSON 不允许 NaN 或 Infinity。")
        return 0.0 if value == 0.0 else value
    if isinstance(value, Mapping):
        return {str(key): _normalize_canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_canonical(item) for item in value]
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


RECORD_META_FIELDS = {"semantic_hash", "record_hash"}


SEMANTIC_META_FIELDS = RECORD_META_FIELDS | {
    "stable_id",
    "content_sha256",
    "created_at",
    "updated_at",
    "frozen_at",
    "activated_at",
    "promoted_at",
    "timestamp",
}


def seal_record(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a record with stable semantic and full-record hashes."""

    record = dict(value)
    if not record.get("schema_version"):
        record["schema_version"] = SCHEMA_VERSION
    if not record.get("stable_id"):
        record["stable_id"] = f"OBJ-{uuid.uuid4().hex.upper()}"
    semantic_payload = _strip_keys_recursive(record, SEMANTIC_META_FIELDS)
    record["semantic_hash"] = sha256_bytes(canonical_json(semantic_payload))
    record_payload = {key: item for key, item in record.items() if key != "record_hash"}
    record["record_hash"] = sha256_bytes(canonical_json(record_payload))
    return record


def _strip_keys_recursive(value: Any, excluded: set[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_keys_recursive(item, excluded)
            for key, item in value.items()
            if str(key) not in excluded
        }
    if isinstance(value, (list, tuple)):
        return [_strip_keys_recursive(item, excluded) for item in value]
    return value


def verify_sealed_record(
    value: Mapping[str, Any], *, expected_schema_version: str = SCHEMA_VERSION
) -> list[str]:
    errors: list[str] = []
    original = dict(value)
    expected_semantic = original.get("semantic_hash")
    expected_record = original.get("record_hash")
    resealed = seal_record(original)
    if expected_semantic != resealed["semantic_hash"]:
        errors.append("semantic_hash 不匹配")
    if expected_record != resealed["record_hash"]:
        errors.append("record_hash 不匹配")
    if not original.get("stable_id"):
        errors.append("缺少 stable_id")
    if original.get("schema_version") != expected_schema_version:
        errors.append("schema_version 不匹配")
    return errors


def load_structured(path: Path) -> dict[str, Any]:
    """Load JSON or JSON-subset YAML.

    PyYAML is intentionally not a runtime dependency.  If it happens to be
    installed, conventional YAML is accepted as a convenience; files emitted by
    this package remain dependency-free JSON-subset YAML.
    """

    text = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            try:
                value = _load_minimal_yaml(text)
            except (ValueError, IndexError) as exc:
                raise WorkflowError(
                    f"{path} 超出内置离线 YAML 子集；请改用 JSON 语法或安装 PyYAML。"
                ) from exc
        else:
            value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise WorkflowError(f"{path} 顶层必须是对象。")
    return value


def _load_minimal_yaml(text: str) -> Any:
    """Parse the conservative YAML subset used by bundled templates.

    Supported constructs are indentation-based mappings/lists, scalar values,
    and JSON-style inline lists/maps. Anchors, tags, block scalars and merge
    keys are intentionally rejected so offline behavior stays predictable.
    """

    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError("tabs are not supported")
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()
        if content.startswith(("|", ">", "&", "*", "!")) or "<<:" in content:
            raise ValueError("advanced YAML is not supported")
        lines.append((indent, content))
    if not lines:
        return {}

    def scalar(token: str) -> Any:
        token = token.strip()
        lowered = token.lower()
        if lowered in {"null", "~"}:
            return None
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if token.startswith(("[", "{")):
            return json.loads(token)
        if token.startswith(('"', "'")) and token.endswith(token[0]):
            return json.loads(token) if token[0] == '"' else token[1:-1].replace("''", "'")
        if re.fullmatch(r"[-+]?\d+", token):
            return int(token)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", token):
            return float(token)
        if ": " in token or token.endswith(":"):
            raise ValueError("ambiguous scalar")
        return token

    def split_key(content: str) -> tuple[str, str]:
        if ":" not in content:
            raise ValueError("mapping entry lacks colon")
        key, remainder = content.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError("empty key")
        return key, remainder.strip()

    def parse_node(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines) or lines[index][0] != indent:
            raise ValueError("invalid indentation")
        if lines[index][1].startswith("-"):
            return parse_list(index, indent)
        return parse_map(index, indent)

    def parse_map(index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(lines):
            current_indent, content = lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or content.startswith("-"):
                break
            key, remainder = split_key(content)
            index += 1
            if remainder:
                result[key] = scalar(remainder)
            elif index < len(lines) and lines[index][0] > indent:
                result[key], index = parse_node(index, lines[index][0])
            else:
                result[key] = None
        return result, index

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(lines):
            current_indent, content = lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or not content.startswith("-"):
                break
            remainder = content[1:].strip()
            index += 1
            if not remainder:
                if index < len(lines) and lines[index][0] > indent:
                    item, index = parse_node(index, lines[index][0])
                else:
                    item = None
            elif ":" in remainder:
                key, value_text = split_key(remainder)
                item = {key: scalar(value_text) if value_text else None}
                if index < len(lines) and lines[index][0] > indent:
                    child_indent = lines[index][0]
                    if value_text:
                        extra, index = parse_map(index, child_indent)
                        item.update(extra)
                    else:
                        child, index = parse_node(index, child_indent)
                        item[key] = child
                        if index < len(lines) and lines[index][0] == child_indent:
                            extra, index = parse_map(index, child_indent)
                            item.update(extra)
            else:
                item = scalar(remainder)
                if index < len(lines) and lines[index][0] > indent:
                    raise ValueError("scalar list item cannot have children")
            result.append(item)
        return result, index

    parsed, consumed = parse_node(0, lines[0][0])
    if consumed != len(lines):
        raise ValueError("unconsumed YAML lines")
    return parsed


@dataclass
class ParameterEntry:
    parameter_id: str
    symbol: str
    meaning: str
    unit: str = "dimensionless"
    category: str = "estimated"
    subcategory: str = ""
    current_value: Any = None
    candidate_range: Any = None
    distribution: Any = None
    basis: str = ""
    estimation_method: str = ""
    data_scope: str = ""
    external_source: str = ""
    literature_source_ids: list[str] = field(default_factory=list)
    uncertainty: Any = None
    formula_ids: list[str] = field(default_factory=list)
    code_variable: str = ""
    code_location: str = ""
    affects_core_conclusion: bool = False
    sensitivity_required: bool = False
    sensitivity_plan: str = ""
    sensitivity_status: str = "not_required"
    sensitivity_result: str = ""
    boundary_hit: bool = False
    boundary_resolution: str = ""
    derived_from: list[str] = field(default_factory=list)
    stable_id: str = field(default_factory=lambda: f"PARAM-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterEntry":
        return cls(**dict(value))


@dataclass
class FormulaCodeAuditEntry:
    formula_id: str
    element_id: str
    element_type: str
    modelspec_definition: str
    data_field: str = ""
    code_module: str = ""
    code_module_sha256: str = ""
    code_function: str = ""
    code_variable: str = ""
    unit: str = ""
    expected: Any = None
    actual: Any = None
    auto_result: str = "not_run"
    manual_result: str = "not_reviewed"
    evidence: list[str] = field(default_factory=list)
    status: str = "not_reviewed"
    failure_reason: str = ""
    fix_commit: str = ""
    stable_id: str = field(default_factory=lambda: f"AUD-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormulaCodeAuditEntry":
        return cls(**dict(value))


@dataclass
class EvidenceMapEntry:
    claim_id: str
    claim: str
    claim_type: str = "numerical"
    paper_anchor: str = ""
    formula_ids: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    code_locations: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    validation_evidence: list[str] = field(default_factory=list)
    literature_sources: list[str] = field(default_factory=list)
    display_contracts: list[dict[str, Any]] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    reviewer: str = ""
    formal_run_id: str = ""
    status: str = "draft"
    stable_id: str = field(default_factory=lambda: f"CLAIM-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceMapEntry":
        source = dict(value)
        source.setdefault("literature_sources", [])
        return cls(**source)


@dataclass
class ArtifactRecord:
    path: str
    version: str
    byte_size: int
    sha256: str
    artifact_type: str = "generic"
    generation_command: str = ""
    formal_status: str = "candidate"
    source_artifact_id: str = ""
    source_sha256: str = ""
    qa_status: str = "pending"
    milestone: str = "draft"
    evidence_refs: list[str] = field(default_factory=list)
    stable_id: str = field(default_factory=lambda: f"ART-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRecord":
        return cls(**dict(value))


@dataclass
class ValidationCheck:
    check_id: str
    severity: str
    result: str
    evidence: str
    remediation: str = ""
    stable_id: str = field(default_factory=lambda: f"VAL-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationCheck":
        return cls(**dict(value))


@dataclass
class ModelSpec:
    question: str
    title: str = ""
    objective: Any = field(default_factory=dict)
    observation_unit: str = ""
    spec_id: str = ""
    revision: int = 1
    status: str = "draft"
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    reality: dict[str, Any] = field(default_factory=dict)
    method_decision: dict[str, Any] = field(default_factory=dict)
    time_space_scale: str = ""
    symbols: list[dict[str, Any]] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    parameters: list[ParameterEntry] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    solver: dict[str, Any] = field(default_factory=dict)
    randomness: dict[str, Any] = field(default_factory=dict)
    validation_plan: list[dict[str, Any]] = field(default_factory=list)
    required_outputs: list[Any] = field(default_factory=list)
    failure_conditions: list[Any] = field(default_factory=list)
    data_contract: dict[str, Any] = field(default_factory=dict)
    not_applicable_reasons: dict[str, str] = field(default_factory=dict)
    parameter_schema_ref: str = ""
    downstream_dependencies: list[str] = field(default_factory=list)
    result_summary: list[str] = field(default_factory=list)
    data_input_hashes: dict[str, str] = field(default_factory=dict)
    problem_contract_id: str = ""
    problem_contract_semantic_hash: str = ""
    requirement_ids: list[str] = field(default_factory=list)
    parent_spec_id: str = ""
    parent_semantic_hash: str = ""
    confirmed_members: list[str] = field(default_factory=list)
    governance: dict[str, Any] = field(default_factory=dict)
    frozen_at: str = ""
    content_sha256: str = ""
    stable_id: str = field(default_factory=lambda: f"MSOBJ-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameters"] = [item.to_dict() for item in self.parameters]
        return seal_record(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelSpec":
        source = dict(value)
        if "parent_hash" in source and "parent_semantic_hash" not in source:
            source["parent_semantic_hash"] = source.pop("parent_hash")
        if "validation" in source and "validation_plan" not in source:
            source["validation_plan"] = source.pop("validation")
        if not source.get("title"):
            reality = source.get("reality") or {}
            source["title"] = reality.get("decision_or_prediction") or f"{source.get('question', '未编号')} ModelSpec"
        governance = source.get("governance") or {}
        if not source.get("frozen_at") and governance.get("frozen_at"):
            source["frozen_at"] = governance.get("frozen_at")
        if not source.get("confirmed_members"):
            source["confirmed_members"] = governance.get("reviewed_by") or []
        source["parameters"] = [
            item if isinstance(item, ParameterEntry) else ParameterEntry.from_dict(item)
            for item in source.get("parameters", [])
        ]
        allowed = cls.__dataclass_fields__
        unknown = sorted(set(source) - set(allowed))
        if unknown:
            raise WorkflowError(f"ModelSpec 含未知字段：{', '.join(unknown)}")
        try:
            return cls(**source)
        except TypeError as exc:
            raise WorkflowError(f"ModelSpec 缺少必需字段或字段类型错误：{exc}") from exc


@dataclass
class ActivationRecord:
    question: str
    spec_id: str
    modelspec_semantic_hash: str
    spec_record_hash: str
    effective_main_commit: str
    effective_tag: str
    activated_by: list[str]
    parameter_set_id: str = ""
    parameter_set_semantic_hash: str = ""
    data_manifest_id: str = ""
    data_manifest_sha256: str = ""
    skill_lock_sha256: str = ""
    skill_root_hash: str = ""
    supersedes_activation_id: str = ""
    status: str = "active"
    notes: str = ""
    activated_at: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: f"ACT-{uuid.uuid4().hex.upper()}")
    activation_id: str = ""
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["activation_id"] = value["activation_id"] or value["stable_id"]
        return seal_record(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActivationRecord":
        source = dict(value)
        aliases = {
            "spec_semantic_hash": "modelspec_semantic_hash",
            "activated_git_commit": "effective_main_commit",
            "confirmed_by": "activated_by",
        }
        for old, new in aliases.items():
            if old in source and new not in source:
                source[new] = source.pop(old)
        if source.get("activation_id") and not source.get("stable_id"):
            source["stable_id"] = source["activation_id"]
        source.setdefault("effective_tag", "")
        source.setdefault("spec_record_hash", "")
        unknown = sorted(set(source) - set(cls.__dataclass_fields__))
        if unknown:
            raise WorkflowError("ActivationRecord 含未知字段：" + ", ".join(unknown))
        try:
            return cls(**source)
        except TypeError as exc:
            raise WorkflowError(f"ActivationRecord 契约错误：{exc}") from exc


@dataclass
class ParameterSet:
    question: str
    spec_id: str
    modelspec_semantic_hash: str
    modelspec_record_hash: str
    version: int
    entries: list[ParameterEntry]
    status: str = "frozen"
    created_by: list[str] = field(default_factory=list)
    source_table: str = ""
    source_table_sha256: str = ""
    sensitivity_records: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: f"PSET-{uuid.uuid4().hex.upper()}")
    parameter_set_id: str = ""
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["entries"] = [item.to_dict() for item in self.entries]
        value["parameter_set_id"] = value["parameter_set_id"] or value["stable_id"]
        return seal_record(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterSet":
        source = dict(value)
        if "modelspec_id" in source and "spec_id" not in source:
            source["spec_id"] = source.pop("modelspec_id")
        if "parameters" in source and "entries" not in source:
            source["entries"] = source.pop("parameters")
        if "sensitivity_scenarios" in source and "sensitivity_records" not in source:
            source["sensitivity_records"] = source.pop("sensitivity_scenarios")
        source.pop("parameter_set_sha256", None)
        source.pop("estimation_data_manifest", None)
        if source.get("parameter_set_id") and not source.get("stable_id"):
            source["stable_id"] = source["parameter_set_id"]
        source.setdefault("modelspec_record_hash", "")
        source.setdefault("version", 1)
        source["entries"] = [ParameterEntry.from_dict(item) for item in source.get("entries", [])]
        unknown = sorted(set(source) - set(cls.__dataclass_fields__))
        if unknown:
            raise WorkflowError("ParameterSet 含未知字段：" + ", ".join(unknown))
        try:
            return cls(**source)
        except TypeError as exc:
            raise WorkflowError(f"ParameterSet 契约错误：{exc}") from exc


@dataclass
class ProvenanceEdge:
    from_id: str
    from_type: str
    to_id: str
    to_type: str
    relation: str
    invalidates: bool = True
    evidence: str = ""
    created_at: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: f"EDGE-{uuid.uuid4().hex.upper()}")
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProvenanceEdge":
        return cls(**dict(value))


@dataclass
class RunRecord:
    run_type: str
    question: str
    activation_id: str
    activation_record_hash: str
    spec_id: str
    modelspec_semantic_hash: str
    modelspec_record_hash: str
    parameter_set_id: str
    parameter_set_semantic_hash: str
    git_commit: str
    data_version: str
    data_hash: str
    config_hash: str
    environment: dict[str, Any]
    command: str
    seed: str
    repeat_count: int
    outputs: list[dict[str, str]]
    code_manifest_id: str = ""
    code_manifest_hash: str = ""
    code_manifest_path: str = ""
    code_manifest_sha256: str = ""
    data_manifest_path: str = ""
    data_manifest_sha256: str = ""
    config_path: str = ""
    config_sha256: str = ""
    repeat_ledger_path: str = ""
    repeat_ledger_sha256: str = ""
    validation_report_path: str = ""
    validation_report_sha256: str = ""
    validation_status: str = "pending"
    artifact_ids: list[str] = field(default_factory=list)
    notes: str = ""
    # A filled template or deserialized object does not prove execution.
    status: str = "not_executed"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: f"RUN-{uuid.uuid4().hex.upper()}")
    run_id: str = ""
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["run_id"] = value["run_id"] or value["stable_id"]
        return seal_record(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunRecord":
        source = dict(value)
        legacy_formal = source.pop("formal", None)
        if legacy_formal and "run_type" not in source:
            source["run_type"] = "formal"
        activation = source.pop("activation_record", {}) or {}
        parameter_set = source.pop("parameter_set", {}) or {}
        data_manifest = source.pop("data_manifest", {}) or {}
        code = source.pop("code", {}) or {}
        randomness = source.pop("randomness", {}) or {}
        source.pop("skill_lock", None)
        if activation:
            source.setdefault("activation_id", activation.get("id", ""))
            source.setdefault("activation_record_hash", activation.get("sha256", ""))
        if parameter_set:
            source.setdefault("parameter_set_id", parameter_set.get("id", ""))
            source.setdefault("parameter_set_semantic_hash", parameter_set.get("sha256", ""))
        if data_manifest:
            source.setdefault("data_version", data_manifest.get("id", ""))
            source.setdefault("data_hash", data_manifest.get("sha256", ""))
        if code:
            source.setdefault("git_commit", code.get("git_commit", ""))
            source.setdefault("command", code.get("command", ""))
            source.setdefault("environment", {"dependency_lock": code.get("environment_lock", "")})
        if randomness:
            source.setdefault("seed", str(randomness.get("root_seed", "")))
            source.setdefault("repeat_count", int(randomness.get("repetitions_expected") or 0))
        if "completed_at" in source and "finished_at" not in source:
            source["finished_at"] = source.pop("completed_at")
        if "outputs_manifest" in source and "outputs" not in source:
            manifest = source.pop("outputs_manifest")
            source["outputs"] = [] if manifest is None else [{"manifest": str(manifest)}]
        if "validation_report" in source and "validation_status" not in source:
            source["validation_status"] = source.pop("validation_report") or "pending"
        source.pop("parallelism", None)
        aliases = {
            "code_commit": "git_commit",
            "input_data_version": "data_version",
            "input_data_hash": "data_hash",
            "output_artifacts": "outputs",
            "created_at": "started_at",
        }
        for old, new in aliases.items():
            if old in source and new not in source:
                source[new] = source.pop(old)
        if source.get("run_id") and not source.get("stable_id"):
            source["stable_id"] = source["run_id"]
        source.setdefault("run_type", "candidate")
        source.setdefault("question", "")
        source.setdefault("activation_id", "")
        source.setdefault("activation_record_hash", "")
        source.setdefault("spec_id", "")
        source.setdefault("modelspec_semantic_hash", "")
        source.setdefault("modelspec_record_hash", "")
        source.setdefault("parameter_set_id", "")
        source.setdefault("parameter_set_semantic_hash", "")
        source.setdefault("git_commit", "")
        source.setdefault("data_version", "")
        source.setdefault("data_hash", "")
        source.setdefault("config_hash", "")
        source.setdefault("environment", {})
        source.setdefault("command", "")
        source.setdefault("seed", "")
        source.setdefault("repeat_count", 1)
        source.setdefault("outputs", [])
        source.setdefault("code_manifest_path", "")
        source.setdefault("code_manifest_sha256", "")
        source.setdefault("data_manifest_path", "")
        source.setdefault("data_manifest_sha256", "")
        source.setdefault("config_path", "")
        source.setdefault("config_sha256", "")
        source.setdefault("repeat_ledger_path", "")
        source.setdefault("repeat_ledger_sha256", "")
        source.setdefault("validation_report_path", "")
        source.setdefault("validation_report_sha256", "")
        source.setdefault("finished_at", source.get("started_at", utc_now()))
        unknown = sorted(set(source) - set(cls.__dataclass_fields__))
        if unknown:
            raise WorkflowError("RunRecord 含未知字段：" + ", ".join(unknown))
        try:
            return cls(**source)
        except TypeError as exc:
            raise WorkflowError(f"RunRecord 契约错误：{exc}") from exc


def normalize_question(question: str) -> str:
    cleaned = question.strip().upper().replace("问题", "Q").replace("第", "")
    cleaned = cleaned.replace("问", "")
    chinese_numbers = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    cleaned = "".join(chinese_numbers.get(character, character) for character in cleaned)
    if cleaned.isdigit():
        cleaned = f"Q{cleaned}"
    if not re.fullmatch(r"Q?[A-Z0-9_-]+", cleaned):
        raise WorkflowError(f"不合法的小问编号：{question!r}")
    return cleaned


def compute_modelspec_hash(spec: ModelSpec | Mapping[str, Any]) -> str:
    value = spec.to_dict() if isinstance(spec, ModelSpec) else dict(spec)
    value = _strip_keys_recursive(
        value,
        {"content_sha256", "semantic_hash", "record_hash", "stable_id", "frozen_at"},
    )
    return sha256_bytes(canonical_json(value))


def validate_modelspec_structure(spec: ModelSpec) -> list[str]:
    errors: list[str] = []
    if spec.status not in MODEL_STATUSES:
        errors.append(f"非法 ModelSpec 状态：{spec.status}")
    if not spec.question:
        errors.append("缺少 question")
    if not spec.title:
        errors.append("缺少 title")
    if not spec.objective:
        errors.append("缺少 objective")
    if not spec.observation_unit:
        errors.append("缺少 observation_unit")
    if spec.status == "frozen":
        def present_or_explained(field_name: str, value: Any) -> bool:
            raw_reason = spec.not_applicable_reasons.get(field_name)
            reason = "" if raw_reason is None else str(raw_reason).strip()
            return bool(value) or bool(
                reason and reason.casefold() not in {"none", "null", "n/a"}
            )

        for field_name, value in (
            ("inputs", spec.inputs),
            ("outputs", spec.outputs),
            ("data_contract", spec.data_contract),
            ("solver", spec.solver),
            ("randomness", spec.randomness),
            ("constraints", spec.constraints),
        ):
            if not present_or_explained(field_name, value):
                errors.append(
                    f"冻结 ModelSpec 的 {field_name} 为空，必须填写内容或给出明确不适用理由"
                )
        if not spec.validation_plan:
            errors.append("冻结 ModelSpec 必须给出 validation_plan")
        if not spec.failure_conditions:
            errors.append("冻结 ModelSpec 必须给出 failure_conditions")
        if not spec.required_outputs:
            errors.append("冻结 ModelSpec 必须给出 required_outputs")
        if not spec.problem_contract_id or not spec.problem_contract_semantic_hash:
            errors.append("冻结 ModelSpec 必须绑定已冻结 ProblemContract")
        if not spec.requirement_ids:
            errors.append("冻结 ModelSpec 必须声明覆盖的 ReqID")
        decision = spec.method_decision
        candidates = decision.get("candidates") if isinstance(decision, Mapping) else None
        if not isinstance(decision, Mapping) or not str(
            decision.get("selected_route", "")
        ).strip():
            errors.append("冻结 ModelSpec 必须记录 method_decision.selected_route")
        if not isinstance(candidates, list) or not candidates:
            errors.append("冻结 ModelSpec 必须记录 method_decision.candidates")
        elif any(
            not isinstance(item, Mapping)
            or not str(item.get("route", "")).strip()
            or not str(item.get("decision", "")).strip()
            or not str(item.get("reason", "")).strip()
            for item in candidates
        ):
            errors.append("method_decision 每个候选都必须含 route、decision 和 reason")
        if not spec.formulas and not (
            isinstance(spec.objective, Mapping)
            and str(spec.objective.get("formula_id", "")).strip()
        ) and not str(spec.not_applicable_reasons.get("formulas", "")).strip():
            errors.append(
                "冻结 ModelSpec 缺少核心公式；非公式型任务必须给出 formulas 不适用理由"
            )
        for key, reason in spec.not_applicable_reasons.items():
            reason_text = "" if reason is None else str(reason).strip()
            if not reason_text or reason_text.casefold() in {"none", "null"}:
                continue
            if key not in {
                "inputs",
                "outputs",
                "data_contract",
                "solver",
                "randomness",
                "constraints",
                "formulas",
            }:
                errors.append(f"not_applicable_reasons 含未知契约段：{key}")
            elif len(reason_text) < 8:
                errors.append(f"{key} 的不适用理由过短，无法复核")
    formula_ids = [str(item.get("formula_id", "")) for item in spec.formulas]
    constraint_ids = [str(item.get("formula_id", "")) for item in spec.constraints]
    all_ids = formula_ids + constraint_ids
    if any(not item for item in all_ids):
        errors.append("每条公式和约束必须有稳定 formula_id")
    duplicates = sorted({item for item in all_ids if all_ids.count(item) > 1})
    if duplicates:
        errors.append(f"formula_id 重复：{', '.join(duplicates)}")
    parameter_ids = [item.parameter_id for item in spec.parameters]
    duplicates = sorted({item for item in parameter_ids if parameter_ids.count(item) > 1})
    if duplicates:
        errors.append(f"parameter_id 重复：{', '.join(duplicates)}")
    errors.extend(validate_parameter_entries(spec.parameters, formal=False))
    errors.extend(
        _anonymous_collaborator_errors(
            spec.confirmed_members, field_name="confirmed_members"
        )
    )
    return errors


def validate_parameter_entries(
    parameters: Sequence[ParameterEntry], *, formal: bool
) -> list[str]:
    errors: list[str] = []
    for item in parameters:
        prefix = f"参数 {item.parameter_id or item.symbol}"
        if item.category not in PARAMETER_CATEGORIES:
            errors.append(f"{prefix} 分类 {item.category!r} 非法")
            continue
        if not item.parameter_id or not item.symbol or not item.meaning:
            errors.append(f"{prefix} 缺少 ID、符号或含义")
        if not item.unit:
            errors.append(f"{prefix} 缺少单位（无量纲也要显式填写）")
        if item.category == "estimated" and not item.estimation_method:
            errors.append(f"{prefix} 为 estimated，但缺少 estimation_method")
        estimated_text = f"{item.subcategory} {item.estimation_method}".lower()
        if item.category == "estimated" and any(
            marker in estimated_text
            for marker in ("human_set", "manual", "人为", "手工设定", "固定阈值", "固定权重")
        ):
            errors.append(f"{prefix} 的依据表明它是人为设定，不能伪装为 estimated")
        if item.category == "external" and not item.external_source:
            errors.append(f"{prefix} 为 external，但缺少 external_source")
        if item.category == "derived" and not item.derived_from:
            errors.append(f"{prefix} 为 derived，但缺少 derived_from")
        if item.category == "human_set":
            if not item.basis:
                errors.append(f"{prefix} 为 human_set，但缺少设定依据")
            if item.candidate_range is None and item.distribution is None:
                errors.append(f"{prefix} 为 human_set，但缺少合理范围或分布")
            if item.affects_core_conclusion:
                if not item.sensitivity_required:
                    errors.append(f"{prefix} 影响核心结论，必须标记 sensitivity_required")
                if not item.sensitivity_plan:
                    errors.append(f"{prefix} 影响核心结论，但缺少敏感性方案")
                if formal and item.sensitivity_status != "passed":
                    errors.append(f"{prefix} 的正式敏感性分析尚未通过")
                if formal and not item.sensitivity_result:
                    errors.append(f"{prefix} 缺少正式敏感性结果位置")
        if item.boundary_hit and not item.boundary_resolution:
            errors.append(f"{prefix} 命中搜索边界，但未扩展或说明原因")
    return errors


def _numeric_bounds(value: Any) -> tuple[float, float] | None:
    values: list[float] = []
    if isinstance(value, Mapping):
        for key in ("min", "lower", "start", "max", "upper", "end"):
            candidate = value.get(key)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                values.append(float(candidate))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [
            float(item)
            for item in value
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
    elif isinstance(value, str):
        values = [
            float(item)
            for item in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)
        ]
    if len(values) < 2:
        return None
    return min(values), max(values)


def _bind_project_file(
    root: Path,
    path_value: Path | str | None,
    *,
    label: str,
) -> tuple[str, str]:
    if path_value is None or not str(path_value).strip():
        return "", ""
    candidate = Path(path_value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkflowError(f"{label} 必须位于项目目录内。") from exc
    if not resolved.is_file():
        raise WorkflowError(f"{label} 文件不存在：{relative}")
    return relative, sha256_file(resolved)


def _data_manifest_errors(
    root: Path,
    payload: Mapping[str, Any],
    *,
    expected_version: str,
) -> list[str]:
    errors = verify_sealed_record(payload)
    if payload.get("record_type") != "data_manifest":
        errors.append("DataManifest record_type 必须为 data_manifest")
    if str(payload.get("data_version", "")) != expected_version:
        errors.append("DataManifest data_version 与 RunRecord 不一致")
    files = payload.get("files")
    no_data_reason = str(payload.get("no_data_reason", "")).strip()
    if not isinstance(files, list):
        errors.append("DataManifest files 必须是数组")
        files = []
    if not files and len(no_data_reason) < 8:
        errors.append("DataManifest 必须列出输入文件，或给出可复核的 no_data_reason")
    for index, item in enumerate(files, start=1):
        if not isinstance(item, Mapping):
            errors.append(f"DataManifest files[{index}] 不是对象")
            continue
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"DataManifest files[{index}] 路径不安全")
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"DataManifest files[{index}] 越出项目目录")
            continue
        expected_hash = str(item.get("sha256", "")).upper()
        if not candidate.is_file():
            errors.append(f"DataManifest 文件不存在：{relative.as_posix()}")
        elif not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
            errors.append(f"DataManifest SHA-256 无效：{relative.as_posix()}")
        elif sha256_file(candidate) != expected_hash:
            errors.append(f"DataManifest 文件哈希漂移：{relative.as_posix()}")
    return errors


def _code_manifest_errors(
    root: Path,
    payload: Mapping[str, Any],
    *,
    expected_question: str,
    expected_spec_id: str,
    expected_modelspec_hash: str,
    expected_revision: str,
) -> list[str]:
    """Verify the actual source snapshot used by a candidate/formal run."""

    errors = verify_sealed_record(payload)
    if payload.get("record_type") != "code_manifest":
        errors.append("CodeManifest record_type 必须为 code_manifest")
    expected = {
        "question": expected_question,
        "spec_id": expected_spec_id,
        "modelspec_semantic_hash": expected_modelspec_hash.upper(),
        "revision_id": expected_revision,
    }
    for field_name, expected_value in expected.items():
        actual = payload.get(field_name)
        if field_name.endswith("_hash"):
            actual = str(actual or "").upper()
        if actual != expected_value:
            errors.append(f"CodeManifest {field_name} 与 RunRecord 不一致")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        return errors + ["CodeManifest 必须列出至少一个代码文件"]
    for index, item in enumerate(files, start=1):
        if not isinstance(item, Mapping):
            errors.append(f"CodeManifest files[{index}] 不是对象")
            continue
        relative = Path(str(item.get("path", "")))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            errors.append(f"CodeManifest files[{index}] 路径不安全")
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"CodeManifest files[{index}] 越出项目目录")
            continue
        expected_hash = str(item.get("sha256", "")).upper()
        if not candidate.is_file():
            errors.append(f"CodeManifest 文件不存在：{relative.as_posix()}")
        elif not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
            errors.append(f"CodeManifest SHA-256 无效：{relative.as_posix()}")
        elif sha256_file(candidate) != expected_hash:
            errors.append(f"CodeManifest 文件哈希漂移：{relative.as_posix()}")
    return errors


def _repeat_ledger_errors(
    payload: Mapping[str, Any], *, expected_count: int, expected_seed: str
) -> list[str]:
    errors = verify_sealed_record(payload)
    if payload.get("record_type") != "repeat_ledger":
        errors.append("RepeatLedger record_type 必须为 repeat_ledger")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return errors + ["RepeatLedger entries 必须是数组"]
    if len(entries) != expected_count:
        errors.append(
            f"RepeatLedger 重复次数 {len(entries)} 与 RunRecord {expected_count} 不一致"
        )
    indexes: list[int] = []
    for item in entries:
        if not isinstance(item, Mapping):
            errors.append("RepeatLedger 含非对象条目")
            continue
        try:
            indexes.append(int(item.get("repeat_index", 0)))
        except (TypeError, ValueError):
            indexes.append(0)
        if not str(item.get("seed", "")).strip():
            errors.append("RepeatLedger 存在空 seed")
        if str(item.get("status", "")).lower() != "completed":
            errors.append("RepeatLedger 存在未完成重复")
    if sorted(indexes) != list(range(1, expected_count + 1)):
        errors.append("RepeatLedger repeat_index 必须从 1 连续编号")
    if str(payload.get("root_seed", "")) != str(expected_seed):
        errors.append("RepeatLedger root_seed 与 RunRecord seed 不一致")
    return errors


def _run_validation_report_errors(
    root: Path,
    payload: Mapping[str, Any],
    *,
    question: str,
    spec_id: str,
    git_commit: str,
    data_version: str,
    data_hash: str,
    config_hash: str,
    repeat_count: int,
    outputs: Sequence[Mapping[str, str]],
    expected_check_ids: set[str],
) -> list[str]:
    errors = verify_sealed_record(payload)
    if payload.get("record_type") != "run_validation_report":
        errors.append("ValidationReport record_type 必须为 run_validation_report")
    expected = {
        "question": question,
        "spec_id": spec_id,
        "git_commit": git_commit,
        "data_version": data_version,
        "data_hash": data_hash.upper(),
        "config_hash": config_hash.upper(),
        "repeat_count": repeat_count,
    }
    for field_name, expected_value in expected.items():
        actual = payload.get(field_name)
        if field_name.endswith("_hash"):
            actual = str(actual or "").upper()
        if actual != expected_value:
            errors.append(f"ValidationReport {field_name} 与 RunRecord 不一致")
    declared_outputs = payload.get("outputs")
    normalized_expected = [
        {"path": str(item.get("path", "")), "sha256": str(item.get("sha256", "")).upper()}
        for item in outputs
    ]
    normalized_actual = [
        {"path": str(item.get("path", "")), "sha256": str(item.get("sha256", "")).upper()}
        for item in declared_outputs
        if isinstance(item, Mapping)
    ] if isinstance(declared_outputs, list) else []
    if normalized_actual != normalized_expected:
        errors.append("ValidationReport outputs 与 RunRecord 输出集合不一致")
    checks = payload.get("checks")
    observed_check_ids: set[str] = set()
    output_hashes = {
        str(item.get("path", "")): str(item.get("sha256", "")).upper()
        for item in outputs
    }
    if not isinstance(checks, list) or not checks:
        errors.append("ValidationReport 缺少可复核 checks")
    else:
        for item in checks:
            if not isinstance(item, Mapping) or not str(item.get("check_id", "")).strip():
                errors.append("ValidationReport 含无效检查项")
                continue
            check_id = str(item.get("check_id", "")).strip()
            if check_id in observed_check_ids:
                errors.append(f"ValidationReport check_id 重复：{check_id}")
            observed_check_ids.add(check_id)
            status = str(item.get("status", "")).lower()
            if status not in {
                "pass",
                "fail",
                "not_applicable",
            }:
                errors.append("ValidationReport 含非法检查状态")
                continue
            if status == "not_applicable":
                if len(str(item.get("reason", "")).strip()) < 8:
                    errors.append(
                        f"ValidationReport {check_id} 标记 not_applicable 但缺少可复核理由"
                    )
                continue
            if item.get("predeclared") is not True:
                errors.append(
                    f"ValidationReport {check_id} 必须标记 predeclared=true"
                )
            if len(str(item.get("criterion", "")).strip()) < 8:
                errors.append(
                    f"ValidationReport {check_id} 缺少预先确定的通过标准"
                )
            raw_evidence = item.get("evidence")
            evidence_refs = (
                [str(value).strip() for value in raw_evidence]
                if isinstance(raw_evidence, list)
                else [str(raw_evidence or "").strip()]
            )
            evidence_refs = [value for value in evidence_refs if value]
            if not evidence_refs:
                errors.append(f"ValidationReport {check_id} 缺少实际证据文件")
            for reference in evidence_refs:
                evidence_path, path_error = _project_reference_path(root, reference)
                if path_error:
                    errors.append(f"ValidationReport {check_id} evidence {path_error}")
                    continue
                if evidence_path is None or not evidence_path.is_file():
                    errors.append(
                        f"ValidationReport {check_id} evidence 文件不存在：{reference}"
                    )
                    continue
                relative = evidence_path.relative_to(root).as_posix()
                if relative in output_hashes:
                    if sha256_file(evidence_path) != output_hashes[relative]:
                        errors.append(
                            f"ValidationReport {check_id} evidence 输出哈希不一致：{relative}"
                        )
                    continue
                hash_match = re.search(
                    r"#sha256=([0-9A-Fa-f]{64})(?:$|[#&])", reference
                )
                if hash_match is None:
                    errors.append(
                        f"ValidationReport {check_id} 的非输出 evidence 必须绑定 SHA-256：{reference}"
                    )
                elif sha256_file(evidence_path) != hash_match.group(1).upper():
                    errors.append(
                        f"ValidationReport {check_id} evidence SHA-256 不匹配：{reference}"
                    )
    missing_planned = sorted(expected_check_ids - observed_check_ids)
    if missing_planned:
        errors.append(
            "ValidationReport 未覆盖 ModelSpec validation_plan："
            + ", ".join(missing_planned)
        )
    declared_status = str(payload.get("status", "")).lower()
    failed_checks = [
        item
        for item in checks or []
        if isinstance(item, Mapping) and str(item.get("status", "")).lower() == "fail"
    ]
    if declared_status in {"pass", "passed", "ready"} and failed_checks:
        errors.append("ValidationReport 自报通过但仍含失败检查")
    passed_checks = [
        item
        for item in checks or []
        if isinstance(item, Mapping) and str(item.get("status", "")).lower() == "pass"
    ]
    if declared_status in {"pass", "passed", "ready"} and not passed_checks:
        errors.append("ValidationReport 自报通过但没有任何实质 pass 检查")
    if declared_status not in {"pass", "passed", "ready", "fail", "failed", "pending"}:
        errors.append("ValidationReport status 非法")
    return errors


REFERENCE_PATH_RE = re.compile(
    r"^(.*?\.(?:csv|tsv|xlsx|xls|json|jsonl|yaml|yml|parquet|txt|md|"
    r"py|r|m|jl|ipynb|png|svg|pdf|docx))(?:[:#].*)?$",
    re.I,
)


def _project_reference_path(root: Path, reference: str) -> tuple[Path | None, str]:
    text = str(reference).strip()
    match = REFERENCE_PATH_RE.match(text)
    if not match:
        return None, ""
    relative = Path(match.group(1))
    if relative.is_absolute() or ".." in relative.parts:
        return None, "引用路径不是安全相对路径"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "引用路径越出项目目录"
    return candidate, ""


def _record_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex.upper()}"


@dataclass
class RequirementEntry:
    req_id: str
    question: str
    source_anchor: str
    requested_action: str
    outputs: list[str]
    acceptance_evidence: list[str]
    inputs: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    precision: str = ""
    quantity_roles: dict[str, list[str]] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    downstream_questions: list[str] = field(default_factory=list)
    not_applicable_reasons: dict[str, str] = field(default_factory=dict)
    status: str = "active"
    stable_id: str = field(default_factory=lambda: _record_id("REQOBJ"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementEntry":
        source = dict(value)
        unknown = sorted(set(source) - set(cls.__dataclass_fields__))
        if unknown:
            raise WorkflowError("RequirementEntry 含未知字段：" + ", ".join(unknown))
        return cls(**source)


@dataclass
class ProblemContract:
    question: str
    title: str
    requirements: list[RequirementEntry]
    source_files: list[dict[str, Any]] = field(default_factory=list)
    contract_id: str = ""
    revision: int = 1
    status: str = "draft"
    parent_contract_id: str = ""
    parent_semantic_hash: str = ""
    frozen_by: list[str] = field(default_factory=list)
    frozen_at: str = ""
    stable_id: str = field(default_factory=lambda: _record_id("PCOBJ"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["requirements"] = [item.to_dict() for item in self.requirements]
        return seal_record(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProblemContract":
        source = dict(value)
        source["requirements"] = [
            item if isinstance(item, RequirementEntry) else RequirementEntry.from_dict(item)
            for item in source.get("requirements", [])
        ]
        unknown = sorted(set(source) - set(cls.__dataclass_fields__))
        if unknown:
            raise WorkflowError("ProblemContract 含未知字段：" + ", ".join(unknown))
        return cls(**source)


@dataclass
class AmbiguityEntry:
    ambiguity_id: str
    question: str
    source_anchor: str
    interpretations: list[str]
    severity: str
    impact: str
    owner: str
    status: str = "open"
    resolution: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    legacy_sources: list[dict[str, Any]] = field(default_factory=list)
    event_type: str = "added"
    parent_record_hash: str = ""
    timestamp: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: _record_id("AMB"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))


@dataclass
class AssumptionEntry:
    assumption_id: str
    question: str
    statement: str
    rationale: str
    impact: str
    testability: str
    linked_ambiguity_ids: list[str] = field(default_factory=list)
    linked_requirement_ids: list[str] = field(default_factory=list)
    reversible: bool = True
    validation_refs: list[str] = field(default_factory=list)
    sensitivity_required: bool = False
    status: str = "proposed"
    reviewed_by: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    validation_plan: str = ""
    validation_checks: list[str] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    legacy_sources: list[dict[str, Any]] = field(default_factory=list)
    event_type: str = "added"
    parent_record_hash: str = ""
    timestamp: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: _record_id("ASM"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))


@dataclass
class HumanDecisionEntry:
    decision_id: str
    question: str
    decision_type: str
    selected_option: str
    rationale: str
    alternatives: list[str]
    evidence_refs: list[str]
    proposed_by: str = "assistant"
    origin: str = "ai_assisted"
    status: str = "proposed"
    confirmed_by: list[str] = field(default_factory=list)
    confirmation_note: str = ""
    event_type: str = "recorded"
    supersedes: str = ""
    parent_record_hash: str = ""
    stale_reason: str = ""
    timestamp: str = field(default_factory=utc_now)
    stable_id: str = field(default_factory=lambda: _record_id("DEC"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))


@dataclass
class AuditFinding:
    finding_id: str
    audit_kind: str
    check_id: str
    severity: str
    status: str
    source: str
    consumer: str
    evidence: str
    remediation: str = ""
    question: str = ""
    stable_id: str = field(default_factory=lambda: _record_id("FIND"))
    schema_version: str = SCHEMA_VERSION
    semantic_hash: str = ""
    record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return seal_record(asdict(self))


def _validation_plan_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    checks = payload.get("checks", [])
    if not isinstance(checks, list) or not checks:
        return ["ValidationPlan 至少需要一个检查项"]
    ids: set[str] = set()
    for item in checks:
        if not isinstance(item, Mapping):
            errors.append("ValidationPlan check 必须是对象")
            continue
        check_id = str(item.get("check_id", "")).strip()
        if not check_id:
            errors.append("ValidationPlan check 缺少 check_id")
        elif check_id in ids:
            errors.append(f"ValidationPlan check_id 重复：{check_id}")
        ids.add(check_id)
        applicability = str(item.get("applicability", "required"))
        if applicability not in {"required", "optional", "not_applicable"}:
            errors.append(f"{check_id} applicability 非法")
        if applicability == "not_applicable" and len(str(item.get("not_applicable_reason", "")).strip()) < 8:
            errors.append(f"{check_id} 的 not_applicable 必须给出可复核理由")
        if applicability != "not_applicable" and not str(item.get("method", "")).strip():
            errors.append(f"{check_id} 缺少 method")
    return errors


def _contract_validation_errors(
    root: Path, contract: ProblemContract, *, for_freeze: bool,
    ambiguities: Sequence[Mapping[str, Any]] = (), assumptions: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    errors: list[str] = []
    question = normalize_question(contract.question)
    if not contract.title.strip():
        errors.append("ProblemContract 缺少 title")
    if not contract.source_files:
        errors.append("ProblemContract 缺少题面来源文件")
    for index, source in enumerate(contract.source_files, 1):
        if not isinstance(source, Mapping):
            errors.append(f"ProblemContract source_files[{index}] 必须是对象")
            continue
        reference = str(source.get("path", "")).strip()
        expected_hash = str(source.get("sha256", "")).strip().upper()
        source_kind = str(
            source.get("source_kind", source.get("source_role", ""))
        ).strip()
        if not reference:
            errors.append(f"ProblemContract source_files[{index}] 缺少 path")
            continue
        if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
            errors.append(f"ProblemContract source_files[{index}] 缺少有效 SHA-256")
        if not source_kind:
            errors.append(f"ProblemContract source_files[{index}] 缺少 source_kind/source_role")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", reference):
            continue
        candidate = Path(reference)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"ProblemContract source_files[{index}] 不是安全项目相对路径")
            continue
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            errors.append(f"ProblemContract source_files[{index}] 越出项目目录")
            continue
        if not resolved.is_file():
            errors.append(f"ProblemContract 题面来源文件不存在：{reference}")
        elif re.fullmatch(r"[0-9A-F]{64}", expected_hash) and sha256_file(resolved) != expected_hash:
            errors.append(f"ProblemContract 题面来源 SHA-256 漂移：{reference}")
    if not contract.requirements:
        errors.append("ProblemContract 至少需要一条 RequirementEntry")
    seen: set[str] = set()
    for entry in contract.requirements:
        if entry.req_id in seen:
            errors.append(f"ReqID 重复：{entry.req_id}")
        seen.add(entry.req_id)
        if normalize_question(entry.question) != question:
            errors.append(f"{entry.req_id} 的 question 与合同不一致")
        if not re.fullmatch(rf"REQ-{re.escape(question)}-[0-9]{{3,}}", entry.req_id):
            errors.append(f"ReqID 格式错误：{entry.req_id}")
        if not entry.source_anchor.strip():
            errors.append(f"{entry.req_id} 缺少 source_anchor")
        if not entry.requested_action.strip():
            errors.append(f"{entry.req_id} 缺少 requested_action")
        if not entry.outputs:
            errors.append(f"{entry.req_id} 缺少 outputs")
        if not entry.acceptance_evidence:
            errors.append(f"{entry.req_id} 缺少 acceptance_evidence")
        unit_reason = str(entry.not_applicable_reasons.get("units", "")).strip()
        if not entry.units and len(unit_reason) < 8:
            errors.append(f"{entry.req_id} 缺少 units 或可复核的不适用理由")
        roles = entry.quantity_roles
        unknown_roles = sorted(set(roles) - {"fixed", "observed", "decision", "derived"})
        if unknown_roles:
            errors.append(f"{entry.req_id} quantity_roles 含未知类别：{', '.join(unknown_roles)}")
    if for_freeze:
        assumption_by_ambiguity: dict[str, list[dict[str, Any]]] = {}
        for assumption in assumptions:
            for ambiguity_id in assumption.get("linked_ambiguity_ids", []):
                assumption_by_ambiguity.setdefault(str(ambiguity_id), []).append(assumption)
        for ambiguity in ambiguities:
            if ambiguity.get("status") == "resolved":
                continue
            ambiguity_id = str(ambiguity.get("ambiguity_id", ""))
            severity = str(ambiguity.get("severity", ""))
            if severity in {"high", "critical"}:
                errors.append(f"高影响题意歧义未解决：{ambiguity_id}")
                continue
            linked = assumption_by_ambiguity.get(ambiguity_id, [])
            acceptable = any(
                item.get("status") in {"accepted", "validated"}
                and item.get("reversible") is True
                and (item.get("validation_refs") or item.get("sensitivity_required")
                     or item.get("validation_checks") and item.get("validation_plan"))
                for item in linked
            )
            if not acceptable:
                errors.append(
                    f"低/中影响歧义 {ambiguity_id} 必须关联已接受、可逆且进入验证或敏感性分析的假设"
                )
    return errors


def impact_analysis(edges: Sequence[Mapping[str, Any]], source_id: str) -> dict[str, Any]:
    """Traverse declared invalidating edges without changing the state."""
    queue = [source_id]
    visited = {source_id}
    impacted: list[dict[str, Any]] = []
    while queue:
        current = queue.pop(0)
        for edge in edges:
            if edge.get("from_id") != current or not edge.get("invalidates", True):
                continue
            target = str(edge.get("to_id"))
            if target in visited:
                continue
            visited.add(target)
            queue.append(target)
            impacted.append(
                {
                    "id": target,
                    "type": edge.get("to_type"),
                    "via": edge.get("stable_id"),
                    "relation": edge.get("relation"),
                }
            )
    return {"source_id": source_id, "impacted": impacted}


def _validate_data_contract(
    root: Path, inventory: Mapping[str, Any] | None,
    passport: Mapping[str, Any], split: Mapping[str, Any], *,
    assumptions: Sequence[Mapping[str, Any]] = (), formal: bool = False,
) -> list[str]:
    root = Path(root).resolve()
    errors: list[str] = []
    for label, payload in (("DatasetPassport", passport), ("DataSplitPlan", split)):
        if not payload:
            errors.append(f"缺少 {label}")
        else:
            errors.extend(f"{label}: {item}" for item in verify_sealed_record(payload))
    if passport.get("applicability") != "not_applicable":
        for name in ("fields", "observation_unit", "missing_policy", "outlier_policy"):
            if not passport.get(name):
                errors.append(f"DatasetPassport 缺少：{name}")
    if split.get("applicability") != "not_applicable":
        for name in ("strategy", "split_unit", "preprocessing_scope", "leakage_controls"):
            if not split.get(name):
                errors.append(f"DataSplitPlan 缺少：{name}")
    passport_na = passport.get("applicability") == "not_applicable"
    split_na = split.get("applicability") == "not_applicable"
    for label, payload in (("DatasetPassport", passport), ("DataSplitPlan", split)):
        if payload.get("applicability") == "not_applicable" and len(str(payload.get("not_applicable_reason", "")).strip()) < 8:
            errors.append(f"{label} 的 not_applicable 必须给出可复核理由")
    if passport_na and not split_na:
        errors.append("没有数据时不能声明适用的训练/测试切分")
    if split_na:
        if any(split.get(key) for key in ("train_entities", "test_entities", "train_time_range", "test_time_range")):
            errors.append("不适用切分与已声明的训练/测试记录冲突")
        if not passport_na and split.get("evaluation_target") not in {"deterministic_computation", "descriptive_analysis"}:
            errors.append("有数据但不切分时须明确 deterministic_computation 或 descriptive_analysis 的结论范围")
        if not passport_na and (
            split.get("claims_new_entity_generalization") is not False
            or split.get("claims_predictive_performance") is not False
        ):
            errors.append("不切分不能声称新主体泛化或预测性能；须显式声明两者为 false")
    if not passport_na and not inventory:
        errors.append("缺少 RawDataInventory")
    elif inventory:
        errors.extend(f"RawDataInventory: {item}" for item in verify_sealed_record(inventory))
    if inventory:
        for entry in inventory.get("entries", []):
            source, source_error = _project_reference_path(root, str(entry.get("path", "")))
            if source_error or source is None:
                errors.append(f"RawDataInventory 路径不安全：{entry.get('path')} {source_error}")
                continue
            if not source.is_file():
                errors.append(f"原始数据文件丢失：{entry.get('path')}")
                continue
            actual = sha256_file(source)
            if actual != str(entry.get("sha256", "")).upper():
                errors.append(f"原始数据漂移：{entry.get('path')}")
    repeated = bool(passport.get("repeated_measurements"))
    entity_id = str(passport.get("entity_id", "")).strip()
    strategy = str(split.get("strategy", "")).strip().lower()
    split_unit = str(split.get("split_unit", "")).strip()
    continuation = split.get("evaluation_target") == "future_observations_same_entities"
    if repeated and not split_na:
        if not entity_id:
            errors.append("重复测量 DatasetPassport 缺少 entity_id")
        if not continuation and (strategy in {"random_row", "row_random", "random"} or split_unit != entity_id):
            errors.append("重复测量数据必须按 entity_id 分组切分，禁止逐行随机切分")
    train_entities = {str(item) for item in split.get("train_entities", [])}
    test_entities = {str(item) for item in split.get("test_entities", [])}
    overlap = sorted(train_entities & test_entities)
    if continuation and not split_na:
        from copilot_model_evidence import temporal_split_errors
        errors.extend(temporal_split_errors(split, train_entities, test_entities))
    elif overlap:
        errors.append("训练集与测试集 entity 重叠：" + ", ".join(overlap[:10]))
    if not split_na or 'preprocessing_steps' in split:
        from copilot_model_evidence import preprocessing_scope_errors
        errors.extend(preprocessing_scope_errors(split))
    if formal:
        for assumption in assumptions:
            if assumption.get("status") in {"rejected", "superseded"}:
                continue
            if (assumption.get("validation_refs") or assumption.get("sensitivity_required")) and assumption.get("status") != "validated":
                errors.append(f"假设尚未完成验证：{assumption.get('assumption_id')}")
    return errors


def validate_problem_contract(
    root: Path, payload: ProblemContract | Mapping[str, Any], *,
    ambiguities: Sequence[Mapping[str, Any]] = (),
    assumptions: Sequence[Mapping[str, Any]] = (),
    for_freeze: bool = False,
) -> list[str]:
    """Validate original contract fields, with registers supplied by the Store."""
    try:
        contract = payload if isinstance(payload, ProblemContract) else ProblemContract.from_dict(payload)
        errors = []
        for name in ("source_files", "requirements"):
            if not isinstance(getattr(contract, name), list):
                errors.append(f"ProblemContract {name} 必须是数组")
        for entry in contract.requirements:
            for name in ("inputs", "outputs", "units", "constraints", "acceptance_evidence", "downstream_questions"):
                values = getattr(entry, name)
                if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
                    errors.append(f"{entry.req_id} {name} 必须是非空字符串组成的数组")
            if not isinstance(entry.quantity_roles, Mapping) or not isinstance(entry.not_applicable_reasons, Mapping):
                errors.append(f"{entry.req_id} quantity_roles/not_applicable_reasons 必须是对象")
        if errors:
            return errors
        return _contract_validation_errors(
            Path(root).resolve(), contract, for_freeze=for_freeze,
            ambiguities=ambiguities, assumptions=assumptions,
        )
    except (TypeError, ValueError, AttributeError, KeyError, WorkflowError) as exc:
        return [f"ProblemContract 字段类型或结构无效：{exc}"]


def validate_data_contract(
    root: Path, inventory: Mapping[str, Any] | None,
    passport: Mapping[str, Any], split: Mapping[str, Any], *,
    assumptions: Sequence[Mapping[str, Any]] = (), formal: bool = False,
) -> list[str]:
    """Validate sealed original inventory/passport/split payloads; read-only."""
    try:
        return _validate_data_contract(root, inventory, passport, split,
                                       assumptions=assumptions, formal=formal)
    except (TypeError, ValueError, AttributeError, KeyError, WorkflowError) as exc:
        return [f"Data Contract 字段类型或结构无效：{exc}"]


def validate_validation_plan(payload: Mapping[str, Any]) -> list[str]:
    """Validate the existing ValidationPlan contract, without registering it."""
    try:
        return _validation_plan_errors(payload)
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        return [f"ValidationPlan 字段类型或结构无效：{exc}"]


def validate_run_report(
    root: Path, payload: Mapping[str, Any],
    run: RunRecord | Mapping[str, Any], expected_check_ids: Iterable[str] = (),
) -> list[str]:
    """Check sealed report bindings; a valid failure report still has status fail.

    Callers must separately require the report's passing status before promotion.
    Deserialization never supplies proof that a command actually executed.
    """
    try:
        record = run if isinstance(run, RunRecord) else RunRecord.from_dict(run)
        errors = _run_validation_report_errors(
            Path(root).resolve(), payload, question=record.question,
            spec_id=record.spec_id, git_commit=record.git_commit,
            data_version=record.data_version, data_hash=record.data_hash,
            config_hash=record.config_hash, repeat_count=record.repeat_count,
            outputs=record.outputs, expected_check_ids=set(expected_check_ids),
        )
        for key in ("code_manifest_id", "code_manifest_hash"):
            expected = getattr(record, key)
            if expected and payload.get(key) != expected:
                errors.append(f"ValidationReport {key} 与 RunRecord 不一致")
        return errors
    except (TypeError, ValueError, AttributeError, KeyError, WorkflowError) as exc:
        return [f"ValidationReport 字段类型或结构无效：{exc}"]


# Compatibility-free public names for the original read-only manifest validators.
validate_data_manifest = _data_manifest_errors
validate_code_manifest = _code_manifest_errors
validate_repeat_ledger = _repeat_ledger_errors
project_reference_path = _project_reference_path
bind_project_file = _bind_project_file



def _evidence_reference_errors(
    root: Path, claim: EvidenceMapEntry, run_payload: Mapping[str, Any], *,
    formal_question: str, promotion_errors: Sequence[str] = (),
) -> list[str]:
    errors: list[str] = []
    data_version = str(run_payload.get("data_version", ""))
    data_hash = str(run_payload.get("data_hash", "")).upper()
    run_output_paths = {
        str(item.get("path", ""))
        for item in run_payload.get("outputs", [])
        if isinstance(item, Mapping)
    }
    valid_data_tokens = {
        data_version,
        data_hash,
        f"{data_version}#sha256={data_hash}",
    }
    for reference in claim.data_sources:
        text = str(reference).strip()
        if text in valid_data_tokens:
            continue
        path, path_error = _project_reference_path(root, text)
        if path_error:
            errors.append(f"{claim.claim_id} data source {path_error}：{text}")
            continue
        hash_match = re.search(r"#sha256=([0-9A-Fa-f]{64})(?:$|[#&])", text)
        if path is None or not path.is_file() or hash_match is None:
            errors.append(
                f"{claim.claim_id} data source 必须绑定 formal data 版本/哈希或项目内文件哈希：{text}"
            )
        elif sha256_file(path) != hash_match.group(1).upper():
            errors.append(f"{claim.claim_id} data source SHA-256 不匹配：{text}")
        elif hash_match.group(1).upper() != data_hash:
            errors.append(f"{claim.claim_id} data source 未绑定 formal run data_hash：{text}")
    for reference in claim.code_locations:
        text = str(reference).strip()
        path, path_error = _project_reference_path(root, text)
        if path_error:
            errors.append(f"{claim.claim_id} code location {path_error}：{text}")
        elif path is None or not path.is_file():
            errors.append(f"{claim.claim_id} code location 文件不存在：{text}")
    for field_name, references in (("table", claim.tables), ("figure", claim.figures)):
        for reference in references:
            text = str(reference).strip()
            path, path_error = _project_reference_path(root, text)
            if path_error:
                errors.append(f"{claim.claim_id} {field_name} {path_error}：{text}")
            elif path is None or not path.is_file():
                errors.append(f"{claim.claim_id} {field_name} 文件不存在：{text}")
            elif field_name == "table":
                relative = path.relative_to(root.resolve()).as_posix()
                if relative not in run_output_paths:
                    errors.append(
                        f"{claim.claim_id} table 不是所绑定 formal run 的输出：{text}"
                    )
    formal_gate_id = f"{formal_question}.run.formal"
    for reference in claim.validation_evidence:
        text = str(reference).strip()
        if text == formal_gate_id:
            if promotion_errors:
                errors.append(
                    f"{claim.claim_id} validation gate 未通过："
                    + "；".join(promotion_errors)
                )
            continue
        path, path_error = _project_reference_path(root, text)
        if path_error:
            errors.append(f"{claim.claim_id} validation evidence {path_error}：{text}")
        elif path is None or not path.is_file():
            errors.append(f"{claim.claim_id} validation evidence 不存在：{text}")
        elif path.suffix.lower() in {".json", ".yaml", ".yml"}:
            try:
                validation_payload = load_structured(path)
            except (OSError, WorkflowError) as exc:
                errors.append(
                    f"{claim.claim_id} validation evidence 无法解析：{text}：{exc}"
                )
            else:
                validation_errors = verify_sealed_record(validation_payload)
                if validation_errors:
                    errors.append(
                        f"{claim.claim_id} validation evidence 未密封："
                        + "；".join(validation_errors)
                    )
                if str(validation_payload.get("status", "")).lower() not in {
                    "ready",
                    "pass",
                    "passed",
                }:
                    errors.append(
                        f"{claim.claim_id} validation evidence 状态未通过：{text}"
                    )
        else:
            hash_match = re.search(
                r"#sha256=([0-9A-Fa-f]{64})(?:$|[#&])", text
            )
            if hash_match is None or sha256_file(path) != hash_match.group(1).upper():
                errors.append(
                    f"{claim.claim_id} 非结构化 validation evidence 必须绑定当前 SHA-256：{text}"
                )
    return errors


def validate_evidence_entry(
    root: Path, payload: EvidenceMapEntry | Mapping[str, Any],
    run: RunRecord | Mapping[str, Any] | None, *,
    run_is_current_verified: bool,
    run_integrity_errors: Sequence[str] = (),
    verified_literature_ids: Iterable[str] = (),
) -> list[str]:
    """Apply original EvidenceMap checks to a Store-selected run.

    The caller supplies currentness and actual validation from the authoritative
    state. A claim's own status or a RunRecord's defaults cannot establish them.
    """
    try:
        claim = payload if isinstance(payload, EvidenceMapEntry) else EvidenceMapEntry.from_dict(payload)
        run_payload = run.to_dict() if isinstance(run, RunRecord) else dict(run or {})
        errors = list(run_integrity_errors)
        if not claim.claim_id.strip() or not claim.claim.strip():
            errors.append("EvidenceMap 缺少 claim_id 或 claim")
        if claim.claim_type not in {"numerical", "model", "method", "theory", "limitation"}:
            errors.append(f"{claim.claim_id} claim_type 非法")
        if not claim.paper_anchor.strip():
            errors.append(f"{claim.claim_id} 缺少 paper_anchor")
        run_bound_type = claim.claim_type in {"numerical", "model", "method"}
        if run_bound_type or claim.formal_run_id:
            if not run_is_current_verified or not run_payload:
                errors.append(f"{claim.claim_id} 未绑定当前已核验 run_id")
            elif claim.formal_run_id != run_payload.get("run_id", run_payload.get("stable_id")):
                errors.append(f"{claim.claim_id} formal_run_id 与选定运行不一致")
            else:
                errors.extend(verify_sealed_record(run_payload))
                if run_payload.get("status") != "completed":
                    errors.append(f"{claim.claim_id} 运行未成功完成")
        if run_bound_type and (not claim.data_sources or not claim.code_locations or not claim.validation_evidence):
            errors.append(f"{claim.claim_id} 的数据、代码或验证证据不完整")
        if claim.claim_type == "numerical" and not claim.tables and not claim.figures:
            errors.append(f"{claim.claim_id} 的数值结论至少需要一个表格或图件证据")
        if claim.claim_type in {"theory", "limitation"} and not (claim.data_sources or claim.validation_evidence or claim.formula_ids):
            errors.append(f"{claim.claim_id} 缺少理论、证据或公式依据")
        if claim.status != "pass":
            errors.append(f"{claim.claim_id} 状态不是 pass")
        missing_literature = sorted(set(claim.literature_sources) - set(verified_literature_ids))
        if missing_literature:
            errors.append(f"{claim.claim_id} 文献未完成内容核验：{', '.join(missing_literature)}")
        if run_payload and claim.formal_run_id:
            root = Path(root).resolve()
            for output in run_payload.get("outputs", []):
                path, path_error = project_reference_path(root, str(output.get("path", "")))
                if path_error or path is None or not path.is_file():
                    errors.append(f"{claim.claim_id} 运行输出丢失或路径不安全")
                elif sha256_file(path) != str(output.get("sha256", "")).upper():
                    errors.append(f"{claim.claim_id} 运行输出哈希漂移")
            errors.extend(_evidence_reference_errors(
                root, claim, run_payload, formal_question=str(run_payload.get("question", "")),
                promotion_errors=run_integrity_errors,
            ))
        return errors
    except (TypeError, ValueError, AttributeError, KeyError, WorkflowError) as exc:
        return [f"EvidenceMap 字段类型或结构无效：{exc}"]



PARAMETER_CONTRACT_FIELDS = (
    "symbol",
    "meaning",
    "unit",
    "category",
    "subcategory",
    "candidate_range",
    "distribution",
    "basis",
    "estimation_method",
    "data_scope",
    "external_source",
    "formula_ids",
    "code_variable",
    "code_location",
    "affects_core_conclusion",
    "sensitivity_required",
    "sensitivity_plan",
    "boundary_hit",
    "boundary_resolution",
    "derived_from",
)


def _parameter_contract_errors(
    expected: Sequence[ParameterEntry], actual: Sequence[ParameterEntry]
) -> list[str]:
    errors: list[str] = []
    expected_ids = [item.parameter_id for item in expected]
    actual_ids = [item.parameter_id for item in actual]
    duplicate_ids = sorted(
        {item for item in actual_ids if item and actual_ids.count(item) > 1}
    )
    if duplicate_ids:
        errors.append("ParameterSet parameter_id 重复：" + ", ".join(duplicate_ids))
    missing = sorted(set(expected_ids) - set(actual_ids))
    extra = sorted(set(actual_ids) - set(expected_ids))
    if missing:
        errors.append("ParameterSet 缺少 ModelSpec 参数：" + ", ".join(missing))
    if extra:
        errors.append("ParameterSet 含 ModelSpec 未声明参数：" + ", ".join(extra))
    expected_by_id = {item.parameter_id: item for item in expected}
    actual_by_id = {item.parameter_id: item for item in actual}
    for parameter_id in sorted(set(expected_by_id) & set(actual_by_id)):
        expected_item = expected_by_id[parameter_id]
        actual_item = actual_by_id[parameter_id]
        for field_name in PARAMETER_CONTRACT_FIELDS:
            if canonical_json(getattr(expected_item, field_name)) != canonical_json(
                getattr(actual_item, field_name)
            ):
                errors.append(
                    f"参数 {parameter_id} 的 {field_name} 与冻结 ModelSpec 不一致"
                )
    return errors


validate_parameter_contract = _parameter_contract_errors
