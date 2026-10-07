"""MathModel Copilot runtime, built around the existing decision-log authority.

Domain records and validators are migrated from cumcm-workflow. This module
adds tasks, managed execution and projections; it never treats Critic as proof.
"""
from __future__ import annotations

import copy
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
import unicodedata
from decimal import Decimal
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from copilot_store import Store, ConflictError, IntegrityError, digest, atomic_write, utc_now
import copilot_domain as domain

SOURCE_KINDS = {"ProblemContract", "ModelSpec", "ParameterSet", "DataContract", "CodeManifest", "ValidationPlan"}
ROLES = {"modeler", "coder", "writer", "integrator", "qa"}
_OBSERVATION = ContextVar("copilot_object_observation", default=None)


@contextmanager
def _observation(root, cp):
    """Reuse completed object checks within one synchronous observation only.

    This is not a revision/file cache. Every new public check reads actual
    files again. Different authorities/roots and exceptions cannot leak reuse.
    """
    parent = _OBSERVATION.get()
    identity = str(root)
    if parent is not None and parent["cp"] is cp and parent["root"] == identity:
        yield parent
        return
    current = {"cp": cp, "root": identity, "complete": {}, "active": set()}
    token = _OBSERVATION.set(current)
    try:
        yield current
    finally:
        _OBSERVATION.reset(token)


def numeric_tokens(text):
    normalized = unicodedata.normalize("NFKC", text).translate(str.maketrans({char: "-" for char in "−–—‐‑‒"}))
    # Presentation whitespace must not silently discard a negative sign,
    # exponent, or percent scale and bind a different numerical value.
    normalized = re.sub(r"(\d(?:\.\d*)?|\.\d+)\s*[eE]\s*([+-]?)\s*(\d+)", r"\1e\2\3", normalized)
    normalized = re.sub(r"([+-])\s+(?=\d|\.\d)", r"\1", normalized)
    normalized = re.sub(r"(?<=\d)\s+%", "%", normalized)
    # Adjacent arithmetic/range operators separate literals. Never let a
    # boundary assertion silently discard the right-hand value (10-999).
    # Exponent signs follow e/E and therefore are not changed here.
    normalized = re.sub(r"(?<=\d)[+-](?=\d|\.\d)", " ", normalized)
    if re.search(r"\d,\d", normalized):
        raise ValueError("数值主张请使用无千位分隔符的十进制写法")
    return re.findall(r"(?:[-+]|(?<![A-Za-z0-9_.]))(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?%?", normalized)


def claim_assurance(cp, payload, result_ids):
    """Recompute content support from checked results; labels confer no trust.

    A note can be registered without asserting that it is an experimental
    finding. Qualitative findings need an exact statement actually returned in
    checked metrics. Numeric findings need every literal bound to numeric
    metrics. Neither binding is a proof of arbitrary natural-language inference.
    """
    def leaves(value, path=""):
        if isinstance(value, dict):
            return [item for key, child in value.items() for item in leaves(child, path + "." + str(key))]
        if isinstance(value, list):
            return [item for i, child in enumerate(value) for item in leaves(child, path + f"[{i}]")]
        return [(path, value)]

    from copilot_display import validate_display_contracts
    displayed = validate_display_contracts(cp, result_ids, payload.get("display_contracts", []))
    metrics = [(rid, path, value) for rid in result_ids
               for path, value in leaves(cp["objects"].get(rid, {}).get("payload", {}).get("metrics", {}))]
    tokens = numeric_tokens(payload["claim"])
    if any(binding["text"] not in tokens for binding in displayed):
        raise ValueError("Display contract must bind a literal actually present in the Claim")
    bindings, unbound = [], []
    for token in tokens:
        explicit = [item for item in displayed if item["text"] == token]
        if explicit:
            bindings.extend(explicit)
            continue
        value = float(token.rstrip("%")) / (100 if token.endswith("%") else 1)
        matches = [{"result_id": rid, "metric_path": path, "value": observed}
                   for rid, path, observed in metrics
                   if type(observed) in (int, float) and math.isfinite(observed) and math.isfinite(value)
                   and math.isclose(value, observed, rel_tol=1e-9, abs_tol=1e-12)]
        if matches:
            bindings.append({"text": token, "sources": matches})
        else:
            unbound.append(token)
    statements = [{"result_id": rid, "metric_path": path, "value": value}
                  for rid, path, value in metrics if isinstance(value, str)
                  and value.strip() == payload["claim"].strip()]
    verified = bool(tokens) and not unbound or not tokens and bool(statements)
    rounded = any(Decimal(item["rounding_delta"]) != 0 for item in displayed)
    comparison = rounded and bool(re.search(
        r"[<>≤≥]|大于|小于|不低于|不高于|不少于|不多于|至少|至多|超过|阈值|"
        r"\b(?:greater than|less than|at least|at most|above|below|threshold)\b",
        unicodedata.normalize("NFKC", payload["claim"]), re.I))
    comparison_sources = {item["display_contract"]["result_id"] for item in displayed if Decimal(item["rounding_delta"]) != 0}
    comparison_checked = comparison_sources <= {item["result_id"] for item in statements}
    if comparison and not comparison_checked:
        verified = False
    return {"version": "0.1.2", "verified": verified,
            "numeric_bindings": bindings, "statement_bindings": statements,
            "unbound_numbers": unbound,
            "comparison_status": "bound_to_checker_statement" if comparison and comparison_checked else "checked_statement_required" if comparison else "not_present",
            "numeric_status": "bound" if tokens and not unbound else "pending_source" if tokens else "not_present",
            "scope": "checked_result_content" if verified else "registered_note_pending_source_or_review",
            "semantic_review": "not_performed"}


def claim_evidence_errors(root, cp, payload, result_ids):
    """Shared registration/consumption gate, including legacy v0.1 claims."""
    try:
        entry = domain.EvidenceMapEntry.from_dict(payload)
        if not result_ids or any(cp["objects"].get(x, {}).get("kind") != "ResultRecord"
                                 or cp["objects"][x].get("status") != "verified" for x in result_ids):
            return ["unsupported claim: 缺少已验证 Result"]
        runs = [cp["objects"][x]["payload"]["run_id"] for x in result_ids]
        if entry.formal_run_id not in runs:
            return ["Claim 的 formal_run_id 与 Result 来源不一致"]
        run = cp["objects"][entry.formal_run_id]["payload"]
        if not entry.requirement_ids or any(r not in cp["requirements"] or cp["requirements"][r]["question"] != run["question"]
                                            for r in entry.requirement_ids):
            return ["Claim 必须绑定真实运行所属小问的 Requirement"]
        if not set(entry.requirement_ids) <= evidence_requirements(cp, entry.formal_run_id):
            return ["Claim 超出实际运行模型声明的 Requirement"]
        if any(run["question"] not in evidence_questions(cp, rid)
               or not set(entry.requirement_ids) <= evidence_requirements(cp, rid) for rid in result_ids):
            return ["Claim 的每个 Result 必须支持相同问题和具体 Requirement；跨问比较应由该问 checker 计算"]
        if not entry.data_sources or not entry.code_locations or not entry.validation_evidence:
            return ["Claim 的数据、代码或实际验证证据不完整，claim_type 不提供豁免"]
        entry.status = "pass"  # Validate evidence, not the caller's trust assertion.
        entry.formal_run_id = run["run_id"]
        return domain.validate_evidence_entry(Path(root), entry, run, run_is_current_verified=True)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return ["EvidenceMap 无效: " + str(exc)]


def safe_path(root, reference, *, exists=True):
    root = Path(root).resolve()
    if not isinstance(reference, str) or not reference or "\\" in reference or ":" in reference:
        raise ValueError(f"必须使用项目内相对路径: {reference!r}")
    rel = Path(reference)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"路径越出项目: {reference}")
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越出项目: {reference}") from exc
    if exists and not path.is_file():
        raise ValueError(f"文件不存在: {reference}")
    return path


def bind_file(root, path):
    target = safe_path(root, path)
    return {"path": path, "sha256": domain.sha256_file(target), "byte_size": target.stat().st_size}


def file_errors(root, files):
    errors = []
    for item in files:
        try:
            path = safe_path(root, item["path"])
            if domain.sha256_file(path) != str(item.get("sha256", "")).upper():
                errors.append(f"文件哈希变化: {item['path']}")
            elif path.stat().st_size != item.get("byte_size", path.stat().st_size):
                errors.append(f"文件大小变化: {item['path']}")
        except (ValueError, OSError, KeyError) as exc:
            errors.append(str(exc))
    return errors


def object_errors(root, cp, object_id, stack=None):
    with _observation(root, cp) as observation:
        # Reject active cycles before reuse, including re-entry through the
        # Section content gate. Only fully completed checks can be reused.
        if object_id in (stack or ()) or object_id in observation["active"]:
            return [f"依赖循环: {object_id}"]
        if object_id in observation["complete"]:
            return list(observation["complete"][object_id])
        observation["active"].add(object_id)
        try:
            errors = _object_errors(root, cp, object_id, stack)
        finally:
            observation["active"].remove(object_id)
        observation["complete"][object_id] = tuple(errors)
        return list(errors)


def _object_errors(root, cp, object_id, stack=None):
    stack = set() if stack is None else stack
    if object_id in stack:
        return [f"依赖循环: {object_id}"]
    obj = cp["objects"].get(object_id)
    if not obj:
        return [f"缺少对象: {object_id}"]
    errors = []
    if cp["current"].get(obj.get("key")) != object_id:
        errors.append(f"对象不是当前版本: {object_id}")
    if obj.get("status") in {"stale", "superseded", "failed", "timeout", "interrupted", "missing_outputs"}:
        errors.append(f"{object_id}: {obj['status']}")
    if digest(obj["payload"]) != obj.get("payload_hash"):
        errors.append(f"对象内容哈希变化: {object_id}")
    errors.extend(file_errors(root, obj.get("files", [])))
    if obj.get("kind") == "ProblemContract":
        # Source objects may also arrive through a generic Store transaction.
        # Never rely only on Runtime's eager invalidation: consumption must
        # bind the full current question interpretation set. This check reads
        # identities only, without recursing into contract freeze/projection.
        from copilot_interpretation import records
        expected = {row["id"] for row in records(cp, obj["payload"].get("question"))}
        if not expected <= set(obj.get("dependencies", [])):
            errors.append(f"合同未绑定当前全部题意歧义/假设，须重新冻结: {object_id}")
    for dep in obj.get("dependencies", []):
        errors.extend(object_errors(root, cp, dep, stack | {object_id}))
    if obj.get("kind") == "AssumptionValidation":
        from copilot_interpretation import validation_receipt_errors
        errors.extend(validation_receipt_errors(cp, obj))
    if obj.get("kind") == "EvidenceMapEntry" and obj.get("status") == "verified":
        sources = [dep for dep in obj.get("dependencies", []) if cp["objects"].get(dep, {}).get("kind") == "ResultRecord"]
        errors.extend(claim_evidence_errors(root, cp, obj["payload"], sources))
        try:
            if not claim_assurance(cp, obj["payload"], sources)["verified"]:
                errors.append(f"unsupported claim: {object_id} 的内容未绑定实际核验结果，需补证后登记新版本")
        except (ValueError, TypeError, KeyError) as exc:
            errors.append("Claim 内容核验失败: " + str(exc))
    if obj.get("kind") == "PaperSection" and obj.get("status") == "verified" and not errors:
        # Revalidate legacy sections too. A valid source claim cannot certify
        # extra, unsupported prose that an earlier section gate overlooked.
        from copilot_delivery import _section_errors
        try:
            payload = obj["payload"]
            text = safe_path(root, payload["path"]).read_text(encoding="utf-8")
            errors.extend(_section_errors(root, cp, text, payload["claim_ids"], payload.get("source_bindings"), payload.get("structure")))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            errors.append("PaperSection 内容核验失败: " + str(exc))
    return list(dict.fromkeys(errors))


def usable(root, cp, object_id, *, verified=False):
    obj = cp["objects"].get(object_id, {})
    return not object_errors(root, cp, object_id) and (
        not verified or obj.get("status") == "verified")


def evidence_questions(cp, object_id):
    """Questions a result actually answers, not every ancestor it happens to cite."""
    obj = cp["objects"].get(object_id, {})
    payload = obj.get("payload", {})
    kind = obj.get("kind")
    if kind == "ResultRecord":
        return evidence_questions(cp, payload["run_id"])
    if kind == "EvidenceMapEntry":
        return evidence_questions(cp, payload["formal_run_id"])
    if kind == "PaperSection":
        return set().union(*(evidence_questions(cp, x) for x in obj.get("dependencies", []) if cp["objects"][x]["kind"] == "EvidenceMapEntry"))
    return {payload["question"]} if kind in {"RunRecord", "ValidationReport"} and payload.get("question") else set()


def evidence_requirements(cp, object_id):
    obj = cp["objects"].get(object_id, {})
    payload, kind = obj.get("payload", {}), obj.get("kind")
    if kind == "EvidenceMapEntry":
        return set(payload.get("requirement_ids", []))
    if kind == "ResultRecord":
        return evidence_requirements(cp, payload["run_id"])
    if kind in {"RunRecord", "ValidationReport", "PaperSection"}:
        covered = set()
        for dep in obj.get("dependencies", []):
            parent = cp["objects"][dep]
            if kind == "RunRecord" and parent["kind"] == "ModelSpec":
                covered.update(parent["payload"].get("requirement_ids", []))
            elif parent["kind"] in {"RunRecord", "EvidenceMapEntry"}:
                covered.update(evidence_requirements(cp, dep))
        return covered
    return set()


def _propagate(cp, source_ids, reason):
    edges = [{"from_id": dep, "to_id": obj_id, "invalidates": True}
             for obj_id, obj in cp["objects"].items() for dep in obj.get("dependencies", [])]
    affected = set(source_ids)
    for source in source_ids:
        report = domain.impact_analysis(edges, source)
        affected.update(item["id"] for item in report["impacted"])
    for obj_id in affected:
        obj = cp["objects"].get(obj_id)
        if obj:
            obj["status"] = "stale"
            obj["stale_reason"] = reason
    for task in cp["tasks"].values():
        if affected.intersection(task.get("dependencies", []) + task.get("outputs", [])):
            task["status"] = "blocked"
            task["blocker"] = reason
    return sorted(affected)


def _put(state, kind, key, payload, deps=(), files=(), status="generated", adopt=True):
    cp = state["copilot"]
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", key):
        raise ValueError("对象 key 必须是稳定 ASCII 标识")
    if len(set(deps)) != len(deps) or any(x not in cp["objects"] for x in deps):
        raise ValueError("对象依赖缺失或重复")
    versions = [obj["version"] for obj in cp["objects"].values() if obj["key"] == key]
    version = max(versions, default=0) + 1
    obj_id = f"{key}@{version}"
    old = cp["current"].get(key)
    if old and cp["objects"][old]["kind"] != kind:
        raise ValueError("稳定 key 不可改变对象类型")
    if old and adopt:
        _propagate(cp, [old], f"{old} 被 {obj_id} 取代")
    obj = {"id": obj_id, "key": key, "kind": kind, "version": version,
           "payload": copy.deepcopy(payload), "payload_hash": digest(payload),
           "dependencies": list(deps), "files": copy.deepcopy(list(files)),
           "status": status, "created_at": utc_now(), "created_revision": cp["revision"] + 1}
    cp["objects"][obj_id] = obj
    if adopt:
        cp["current"][key] = obj_id
    return obj_id


def requirement_status(root, state):
    cp = state.get("copilot", {})
    requirements = cp.get("requirements", {})
    rows = []
    expected = state.get("stages", {}).get("5", {}).get("qi_count")
    questions = {f"Q{i}": "missing" for i in range(1, expected + 1)} if type(expected) is int else {}
    for req_id, req in requirements.items():
        if not req.get("active", True):
            continue
        outputs = req["definition"]["outputs"]
        coverage = req.get("coverage", {})
        missing = [name for name in outputs if name not in coverage or
                   not usable(root, cp, coverage[name], verified=True)]
        contract_ok = usable(root, cp, req["contract_id"])
        status = "verified" if contract_ok and not missing and outputs else "missing"
        rows.append({"id": req_id, "question": req["question"], "status": status,
                     "missing_outputs": missing, "contract_current": contract_ok})
        questions.setdefault(req["question"], "missing")
    for question in questions:
        selected = [row for row in rows if row["question"] == question]
        if selected and all(row["status"] == "verified" for row in selected):
            questions[question] = "verified"
    from copilot_interpretation import pending_validation, legacy_errors
    pending = pending_validation(root, cp)
    for oid in pending:
        questions[cp["objects"][oid]["payload"]["question"]] = "missing"
    for question in questions:
        if state.get("copilot") and legacy_errors(state, question):
            questions[question] = "missing"
    result = {"total": len(rows), "verified": sum(x["status"] == "verified" for x in rows),
             "missing": [x["id"] for x in rows if x["status"] != "verified"],
             "questions": questions, "rows": rows,
             "complete": bool(rows and questions) and all(x == "verified" for x in questions.values())}
    if pending:
        result["pending_assumption_validation"] = pending
    return result


class Runtime:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.store = Store(self.root / "state/decision_log.json")

    def read(self):
        return self.store.read()

    def _tx(self, revision, actor, reason, fn, request_id=None, intent=None):
        return self.store.transact(revision, actor, reason, fn, request_id,
                                   digest(intent) if request_id else None)

    def migrate(self, revision=0, actor="integrator"):
        state = self.read()
        if state.get("copilot"):
            return {"revision": state["copilot"]["revision"], "result": {"already_migrated": True}}
        original = self.store.path.read_bytes()
        backup = self.root / "state/migrations" / (digest(state) + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(original)
        return self._tx(revision, actor, "迁移旧状态；旧评分不成为运行证据", lambda s: {"legacy_backup": str(backup.relative_to(self.root))})

    def configure(self, revision, *, actor="integrator", question_count=None,
                  problem_year=None, rules_year=None, evaluation_mode=None, stage=None,
                  mode=None, task_type=None, qi_weights=None, **metadata):
        def change(state):
            if question_count is not None:
                if type(question_count) is not int or question_count < 1:
                    raise ValueError("question_count 必须是正整数")
                old = state["stages"]["5"].get("qi_count")
                if old is not None and question_count < old:
                    raise ValueError("不可缩小已声明题目全集；需按题意合同显式修订")
                state["stages"]["5"]["qi_count"] = question_count
                for i in range(1, question_count + 1):
                    state["stages"]["5"].setdefault("qi_status", {}).setdefault(f"Q{i}", "pending")
            if stage is not None:
                state["current_stage"] = stage
            if mode is not None:
                if mode not in {"fast", "standard", "championship"}:
                    raise ValueError("未知工作模式")
                state["mode"] = mode
            if task_type is not None:
                if not isinstance(task_type, str): raise ValueError("task_type 必须是字符串")
                state["task_type"] = task_type
            if qi_weights is not None:
                expected = {f"Q{i}" for i in range(1, (state["stages"]["5"].get("qi_count") or 0) + 1)}
                if not isinstance(qi_weights, dict) or not expected or set(qi_weights) != expected:
                    raise ValueError("权重必须按完整 Qi ID 映射")
                state["stages"]["5"]["qi_weights"] = qi_weights
            for key, value in (("problem_year", problem_year), ("rules_year", rules_year), ("evaluation_mode", evaluation_mode)):
                if value is not None:
                    state["problem_meta"][key] = value
            meta = state["problem_meta"]
            if meta.get("evaluation_mode") not in {None, "formal_contest", "historical_benchmark", "open_research"}:
                raise ValueError("evaluation_mode 非法")
            for key in ("problem_year", "rules_year"):
                if meta.get(key) is not None and (type(meta[key]) is not int or not 1900 <= meta[key] <= 2200):
                    raise ValueError(f"{key} 非法")
            if meta.get("evaluation_mode") == "formal_contest" and meta.get("problem_year") != meta.get("rules_year"):
                raise ValueError("正式项目 problem_year 与 rules_year 必须相同")
            if metadata:
                if set(metadata) - {"title", "letter", "deadline_iso", "team_size"}:
                    raise ValueError("未知 configure 字段：" + ", ".join(sorted(set(metadata) - {"title", "letter", "deadline_iso", "team_size"}))
                                     + "；允许字段：question_count, problem_year, rules_year, evaluation_mode, stage, mode, task_type, qi_weights, title, letter, deadline_iso, team_size")
                meta.update(metadata)
            return {"stage": state["current_stage"], "question_count": state["stages"]["5"].get("qi_count")}
        return self._tx(revision, actor, "更新项目范围与导航", change)

    def record_stage(self, revision, stage, details, *, actor="integrator"):
        if type(stage) is not int or not 0 <= stage <= 9 or not isinstance(details, dict):
            raise ValueError("stage 与 details 无效")
        protected = {"submission_ready", "compliance_checks", "qi_count", "qi_status", "qi_weights", "ambiguities", "assumptions"}
        if protected.intersection(details):
            raise ValueError("完成、合规、题目全集和歧义/假设必须使用专用入口；歧义/假设请使用 interpretation 与 interpretation-review")
        def change(state):
            state["stages"][str(stage)].update(copy.deepcopy(details))
            return {"stage": stage, "recorded_fields": sorted(details)}
        return self._tx(revision, actor, f"记录 Stage {stage} 的决定与材料", change)

    def record_interpretation(self, revision, kind, payload, *, actor="modeler", request_id=None):
        from copilot_interpretation import record
        return record(self, revision, kind, payload, actor=actor, request_id=request_id)

    def review_interpretation(self, revision, object_id, *, action, rationale, evidence_files=(),
                              resolution=None, result_ids=(), actor="integrator"):
        from copilot_interpretation import review
        return review(self, revision, object_id, action=action, rationale=rationale,
                      evidence_files=evidence_files, resolution=resolution, result_ids=result_ids, actor=actor)

    def log_ai(self, revision, payload, *, actor="integrator"):
        def change(state):
            ledger = state["compliance"].get("ai_usage")
            if payload.get("action") == "declare_none":
                if ledger or not str(payload.get("reason", "")).strip():
                    raise ValueError("不可清除已有 AI 日志；未使用声明需明确原因")
                state["compliance"]["ai_usage"] = []
            else:
                entry = payload.get("entry")
                if not isinstance(entry, dict) or not entry:
                    raise ValueError("需提供实际 AI 使用 entry；字段参考原 render_ai_usage.py")
                state["compliance"]["ai_usage"] = list(ledger or []) + [copy.deepcopy(entry)]
            return {"entries": len(state["compliance"]["ai_usage"])}
        return self._tx(revision, actor, "追加实际 AI 使用记录", change)

    def register(self, revision, kind, key, payload, *, dependencies=(), files=(), actor="modeler", request_id=None):
        if kind not in SOURCE_KINDS | {"ArtifactRecord"}:
            raise ValueError("此入口只登记源契约或 generated 产物；运行、验证、Claim 必须走专用入口")
        def change(state):
            cp = state["copilot"]
            for dep in dependencies:
                errors = object_errors(self.root, cp, dep)
                if errors:
                    raise ValueError("; ".join(errors))
            data = copy.deepcopy(payload)
            errors = []
            refs = list(files)
            deps = list(dependencies)
            status = "frozen" if kind in SOURCE_KINDS else "generated"
            if kind == "ProblemContract":
                # Reject unusable identities at the write boundary, while
                # preserving deserialization of historical records and drafts.
                contract_id = data.get("contract_id")
                if (not isinstance(contract_id, str) or not contract_id
                        or not contract_id.isprintable() or any(char.isspace() for char in contract_id)):
                    raise ValueError("题意合同标识 contract_id 必须是非空文本，且不能含空白或不可见字符（例如 PC-Q1）")
                data["status"] = "frozen"
                contract = domain.ProblemContract.from_dict(data)
                count = state["stages"]["5"].get("qi_count")
                if type(count) is not int or contract.question not in {f"Q{i}" for i in range(1, count + 1)}:
                    raise ValueError("先从题面声明完整 question_count；合同小问必须位于该全集")
                from copilot_interpretation import freeze_inputs
                interpretation_errors, ambiguities, assumptions, interpretation_ids = freeze_inputs(self.root, state, contract)
                errors += interpretation_errors
                errors += domain.validate_problem_contract(self.root, contract, for_freeze=True,
                                                           ambiguities=ambiguities, assumptions=assumptions)
                deps += [oid for oid in interpretation_ids if oid not in deps]
                refs += [x["path"] for x in contract.source_files if not re.match(r"\w+://", x["path"])]
                if any(re.match(r"\w+://", x["path"]) for x in contract.source_files):
                    errors.append("题意必须绑定已取得的本地题面快照，URL 只作来源元数据")
                data = contract.to_dict()
            elif kind == "ModelSpec":
                from copilot_interpretation import legacy_errors
                errors += legacy_errors(state, data.get("question"))
                data["status"] = "frozen"
                spec = domain.ModelSpec.from_dict(data)
                errors += domain.validate_modelspec_structure(spec)
                contracts = [cp["objects"][x] for x in deps if cp["objects"][x]["kind"] == "ProblemContract"]
                if len(contracts) != 1 or contracts[0]["payload"].get("question") != spec.question:
                    errors.append("模型须依赖同一小问的当前题意合同")
                elif spec.problem_contract_id != contracts[0]["payload"].get("contract_id") or spec.problem_contract_semantic_hash != contracts[0]["payload"].get("semantic_hash"):
                    errors.append("ModelSpec 的 ProblemContract ID/hash 与实际依赖不一致")
                if not set(spec.requirement_ids) <= set(cp["requirements"]):
                    errors.append("模型覆盖未知 Requirement")
                elif any(cp["requirements"][x]["question"] != spec.question or
                         cp["requirements"][x]["contract_id"] not in deps for x in spec.requirement_ids):
                    errors.append("ModelSpec 只能声明同一小问当前合同的 Requirement")
                data = spec.to_dict()
            elif kind == "ParameterSet":
                params = domain.ParameterSet.from_dict(data)
                errors += domain.validate_parameter_entries(params.entries, formal=False)
                models = [cp["objects"][x] for x in deps if cp["objects"][x]["kind"] == "ModelSpec"]
                if len(models) != 1:
                    errors.append("ParameterSet 须依赖唯一当前模型")
                else:
                    model = models[0]["payload"]
                    if (params.spec_id != model.get("spec_id") or params.modelspec_semantic_hash != model.get("semantic_hash") or params.modelspec_record_hash != model.get("record_hash")):
                        errors.append("ParameterSet 模型 ID/hash 不匹配")
                    if params.question != model.get("question"):
                        errors.append("ParameterSet 与模型小问不一致")
                    if {x.parameter_id for x in params.entries} != {x["parameter_id"] for x in model.get("parameters", [])}:
                        errors.append("ParameterSet 与 ModelSpec 参数全集不一致")
                    errors += domain.validate_parameter_contract(
                        [domain.ParameterEntry.from_dict(x) for x in model.get("parameters", [])], params.entries)
                data = params.to_dict()
            elif kind == "DataContract":
                contracts = [cp["objects"][x] for x in deps if cp["objects"][x]["kind"] == "ProblemContract"]
                if not data.get("question") or not any(x["payload"]["question"] == data["question"] for x in contracts):
                    errors.append("DataContract 须绑定所属小问的题意合同")
                errors += domain.validate_data_contract(self.root, data.get("inventory", {}), data.get("passport", {}), data.get("split", {}))
                refs += [x["path"] for x in (data.get("inventory") or {}).get("entries", [])]
                data = domain.seal_record(data)
            elif kind == "ValidationPlan":
                errors += domain.validate_validation_plan(data)
                for check in data.get("checks", []):
                    if check.get("applicability", "required") != "not_applicable" and len(str(check.get("criterion", "")).strip()) < 8:
                        errors.append("每个实质检查须预先给出可复核 criterion")
                models = [cp["objects"][x] for x in deps if cp["objects"][x]["kind"] == "ModelSpec"]
                if len(models) != 1:
                    errors.append("验证计划须绑定唯一模型版本")
                else:
                    if data.get("question") != models[0]["payload"]["question"]:
                        errors.append("ValidationPlan 与模型小问不一致")
                    expected = {x["check_id"] for x in models[0]["payload"]["validation_plan"] if x.get("check_id")}
                    declared_ids = {x.get("check_id") for x in data.get("checks", [])}
                    if not expected or not expected <= declared_ids:
                        errors.append("验证计划不得遗漏冻结模型预定检查")
                checker = data.get("checker")
                if not isinstance(checker, dict) or not checker.get("path") or not checker.get("sha256"):
                    errors.append("验证计划须预先绑定实际 checker 文件及 SHA-256")
                else:
                    checker_file = bind_file(self.root, checker["path"])
                    if checker_file["sha256"] != str(checker["sha256"]).upper():
                        errors.append("checker 哈希不匹配")
                    refs.append(checker["path"])
                    if Path(checker["path"]).suffix.lower() != ".py":
                        errors.append("v0.1 的已验证执行后端只运行 Python checker")
                    checker.setdefault("argv", ["{python}", "{checker}", "{run}", "{report}"])
                    if (not isinstance(checker["argv"], list) or len(checker["argv"]) < 2
                            or checker["argv"][:2] != ["{python}", "{checker}"]
                            or any(not isinstance(x, str) for x in checker["argv"])):
                        errors.append("checker argv 必须直接执行已绑定文件")
                data = domain.seal_record(data)
            elif kind == "CodeManifest":
                if "environment_lock" in data:
                    from copilot_run_environment import bind_lock
                    data["environment_lock"] = bind_lock(self.root, data["environment_lock"])
                    refs.append(data["environment_lock"]["path"])
                if data.get("files") and files and {x["path"] for x in data["files"]} != set(files):
                    errors.append("CodeManifest files 与实际快照文件清单不一致")
                refs += [x["path"] for x in data.get("files", [])]
                if not refs or any(Path(x).suffix.lower() not in {".py", ".m", ".r", ".jl", ".json", ".txt", ".csv", ".yaml", ".yml", ".toml", ".lock"} for x in refs):
                    errors.append("代码清单须绑定实际代码及配置文件")
                models = [cp["objects"][x] for x in deps if cp["objects"][x]["kind"] == "ModelSpec"]
                if len(models) != 1:
                    errors.append("代码清单须绑定唯一模型")
                python_files = [x for x in refs if Path(x).suffix.lower() == ".py"]
                entry = data.get("entrypoint") or (python_files[0] if len(python_files) == 1 else None)
                if entry not in python_files:
                    errors.append("CodeManifest 需明确绑定的 Python entrypoint；其他后端保留为生成产物")
                data["entrypoint"] = entry
                data.setdefault("argv", ["{python}", entry])
                if (not isinstance(data["argv"], list) or len(data["argv"]) < 2
                        or data["argv"][:2] != ["{python}", entry]
                        or any(not isinstance(x, str) for x in data["argv"])):
                    errors.append("代码 argv 必须直接执行已绑定 entrypoint")
                data = domain.seal_record(data)
                if len(models) == 1:
                    model = models[0]["payload"]
                    data.setdefault("record_type", "code_manifest")
                    data.setdefault("spec_id", model["spec_id"])
                    data.setdefault("modelspec_semantic_hash", model["semantic_hash"])
                    data.setdefault("question", model["question"])
                    data.setdefault("revision_id", digest([bind_file(self.root, x) for x in sorted(set(refs))]))
                    data.setdefault("files", [bind_file(self.root, x) for x in sorted(set(refs))])
                    data = domain.seal_record(data)
                    errors += domain.validate_code_manifest(self.root, data,
                        expected_question=model["question"], expected_spec_id=model["spec_id"],
                        expected_modelspec_hash=model["semantic_hash"], expected_revision=data["revision_id"])
            elif kind == "ArtifactRecord":
                if data.get("path"):
                    refs.append(data["path"])
                if not refs:
                    errors.append("产物须绑定实际文件")
                data = domain.seal_record(data)
            if errors:
                raise ValueError("; ".join(errors))
            if kind in SOURCE_KINDS:
                aliases = [x["key"] for x in cp["objects"].values() if x["kind"] == kind and
                           x["payload"].get("question") == data.get("question") and x["key"] != key]
                if aliases:
                    raise ValueError(f"该小问的 {kind} 已有稳定 key {aliases[0]}；请创建同 key 新版本")
            bindings = [bind_file(self.root, x) for x in sorted(set(refs))]
            obj_id = _put(state, kind, key, data, deps, bindings, status)
            if kind == "ProblemContract":
                current_ids = set()
                for entry in data["requirements"]:
                    rid = entry["req_id"]
                    current_ids.add(rid)
                    existing = cp["requirements"].get(rid)
                    if existing and existing["question"] != data["question"]:
                        raise ValueError("ReqID 不可跨小问复用")
                    cp["requirements"][rid] = {"question": data["question"], "definition": entry,
                        "contract_id": obj_id, "coverage": {}, "active": True}
                for rid, req in cp["requirements"].items():
                    if req["question"] == data["question"] and rid not in current_ids:
                        # Removed requirements remain visible until explicitly resolved.
                        req["coverage"] = {}
                        req["removal_pending"] = True
            return {"object_id": obj_id, "status": status}
        return self._tx(revision, actor, f"登记 {kind} {key}", change, request_id,
                        {"kind": kind, "key": key, "payload": payload, "deps": list(dependencies), "files": list(files)})

    def task(self, revision, task_id, payload, *, actor="integrator"):
        def change(state):
            cp = state["copilot"]
            if task_id in cp["tasks"]:
                raise ValueError("Task ID 已存在；用 transition 更新任务")
            if not payload.get("title") or payload.get("role") not in ROLES:
                raise ValueError("任务需 title 和有效 role")
            reqs = payload.get("requirements", [])
            if not reqs or not set(reqs) <= set(cp["requirements"]):
                raise ValueError("任务须绑定已知 Requirement")
            deps = payload.get("dependencies", [])
            parents = payload.get("depends_on", [])
            if any(x not in cp["objects"] for x in deps) or any(x not in cp["tasks"] for x in parents):
                raise ValueError("任务依赖不存在")
            cp["tasks"][task_id] = {"id": task_id, **copy.deepcopy(payload), "status": "pending", "outputs": []}
            cp["current_task"] = task_id
            return cp["tasks"][task_id]
        return self._tx(revision, actor, f"创建任务 {task_id}", change)

    def transition(self, revision, task_id, status, *, outputs=(), actor="integrator"):
        def change(state):
            cp = state["copilot"]
            task = cp["tasks"].get(task_id)
            if not task:
                raise ValueError("任务不存在")
            allowed = {"pending": {"running", "blocked"}, "running": {"completed", "blocked"},
                       "blocked": {"pending", "running"}, "completed": set()}
            if status not in allowed[task["status"]]:
                raise ValueError(f"非法 Task 转移: {task['status']} -> {status}")
            if status in {"running", "completed"}:
                if any(cp["tasks"][x]["status"] != "completed" for x in task.get("depends_on", [])):
                    raise ValueError("前置任务未完成")
                for x in task.get("dependencies", []):
                    if not usable(self.root, cp, x):
                        raise ValueError("任务输入已过期")
            if status == "completed":
                if not outputs or not all(usable(self.root, cp, x, verified=True) for x in outputs):
                    raise ValueError("任务完成须提供当前已核验输出")
                for rid in task["requirements"]:
                    req = cp["requirements"][rid]
                    if not any(req["question"] in evidence_questions(cp, x) and rid in evidence_requirements(cp, x) for x in outputs):
                        raise ValueError("任务输出未回答任务所要求的 Requirement")
                task["outputs"] = list(outputs)
            task["status"] = status
            cp["current_task"] = task_id
            return copy.deepcopy(task)
        return self._tx(revision, actor, f"任务 {task_id} -> {status}", change)

    def reconcile(self, revision, actor="integrator"):
        def change(state):
            cp = state["copilot"]
            drift = [x for x, obj in cp["objects"].items() if obj["status"] != "stale" and file_errors(self.root, obj.get("files", []))]
            return {"stale": _propagate(cp, drift, "登记文件发生变化；需要新版本和重检")}
        return self._tx(revision, actor, "重新核对登记文件与下游影响", change)

    def execute(self, revision, question, argv, outputs, *, dependencies, seed="0", timeout=60,
                actor="coder", request_id=None):
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
            raise ValueError("执行命令必须是非空 argv 数组；不通过 shell 执行")
        if type(timeout) not in (int, float) or timeout <= 0 or not outputs or len(set(outputs)) != len(outputs):
            raise ValueError("timeout 与唯一必需输出清单无效")
        execution_id = "RUN-" + uuid.uuid4().hex[:16]
        intent = {"question": question, "argv": argv, "outputs": outputs, "deps": dependencies, "seed": seed, "timeout": timeout}
        def reserve(state):
            cp = state["copilot"]
            from copilot_interpretation import legacy_errors
            legacy = legacy_errors(state, question)
            if legacy:
                raise ValueError("; ".join(legacy))
            chosen = {cp["objects"][x]["kind"]: x for x in dependencies if x in cp["objects"]}
            for kind in ("ModelSpec", "ParameterSet", "DataContract", "CodeManifest", "ValidationPlan"):
                if kind not in chosen:
                    raise ValueError(f"真实运行缺少 {kind}")
                if sum(cp["objects"].get(x, {}).get("kind") == kind for x in dependencies) != 1:
                    raise ValueError(f"真实运行必须绑定唯一 {kind}")
            for dep in dependencies:
                if not usable(self.root, cp, dep):
                    raise ValueError(f"运行依赖失效: {dep}")
                obj = cp["objects"][dep]
                q = obj["payload"].get("question")
                if q and q != question and obj["kind"] != "ResultRecord":
                    raise ValueError("直接运行配置的小问不一致；跨问结果应作为显式附加输入")
            model_id = chosen["ModelSpec"]
            required_outputs = cp["objects"][model_id]["payload"]["required_outputs"]
            if not set(required_outputs) <= set(outputs):
                raise ValueError("不得省略冻结模型的 required_outputs")
            if argv != cp["objects"][chosen["CodeManifest"]]["payload"]["argv"]:
                raise ValueError("执行命令与预先锁定的 CodeManifest 不一致")
            for kind in ("ParameterSet", "CodeManifest", "ValidationPlan"):
                if model_id not in cp["objects"][chosen[kind]]["dependencies"]:
                    raise ValueError(f"{kind} 未绑定所执行模型")
            cp.setdefault("executions", {})[execution_id] = {"id": execution_id, "status": "running",
                "question": question, "dependencies": list(dependencies), "argv": argv,
                "outputs": outputs, "seed": str(seed), "started_at": utc_now(), "chosen": chosen}
            return {"execution_id": execution_id}
        reserved = self._tx(revision, actor, f"开始真实运行 {question}", reserve, request_id, intent)
        actual_id = reserved["result"]["execution_id"]
        if actual_id != execution_id:
            previous = self.read()["copilot"]["executions"][actual_id]
            if previous["status"] == "running":
                raise ConflictError("相同请求正在执行或已中断；不可重复启动")
            return {"revision": self.read()["copilot"]["revision"], "result": previous}
        state = self.read()
        cp = state["copilot"]
        reservation = cp["executions"][execution_id]
        run_dir = self.root / ".copilot/runs" / execution_id
        run_dir.mkdir(parents=True, exist_ok=False)
        copied = {}
        closure = set(dependencies)
        todo = list(dependencies)
        while todo:
            obj_id = todo.pop()
            for dep in cp["objects"][obj_id]["dependencies"]:
                if dep not in closure:
                    closure.add(dep)
                    todo.append(dep)
        for obj_id in closure:
            for item in cp["objects"][obj_id]["files"]:
                copied[item["path"]] = item
        receipt = {"execution_id": execution_id, "argv": argv, "seed": str(seed), "status": "failed",
                   "started_at": reservation["started_at"], "returncode": None,
                   "environment": {"python": sys.version, "platform": platform.platform(), "executable": sys.executable},
                   "inputs": list(copied.values()), "outputs": [], "error": ""}
        try:
            for relative in outputs:
                safe_path(run_dir, relative, exists=False)
                if relative in copied or relative in {"stdout.log", "stderr.log", "receipt.json", "run_context.json"}:
                    raise ValueError("输出不得与输入或执行器保留文件重叠")
            for relative, item in copied.items():
                source = safe_path(self.root, relative)
                if domain.sha256_file(source) != item["sha256"]:
                    raise ValueError(f"复制前输入已变化: {relative}")
                destination = safe_path(run_dir, relative, exists=False)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if domain.sha256_file(destination) != item["sha256"]:
                    raise ValueError(f"输入复制不一致: {relative}")
            # The snapshot is the real runtime input, including model and parameters.
            context = {cp["objects"][x]["kind"]: cp["objects"][x]["payload"] for x in dependencies}
            context["_objects"] = {x: {"kind": cp["objects"][x]["kind"], "payload": cp["objects"][x]["payload"]} for x in dependencies}
            atomic_write(run_dir / "run_context.json", context)
            context_hash = domain.sha256_file(run_dir / "run_context.json")
            command = [x.replace("{python}", sys.executable).replace("{run}", str(run_dir)) for x in argv]
            environment = dict(os.environ, PYTHONHASHSEED=str(seed) if str(seed).isdigit() else "0", PYTHONUTF8="1")
            from copilot_run_environment import observe_git, observe_libraries
            receipt["environment"]["scientific_libraries"] = observe_libraries(run_dir, environment)
            receipt["environment"]["git"] = observe_git(self.root)
            code = cp["objects"][reservation["chosen"]["CodeManifest"]]["payload"]
            if code.get("environment_lock"):
                receipt["environment"]["environment_lock"] = {
                    "binding": code["environment_lock"], "content_status": "hash_verified_and_snapshotted",
                    "environment_match": "not_verified"}
            with (run_dir / "stdout.log").open("wb") as out, (run_dir / "stderr.log").open("wb") as err:
                completed = subprocess.run(command, cwd=run_dir, stdout=out, stderr=err,
                                           timeout=timeout, env=environment, shell=False)
            receipt["returncode"] = completed.returncode
            receipt["status"] = "completed" if completed.returncode == 0 else "failed"
            if receipt["status"] == "completed":
                absent = [x for x in outputs if not safe_path(run_dir, x, exists=False).is_file()]
                if absent:
                    receipt["status"] = "missing_outputs"
                    receipt["error"] = "缺少本次运行输出: " + ", ".join(absent)
            for relative in outputs:
                path = safe_path(run_dir, relative, exists=False)
                if path.is_file():
                    receipt["outputs"].append(bind_file(self.root, path.relative_to(self.root).as_posix()))
            # A solver changing its inputs is a different experiment, not this run.
            changed_inputs = [x for x, item in copied.items() if domain.sha256_file(run_dir / x) != item["sha256"]]
            if domain.sha256_file(run_dir / "run_context.json") != context_hash:
                changed_inputs.append("run_context.json")
            if changed_inputs:
                receipt["status"] = "failed"
                receipt["error"] = "运行改写已锁定输入: " + ", ".join(changed_inputs)
        except subprocess.TimeoutExpired:
            receipt["status"] = "timeout"
            receipt["error"] = f"超过 {timeout} 秒"
        except (OSError, ValueError) as exc:
            receipt["status"] = "failed"
            receipt["error"] = str(exc)
        receipt["finished_at"] = utc_now()
        atomic_write(run_dir / "receipt.json", receipt)
        def finish(state):
            live = state["copilot"]
            chosen = reservation["chosen"]
            model = cp["objects"][chosen["ModelSpec"]]["payload"]
            params = cp["objects"][chosen["ParameterSet"]]["payload"]
            record = domain.RunRecord.from_dict({"run_id": execution_id, "run_type": "candidate", "question": question,
                "spec_id": model["spec_id"], "modelspec_semantic_hash": model["semantic_hash"], "modelspec_record_hash": model["record_hash"],
                "activation_id": chosen["ModelSpec"], "activation_record_hash": cp["objects"][chosen["ModelSpec"]]["payload_hash"],
                "parameter_set_id": params["parameter_set_id"], "parameter_set_semantic_hash": params["semantic_hash"],
                "git_commit": receipt["environment"].get("git", {}).get("head", ""),
                "code_manifest_id": chosen["CodeManifest"],
                "code_manifest_hash": cp["objects"][chosen["CodeManifest"]]["payload_hash"].upper(),
                "data_version": chosen["DataContract"], "data_hash": cp["objects"][chosen["DataContract"]]["payload_hash"].upper(),
                "config_hash": digest(intent).upper(), "environment": receipt["environment"], "command": json.dumps(argv),
                "seed": str(seed), "repeat_count": 1, "outputs": receipt["outputs"], "status": receipt["status"],
                "started_at": receipt["started_at"], "finished_at": receipt["finished_at"]}).to_dict()
            files = receipt["outputs"] + [bind_file(self.root, (run_dir / x).relative_to(self.root).as_posix())
                                         for x in ("receipt.json", "stdout.log", "stderr.log", "run_context.json") if (run_dir / x).is_file()]
            files += [bind_file(self.root, (run_dir / x).relative_to(self.root).as_posix()) for x in copied if (run_dir / x).is_file()]
            outcome = "executed" if receipt["status"] == "completed" else receipt["status"]
            if any(not usable(self.root, live, x) for x in dependencies):
                outcome = "stale"
            object_id = _put(state, "RunRecord", execution_id, record, dependencies, files, outcome)
            live["objects"][object_id]["execution"] = {"receipt": (run_dir / "receipt.json").relative_to(self.root).as_posix(),
                                                       "returncode": receipt["returncode"], "directory": run_dir.relative_to(self.root).as_posix()}
            live["executions"][execution_id].update(status=receipt["status"], object_id=object_id, finished_at=receipt["finished_at"])
            return {"object_id": object_id, "status": outcome, "receipt": live["objects"][object_id]["execution"]["receipt"]}
        return self._finish_transaction(actor, "登记真实运行回执", finish)

    def _finish_transaction(self, actor, reason, fn):
        # An expensive execution may finish while other roles update unrelated
        # objects. Recheck dependencies inside each fresh CAS, never overwrite.
        for _ in range(8):
            revision = self.read()["copilot"]["revision"]
            try:
                return self._tx(revision, actor, reason, fn)
            except ConflictError:
                continue
        raise ConflictError("运行结果已保存在独立目录；状态持续冲突，请恢复登记")

    def validate_run(self, revision, run_id, checker, argv, *, report="validation.json", timeout=60, actor="qa"):
        state = self.read()
        cp = state["copilot"]
        if cp["revision"] != revision:
            raise ConflictError("验证基线已变化")
        run_obj = cp["objects"].get(run_id)
        if not run_obj or run_obj["kind"] != "RunRecord" or run_obj["status"] not in {"executed", "verified"} or not usable(self.root, cp, run_id):
            raise ValueError("只能验证当前成功执行的 Run")
        plan_id = next(x for x in run_obj["dependencies"] if cp["objects"][x]["kind"] == "ValidationPlan")
        plan = cp["objects"][plan_id]["payload"]
        checker_binding = bind_file(self.root, checker)
        # Checker identity is part of the plan, fixed before the model run.
        declared = plan.get("checker")
        if not isinstance(declared, dict) or declared.get("path") != checker or str(declared.get("sha256", "")).upper() != checker_binding["sha256"]:
            raise ValueError("验证器必须在运行前的 ValidationPlan 中锁定路径和 SHA-256")
        if argv != declared.get("argv"):
            raise ValueError("验证命令与预先锁定的 checker argv 不一致")
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout 必须大于零")
        check_id = "CHECK-" + uuid.uuid4().hex[:16]
        check_dir = self.root / ".copilot/checks" / check_id
        check_dir.mkdir(parents=True, exist_ok=False)
        safe_path(check_dir, report, exists=False)
        if report in {"checker.py", "stdout.log", "stderr.log", "receipt.json", "sealed-report.json"}:
            raise ValueError("验证报告路径与保留文件冲突")
        shutil.copy2(safe_path(self.root, checker), check_dir / "checker.py")
        if domain.sha256_file(check_dir / "checker.py") != checker_binding["sha256"]:
            raise ValueError("复制后的 checker 与预定哈希不一致")
        run_dir = self.root / run_obj["execution"]["directory"]
        command = [x.replace("{python}", sys.executable).replace("{checker}", str(check_dir / "checker.py"))
                   .replace("{run}", str(run_dir)).replace("{report}", str(check_dir / report)) for x in argv]
        receipt = {"argv": command, "checker": checker_binding, "run_id": run_id, "plan_id": plan_id,
                   "started_at": utc_now(), "returncode": None, "status": "failed"}
        try:
            with (check_dir / "stdout.log").open("wb") as out, (check_dir / "stderr.log").open("wb") as err:
                process = subprocess.run(command, cwd=check_dir, stdout=out, stderr=err, timeout=timeout,
                                         env=dict(os.environ, PYTHONUTF8="1"), shell=False)
            receipt["returncode"] = process.returncode
            receipt["status"] = "completed" if process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            receipt["status"] = "timeout"
        except OSError as exc:
            receipt["error"] = str(exc)
        errors = []
        raw = {}
        try:
            raw = json.loads(safe_path(check_dir, report).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("验证报告必须是 object")
            digest(raw)  # Reject non-finite JSON values before any success path.
            if not isinstance(raw.get("checks"), list) or not isinstance(raw.get("metrics", {}), dict) or not isinstance(raw.get("scope", ""), str):
                raise ValueError("验证报告 checks/metrics/scope 类型无效")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            raw = {}
        planned = {x["check_id"]: x for x in plan["checks"]}
        seen = set()
        checks = []
        outputs = run_obj["payload"]["outputs"]
        for check in raw.get("checks", []) if isinstance(raw.get("checks"), list) else []:
            if not isinstance(check, dict) or not isinstance(check.get("check_id"), str) or check.get("check_id") not in planned or check["check_id"] in seen:
                errors.append("未知或重复验证 check_id")
                continue
            name = check["check_id"]
            seen.add(name)
            rule = planned[name]
            if not isinstance(check.get("status"), str) or check.get("status") not in {"pass", "fail", "not_applicable"}:
                errors.append(f"{name}: 缺少或无效的检查状态")
                check = {**check, "status": "fail"}
            evidence = check.get("evidence", [])
            if not isinstance(evidence, list):
                errors.append(f"{name}: evidence 必须是数组")
                evidence = []
            refs = []
            for ref in evidence:
                if not isinstance(ref, str):
                    errors.append(f"{name}: 无效证据路径")
                    continue
                try:
                    candidate = safe_path(run_dir, ref, exists=False).relative_to(self.root).as_posix()
                except ValueError:
                    candidate = None
                matched = [x["path"] for x in outputs if x["path"] == ref or
                           candidate == x["path"]]
                if not matched:
                    errors.append(f"{name}: 证据不属于本次运行输出 {ref}")
                refs += matched
            if check.get("status") == "not_applicable" and rule.get("applicability") != "not_applicable":
                errors.append(f"{name}: 必需检查不能在运行后改成不适用")
            checks.append({**check, "predeclared": True, "criterion": rule.get("criterion", rule.get("not_applicable_reason", "")), "evidence": refs})
        required = {x for x, check in planned.items() if check.get("applicability", "required") == "required"}
        if required - seen:
            errors.append("缺少预定检查: " + ", ".join(sorted(required - seen)))
        run = run_obj["payload"]
        passed = receipt["status"] == "completed" and not errors and bool(checks) and all(
            x["status"] == "pass" or (x["status"] == "not_applicable" and planned[x["check_id"]].get("applicability") == "not_applicable") for x in checks)
        body = {k: run[k] for k in ("question", "spec_id", "git_commit", "data_version", "data_hash", "config_hash", "repeat_count", "outputs")}
        for key in ("code_manifest_id", "code_manifest_hash"):
            if run.get(key):
                body[key] = run[key]
        body.update(record_type="run_validation_report", checks=checks, status="pass" if passed else "fail", validated_at=utc_now())
        body = domain.seal_record(body)
        errors += domain.validate_run_report(self.root, body, run, required)
        errors += object_errors(self.root, cp, run_id)
        if not (check_dir / "checker.py").is_file() or domain.sha256_file(check_dir / "checker.py") != checker_binding["sha256"]:
            errors.append("checker 执行期间发生变化")
        passed = passed and not errors
        receipt.update(finished_at=utc_now(), validation_errors=errors, passed=passed)
        atomic_write(check_dir / "receipt.json", receipt)
        atomic_write(check_dir / "sealed-report.json", body)
        def change(state):
            live = state["copilot"]
            still_current = usable(self.root, live, run_id)
            files = [bind_file(self.root, x.relative_to(self.root).as_posix()) for x in check_dir.iterdir() if x.is_file()]
            files.append(checker_binding)
            cid = _put(state, "ValidationReport", check_id, body, [run_id, plan_id], files,
                       "verified" if passed and still_current else "failed" if still_current else "stale")
            live["objects"][cid]["execution"] = receipt
            if passed and still_current:
                live["objects"][run_id]["status"] = "verified"
                result = _put(state, "ResultRecord", f"result.{run['question']}.{run_id.split('@')[0]}",
                              {"question": run["question"], "run_id": run_id, "validation_id": cid, "metrics": raw.get("metrics", {}),
                               "scope": raw.get("scope", "")}, [run_id, cid], outputs, "verified")
            else:
                # A later failed recheck withdraws every earlier consumer.
                result = None
                _propagate(live, [run_id], "运行复验失败或验证期间上游已变更")
            return {"validation_id": cid, "result_id": result, "passed": passed and still_current, "errors": errors}
        return self._finish_transaction(actor, f"登记独立验证 {run_id}", change)

    def claim(self, revision, payload, result_ids, *, actor="writer"):
        def change(state):
            cp = state["copilot"]
            entry = domain.EvidenceMapEntry.from_dict(payload)
            if not entry.claim.strip() or not entry.paper_anchor.strip() or not entry.limitations:
                raise ValueError("Claim 需具体内容、论文位置和适用限制")
            if not result_ids or any(cp["objects"].get(x, {}).get("kind") != "ResultRecord" or not usable(self.root, cp, x, verified=True) for x in result_ids):
                raise ValueError("unsupported claim: 缺少当前已验证的 Result / Run")
            errors = claim_evidence_errors(self.root, cp, payload, result_ids)
            if errors:
                raise ValueError("unsupported claim: " + "; ".join(errors))
            assurance = claim_assurance(cp, payload, result_ids)
            if entry.claim_type == "numerical" and not numeric_tokens(entry.claim):
                raise ValueError("numerical Claim 必须给出可绑定的具体数值；普通说明可登记为待核验 note")
            if entry.claim_type == "numerical" and not assurance["verified"]:
                if assurance["comparison_status"] == "checked_statement_required":
                    raise ValueError("Rounded threshold/comparison Claim requires an exact conclusion statement returned by the independent checker")
                raise ValueError("unsupported claim: 数值 " + ", ".join(assurance["unbound_numbers"]) + " 未绑定已验证 Result.metrics")
            entry.status = "pass" if assurance["verified"] else "draft"
            status = "verified" if assurance["verified"] else "generated"
            claim_id = _put(state, "EvidenceMapEntry", entry.claim_id, entry.to_dict(), result_ids, [], status)
            cp["objects"][claim_id]["numeric_bindings"] = assurance["numeric_bindings"]
            cp["objects"][claim_id]["claim_assurance"] = assurance
            return {"claim_id": claim_id, "status": status, "assurance": assurance}
        return self._tx(revision, actor, "建立有运行来源的 EvidenceMap", change)

    def cover(self, revision, requirement_id, coverage, *, actor="integrator"):
        def change(state):
            cp = state["copilot"]
            req = cp["requirements"].get(requirement_id)
            if not req or set(coverage) != set(req["definition"]["outputs"]):
                raise ValueError("必须逐项覆盖该 Requirement 的全部 outputs")
            for obj_id in coverage.values():
                if not usable(self.root, cp, obj_id, verified=True):
                    raise ValueError("Requirement 输出未核验或已过期")
                obj = cp["objects"][obj_id]
                if req["question"] not in evidence_questions(cp, obj_id):
                    raise ValueError("输出来源没有回答该 Requirement 所属小问")
                if requirement_id not in evidence_requirements(cp, obj_id):
                    raise ValueError("输出证据未覆盖这个具体 Requirement")
                if obj["kind"] == "EvidenceMapEntry" and requirement_id not in obj["payload"]["requirement_ids"]:
                    raise ValueError("Claim 未声明覆盖该 Requirement")
                closure = set()
                pending = [obj_id]
                while pending:
                    parent = pending.pop()
                    if parent not in closure:
                        closure.add(parent)
                        pending.extend(cp["objects"][parent]["dependencies"])
                if req["contract_id"] not in closure:
                    raise ValueError("输出证据链未绑定该 Requirement 的当前题意合同")
            req["coverage"] = copy.deepcopy(coverage)
            return {"requirement_id": requirement_id, "coverage": coverage}
        return self._tx(revision, actor, f"核对题目要求 {requirement_id}", change)


def project_status(workspace, log):
    with _observation(Path(workspace).resolve(), log.get("copilot")):
        return _project_status(workspace, log)


def _project_status(workspace, log):
    root = Path(workspace).resolve()
    cp = log.get("copilot")
    if not cp:
        return {"requirements": {"total": 0, "verified": 0, "missing": [], "questions": {}},
                "current_task": None, "current_objects": {}, "stale_objects": [],
                "blockers": ["旧状态尚未迁移；评分不构成运行证据"],
                "submission": {"ready": False, "state": "NOT_READY", "blockers": ["缺少版本绑定审计"]}}
    reqs = requirement_status(root, log)
    stale = {x: object_errors(root, cp, x) for x in cp["objects"]}
    stale = {x: errors for x, errors in stale.items() if errors}
    current = {key: obj_id for key, obj_id in cp["current"].items() if obj_id not in stale}
    blockers = [f"{q} 未完成" for q, s in reqs["questions"].items() if s != "verified"]
    if not reqs["total"]:
        blockers.append("Requirement Matrix 尚未建立")
    from copilot_interpretation import projection as interpretation_projection, legacy_errors
    interpretations = interpretation_projection(root, log)
    for item in interpretations:
        if item["kind"] == "AmbiguityEntry" and item["status"] == "open" and item["freeze_gate"] == "blocked":
            blockers.append(f"{item['question']} 题意歧义待解决或带条件假设：{item['payload']['ambiguity_id']}")
        elif item["kind"] == "AssumptionEntry" and item["status"] == "proposed":
            blockers.append(f"{item['question']} 假设尚未明确采纳或拒绝：{item['payload']['assumption_id']}")
        elif item["mathematical_validation"] == "pending":
            blockers.append(f"{item['question']} 已接受假设仍待实际核验：{item['payload']['assumption_id']}")
    for question in reqs["questions"]:
        blockers.extend(legacy_errors(log, question))
    blockers += [f"{x} 待重检" for x in stale if x in cp["current"].values()]
    try:
        from copilot_delivery import submission_status
        submission = submission_status(root, log)
    except ImportError:
        submission = {"ready": False, "state": "NOT_READY", "blockers": ["尚未执行交付审计"]}
    task = cp["tasks"].get(cp.get("current_task"))
    result = {"revision": cp["revision"], "requirements": reqs, "current_task": task,
            "current_objects": current, "stale_objects": stale, "blockers": blockers,
            "next_action": blockers[0] if blockers else (task["title"] if task and task["status"] != "completed" else "执行当前文件的论文与交付审计"),
            "submission": submission}
    if interpretations:
        result["interpretations"] = interpretations
    return result
