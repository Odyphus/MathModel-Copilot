"""Versioned interpretation decisions in the existing Store, not a new authority.

Recorded review decisions are not proof of human identity or mathematical truth.
Assumption validation is a downstream receipt, so evidence never creates a cycle
back into the accepted assumption on which a run depends.
"""
from __future__ import annotations

import copy
import re

import copilot_domain as domain
from copilot_store import utc_now, digest

KINDS = {"AmbiguityEntry", "AssumptionEntry"}
SEVERITIES = {"low": 0, "medium": 1, "high": 2, "critical": 3}
FIELDS = {
    "AmbiguityEntry": {"ambiguity_id", "question", "source_anchor", "interpretations", "severity",
                       "impact", "owner", "requirement_ids", "status", "evidence_refs"},
    "AssumptionEntry": {"assumption_id", "question", "statement", "rationale", "impact", "testability",
                        "linked_requirement_ids", "linked_ambiguity_ids", "reversible", "sensitivity_required",
                        "validation_plan", "validation_checks", "status", "evidence_refs"},
}


def _strings(value, label, *, minimum=0):
    if (not isinstance(value, list) or len(value) < minimum
            or any(not isinstance(x, str) or not x.strip() for x in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{label} 必须是无重复的非空文本数组，至少 {minimum} 项")


def validate_payload(kind, data):
    if kind not in KINDS or not isinstance(data, dict):
        raise ValueError("不支持的歧义/假设记录")
    id_name = "ambiguity_id" if kind == "AmbiguityEntry" else "assumption_id"
    if not isinstance(data.get(id_name), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", data[id_name]):
        raise ValueError(f"{id_name} 必须是稳定 ASCII 标识")
    question = data.get("question")
    if not isinstance(question, str) or not re.fullmatch(r"Q[1-9][0-9]*", question):
        raise ValueError("question 必须是已声明的 Q编号")
    rids = data.get("requirement_ids" if kind == "AmbiguityEntry" else "linked_requirement_ids")
    _strings(rids, "关联 Requirement", minimum=1)
    if any(not re.fullmatch(rf"REQ-{question}-[0-9]{{3,}}", rid) for rid in rids):
        raise ValueError("歧义/假设须关联同一小问的具体 Requirement")
    required = ("source_anchor", "impact", "owner") if kind == "AmbiguityEntry" else ("statement", "rationale", "impact", "testability")
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in required):
        raise ValueError("歧义/假设缺少必要说明：" + ", ".join(required))
    _strings(data.get("evidence_refs", []), "evidence_refs")
    legacy = data.get("legacy_sources", [])
    field = "ambiguities" if kind == "AmbiguityEntry" else "assumptions"
    if (not isinstance(legacy, list) or any(not isinstance(row, dict)
            or set(row) != {"stage", "index", "field", "sha256"}
            or not isinstance(row["stage"], str) or not row["stage"]
            or type(row["index"]) is not int or row["index"] < 0 or row["field"] != field
            or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            for row in legacy)):
        raise ValueError("legacy_sources 必须保留明确的旧 Stage 内容绑定")
    if kind == "AmbiguityEntry":
        _strings(data.get("interpretations"), "interpretations", minimum=2)
        if (not isinstance(data.get("severity"), str) or data["severity"] not in SEVERITIES
                or not isinstance(data.get("status"), str) or data["status"] not in {"open", "resolved"}):
            raise ValueError("歧义 severity/status 非法")
        if data["status"] == "resolved" and data.get("resolution") not in data["interpretations"]:
            raise ValueError("解决歧义必须明确选择一个已记录解释")
        reviewed = data["status"] == "resolved"
    else:
        if not isinstance(data.get("status"), str) or data["status"] not in {"proposed", "accepted", "rejected"}:
            raise ValueError("假设 status 非法；数学验证须使用真实结果的独立回执")
        if type(data.get("reversible")) is not bool or type(data.get("sensitivity_required")) is not bool:
            raise ValueError("reversible/sensitivity_required 必须是布尔值")
        _strings(data.get("linked_ambiguity_ids", []), "linked_ambiguity_ids")
        _strings(data.get("validation_checks", []), "validation_checks")
        if data["status"] == "accepted" and (not data.get("validation_checks") or not isinstance(data.get("validation_plan"), str)
                                               or not data["validation_plan"].strip()):
            raise ValueError("接受假设必须预先声明 validation_plan 和 validation_checks")
        reviewed = data["status"] in {"accepted", "rejected"}
    if reviewed:
        review = data.get("review")
        expected = "resolve" if kind == "AmbiguityEntry" else "accept" if data["status"] == "accepted" else "reject"
        if (not isinstance(review, dict) or review.get("action") != expected
                or any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("actor", "rationale", "at"))):
            raise ValueError("采纳/解决必须来自显式 review 记录，不能由 Stage 文本升级")
        if kind == "AmbiguityEntry" and not review.get("evidence_files"):
            raise ValueError("解决歧义必须绑定实际来源证据文件")


def records(cp, question=None):
    return [cp["objects"][oid] for oid in cp.get("current", {}).values()
            if cp["objects"][oid]["kind"] in KINDS
            and (question is None or cp["objects"][oid]["payload"]["question"] == question)]


def _key(kind, data):
    return "interpretation." + ("ambiguity." + data["ambiguity_id"] if kind == "AmbiguityEntry"
                                else "assumption." + data["assumption_id"])


def validate_source_continuity(cp):
    """Stable source identities cannot disappear through a new object version.

    Enforced at Store read/commit as well as Runtime inputs. Historic versions
    keep their original review status; only the latest source may be current.
    """
    for old in cp["objects"].values():
        kind = old["kind"]
        if kind not in KINDS:
            continue
        key, data = old["key"], old["payload"]
        if key != _key(kind, data):
            raise ValueError("歧义/假设 key 必须匹配其稳定标识")
        new = cp["objects"].get(cp["current"].get(key))
        if not new or new["kind"] != kind or new["key"] != key:
            raise ValueError("不可替换当前歧义/假设的对象类型或移除其身份")
        current = new["payload"]
        identifier = "ambiguity_id" if kind == "AmbiguityEntry" else "assumption_id"
        if current.get(identifier) != data[identifier] or current.get("question") != data["question"]:
            raise ValueError("歧义/假设的新版本不可改绑稳定标识或小问")
        if new["version"] < old["version"]:
            raise ValueError("当前歧义/假设不可回退到历史版本")
        if kind == "AmbiguityEntry" and SEVERITIES[current["severity"]] < SEVERITIES[data["severity"]]:
            raise ValueError("歧义的新版本不得降低历史 severity")
        if any(row not in current.get("legacy_sources", []) for row in data.get("legacy_sources", [])):
            raise ValueError("歧义/假设的新版本不可丢弃旧 Stage 来源绑定")


def _invalidate_question(cp, question, reason):
    from copilot_runtime import _propagate
    contracts = [oid for oid in cp["current"].values() if cp["objects"][oid]["kind"] == "ProblemContract"
                 and cp["objects"][oid]["payload"]["question"] == question]
    return _propagate(cp, contracts, reason)


def _scope(state, kind, data):
    validate_payload(kind, data)
    count = state["stages"]["5"].get("qi_count")
    if type(count) is not int or data["question"] not in {f"Q{i}" for i in range(1, count + 1)}:
        raise ValueError("先声明完整 question_count，再记录对应小问歧义/假设")
    cp = state["copilot"]
    rids = data["requirement_ids" if kind == "AmbiguityEntry" else "linked_requirement_ids"]
    for rid in rids:
        existing = cp["requirements"].get(rid)
        if existing and (existing["question"] != data["question"] or not existing.get("active", True)):
            raise ValueError("关联 Requirement 不属于当前小问")


def _assumption_dependencies(root, cp, data):
    from copilot_runtime import usable
    deps = []
    for aid in data.get("linked_ambiguity_ids", []):
        matches = [obj for obj in records(cp, data["question"])
                   if obj["kind"] == "AmbiguityEntry" and obj["payload"]["ambiguity_id"] == aid]
        if len(matches) != 1 or not usable(root, cp, matches[0]["id"]):
            raise ValueError("假设关联的歧义必须是同问当前有效记录：" + aid)
        if not set(matches[0]["payload"]["requirement_ids"]) <= set(data["linked_requirement_ids"]):
            raise ValueError("假设必须覆盖所关联歧义的全部 Requirement")
        deps.append(matches[0]["id"])
    return deps


def _legacy_rows(state, kind):
    field = "ambiguities" if kind == "AmbiguityEntry" else "assumptions"
    for stage_id, stage in state.get("stages", {}).items():
        values = stage.get(field)
        if not values:
            continue
        values = values if isinstance(values, list) else [values]
        for index, row in enumerate(values):
            yield {"stage": stage_id, "index": index, "field": field, "sha256": digest(row)}, row


def _legacy_bindings(state, kind, data, explicit_refs):
    if not isinstance(explicit_refs, list) or any(not isinstance(row, dict) or set(row) != {"stage", "index"}
                                                or not isinstance(row["stage"], str) or type(row["index"]) is not int
                                                or row["index"] < 0 for row in explicit_refs):
        raise ValueError("legacy_refs 须为 stage 文本与 index 非负整数组成的来源数组")
    requested = {(row["stage"], row["index"]) for row in explicit_refs}
    found, bindings = set(), []
    identifier = "ambiguity_id" if kind == "AmbiguityEntry" else "assumption_id"
    for binding, row in _legacy_rows(state, kind):
        position = (binding["stage"], binding["index"])
        automatic = isinstance(row, dict) and row.get(identifier) == data[identifier] and row.get("question") in {None, "", data["question"]}
        if not automatic and position not in requested:
            continue
        if isinstance(row, dict):
            if row.get("question") not in {None, "", data["question"]} or row.get(identifier) not in {None, "", data[identifier]}:
                raise ValueError("旧记录的小问或稳定标识不匹配")
            if kind == "AmbiguityEntry":
                old_severity = row.get("severity")
                if old_severity not in SEVERITIES or SEVERITIES[data["severity"]] < SEVERITIES[old_severity]:
                    raise ValueError("旧 Stage 歧义迁入不得降低或忽略原 severity")
                old_options = row.get("interpretations")
                if isinstance(old_options, list) and not set(old_options) <= set(data["interpretations"]):
                    raise ValueError("旧歧义迁入不得删去已有 interpretations")
            elif row.get("statement") and row["statement"] != data["statement"]:
                raise ValueError("旧假设迁入须保留原 statement；迁入后才能显式修订")
        bindings.append(binding)
        found.add(position)
    if requested - found:
        raise ValueError("legacy_refs 指向不存在的旧 Stage 记录")
    return bindings


def record(rt, revision, kind, payload, *, actor="modeler", request_id=None):
    if kind not in KINDS or not isinstance(payload, dict) or set(payload) - FIELDS[kind] - {"legacy_refs"}:
        raise ValueError("歧义/假设字段不支持；resolved/accepted 必须走显式 review")
    initial = "open" if kind == "AmbiguityEntry" else "proposed"
    if payload.get("status", initial) != initial:
        raise ValueError("新增/修订只能记录 open/proposed；采纳或解决请使用 review")
    from copilot_runtime import _put, bind_file

    def change(state):
        cp = state["copilot"]
        values = dict(payload, status=initial)
        legacy_refs = values.pop("legacy_refs", [])
        cls = domain.AmbiguityEntry if kind == "AmbiguityEntry" else domain.AssumptionEntry
        try:
            data = cls(**values).to_dict()
        except TypeError as exc:
            raise ValueError("歧义/假设字段缺失或类型错误：" + str(exc)) from exc
        _scope(state, kind, data)
        data["legacy_sources"] = _legacy_bindings(state, kind, data, legacy_refs)
        key = _key(kind, data)
        old = cp["objects"].get(cp["current"].get(key))
        if old:
            if old["payload"]["question"] != data["question"]:
                raise ValueError("稳定歧义/假设标识不可改绑小问")
            if kind == "AmbiguityEntry" and SEVERITIES[data["severity"]] < SEVERITIES[old["payload"]["severity"]]:
                raise ValueError("不得通过降低 severity 绕过未解决歧义；请明确解决并保留依据")
            # Explicit migration provenance remains present in every later version.
            data["legacy_sources"] += [row for row in old["payload"].get("legacy_sources", []) if row not in data["legacy_sources"]]
        data = domain.seal_record(data)
        deps = _assumption_dependencies(rt.root, cp, data) if kind == "AssumptionEntry" else []
        files = [bind_file(rt.root, name) for name in data["evidence_refs"]]
        oid = _put(state, kind, key, data, deps, files, "recorded")
        affected = _invalidate_question(cp, data["question"], "题意歧义/假设发生变化，须重新冻结合同并重检下游")
        return {"object_id": oid, "status": initial, "invalidated": affected}
    return rt._tx(revision, actor, "记录歧义/假设候选", change, request_id,
                  {"kind": kind, "payload": payload})


def review(rt, revision, object_id, *, action, rationale, evidence_files=(), resolution=None,
           result_ids=(), actor="integrator"):
    from copilot_runtime import _put, bind_file, usable, evidence_requirements
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("review 必须说明 rationale")
    _strings(list(evidence_files) if isinstance(evidence_files, tuple) else evidence_files, "evidence_files")
    _strings(list(result_ids) if isinstance(result_ids, tuple) else result_ids, "result_ids")

    def change(state):
        cp = state["copilot"]
        old = cp["objects"].get(object_id)
        if not old or old["kind"] not in KINDS or not usable(rt.root, cp, object_id):
            raise ValueError("只能审查当前有效歧义/假设版本")
        kind, data = old["kind"], copy.deepcopy(old["payload"])
        files = [bind_file(rt.root, name) for name in evidence_files]
        event = {"action": action, "rationale": rationale, "actor": actor, "at": utc_now(),
                 "evidence_files": files, "identity_scope": "recorded_actor_not_authenticated_human"}
        if action == "validate":
            if kind != "AssumptionEntry" or data["status"] != "accepted" or not result_ids:
                raise ValueError("数学验证须绑定已接受假设及真实 Result")
            required = set(data["validation_checks"])
            seen = set()
            for rid in result_ids:
                obj = cp["objects"].get(rid)
                if not obj or obj["kind"] != "ResultRecord" or not usable(rt.root, cp, rid, verified=True):
                    raise ValueError("假设验证结果已过期或未核验")
                if obj["payload"]["question"] != data["question"] or not set(data["linked_requirement_ids"]) <= evidence_requirements(cp, rid):
                    raise ValueError("假设验证 Result 的小问或 Requirement 不匹配")
                closure, pending = set(), [rid]
                while pending:
                    current = pending.pop()
                    if current in closure:
                        continue
                    closure.add(current)
                    pending.extend(cp["objects"][current]["dependencies"])
                if object_id not in closure:
                    raise ValueError("Result 并非依据此假设版本执行，不能事后借用")
                report = cp["objects"][obj["payload"]["validation_id"]]["payload"]
                seen.update(row["check_id"] for row in report["checks"] if row["status"] == "pass" and row.get("predeclared"))
            if not required <= seen:
                raise ValueError("实际核验缺少预定假设检查：" + ", ".join(sorted(required - seen)))
            body = domain.seal_record({"question": data["question"], "assumption_object_id": object_id,
                                       "checks": sorted(required), "result_ids": list(result_ids), "review": event})
            oid = _put(state, "AssumptionValidation", "interpretation.validation." + data["assumption_id"],
                       body, [object_id, *result_ids], files, "verified")
            return {"object_id": oid, "status": "validated", "scope": "predeclared_checks_only"}
        if result_ids:
            raise ValueError("result_ids 仅用于 validate，不得伪装普通 review 为数学核验")
        if kind == "AmbiguityEntry":
            if action == "resolve" and data["status"] == "open":
                if resolution not in data["interpretations"] or not files:
                    raise ValueError("resolve 须选择已记录的 resolution 并绑定真实来源 evidence_files")
                data.update(status="resolved", resolution=resolution)
            elif action == "reopen" and data["status"] == "resolved":
                data.update(status="open", resolution="")
            else:
                raise ValueError("歧义 review 状态转换非法")
        else:
            if resolution is not None:
                raise ValueError("resolution 仅适用于歧义")
            if action in {"accept", "reject"} and data["status"] == "proposed":
                data["status"] = "accepted" if action == "accept" else "rejected"
            elif action == "reopen" and data["status"] in {"accepted", "rejected"}:
                data["status"] = "proposed"
            else:
                raise ValueError("假设 review 状态转换非法")
        data.update(review=event, timestamp=utc_now(), event_type=action,
                    parent_record_hash=old["payload"].get("record_hash", ""))
        validate_payload(kind, data)
        data = domain.seal_record(data)
        oid = _put(state, kind, old["key"], data, old["dependencies"], old["files"] + files, "recorded")
        affected = _invalidate_question(cp, data["question"], "歧义/假设决定发生变化，须重新冻结合同并重检下游")
        return {"object_id": oid, "status": data["status"], "invalidated": affected}
    return rt._tx(revision, actor, f"显式审查歧义/假设：{action}", change)


def legacy_errors(state, question):
    """Old Stage descriptions remain readable but never confer review status."""
    cp = state["copilot"]
    known = {(obj["kind"], digest(binding)) for obj in records(cp, question)
             for binding in obj["payload"].get("legacy_sources", [])}
    errors = []
    for kind in KINDS:
        for binding, row in _legacy_rows(state, kind):
            if isinstance(row, dict) and row.get("question") not in {None, "", question}:
                continue
            if (kind, digest(binding)) not in known:
                errors.append(f"{question} 的旧 Stage {binding['field']} 需显式迁入权威记录；原文字状态不能代替审查")
    return errors


def validation_receipt_errors(cp, obj):
    """Validate new receipt types even when inserted through a generic Store tx.

    Structural checks apply to retained historical records too. Currentness and
    disk observations are additionally checked through the normal dependency DAG.
    """
    try:
        data = obj["payload"]
        source_id = data.get("assumption_object_id")
        source = cp["objects"].get(source_id)
        if not source or source["kind"] != "AssumptionEntry" or source["payload"]["status"] != "accepted":
            return ["AssumptionValidation 缺少实际已接受的假设版本"]
        declared = source["payload"]
        if data.get("question") != declared["question"]:
            return ["AssumptionValidation 小问不匹配"]
        _strings(data.get("result_ids"), "AssumptionValidation result_ids", minimum=1)
        _strings(data.get("checks"), "AssumptionValidation checks", minimum=1)
        if set(obj["dependencies"]) != {source_id, *data["result_ids"]}:
            return ["AssumptionValidation 依赖必须精确绑定源假设和实际 Result"]
        review = data.get("review", {})
        if (review.get("action") != "validate"
                or any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("actor", "rationale", "at"))):
            return ["AssumptionValidation 缺少显式核验回执"]
        if set(data["checks"]) != set(declared["validation_checks"]):
            return ["AssumptionValidation 必须覆盖源假设的完整预定检查"]
        seen = set()
        from copilot_runtime import evidence_requirements
        for rid in data["result_ids"]:
            result = cp["objects"].get(rid)
            if not result or result["kind"] != "ResultRecord" or result["payload"].get("question") != declared["question"]:
                return ["AssumptionValidation Result 不存在或小问不一致"]
            if not set(declared["linked_requirement_ids"]) <= evidence_requirements(cp, rid):
                return ["AssumptionValidation Result 未覆盖假设 Requirement"]
            run = cp["objects"].get(result["payload"].get("run_id"))
            report = cp["objects"].get(result["payload"].get("validation_id"))
            if (not run or run["kind"] != "RunRecord" or not report or report["kind"] != "ValidationReport"
                    or set(result["dependencies"]) != {run["id"], report["id"]}
                    or run["id"] not in report["dependencies"]
                    or run.get("execution", {}).get("returncode") != 0
                    or report.get("execution", {}).get("passed") is not True
                    or report["payload"].get("status") != "pass"):
                return ["AssumptionValidation 结果没有真实成功运行与核验回执"]
            if obj.get("status") == "verified" and any(row.get("status") != "verified" for row in (result, run, report)):
                return ["AssumptionValidation 不能借用未核验或失效的结果"]
            closure, pending = set(), [rid]
            while pending:
                current = pending.pop()
                if current in closure:
                    continue
                closure.add(current)
                pending.extend(cp["objects"][current]["dependencies"])
            if source_id not in closure:
                return ["AssumptionValidation Result 没有依据该假设版本执行"]
            seen.update(row["check_id"] for row in report["payload"]["checks"] if row["status"] == "pass" and row.get("predeclared"))
        if not set(data["checks"]) <= seen:
            return ["AssumptionValidation 缺少实际通过的预定检查"]
        return []
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        return ["AssumptionValidation 结构无效：" + str(exc)]


def freeze_inputs(root, state, contract):
    from copilot_runtime import object_errors
    selected = records(state["copilot"], contract.question)
    errors = legacy_errors(state, contract.question)
    requirements = {r.req_id for r in contract.requirements}
    for obj in selected:
        errors.extend(object_errors(root, state["copilot"], obj["id"]))
        data = obj["payload"]
        field = "requirement_ids" if obj["kind"] == "AmbiguityEntry" else "linked_requirement_ids"
        if not set(data[field]) <= requirements:
            errors.append("合同不得遗漏歧义/假设关联的 Requirement")
        if obj["kind"] == "AssumptionEntry" and data["status"] == "proposed":
            errors.append("假设尚未明确接受或拒绝：" + data["assumption_id"])
    ambiguities = [x["payload"] for x in selected if x["kind"] == "AmbiguityEntry"]
    assumptions = [x["payload"] for x in selected if x["kind"] == "AssumptionEntry"]
    return errors, ambiguities, assumptions, [x["id"] for x in selected]


def pending_validation(root, cp, question=None):
    from copilot_runtime import usable
    pending = []
    for obj in records(cp, question):
        if obj["kind"] != "AssumptionEntry" or obj["payload"]["status"] != "accepted":
            continue
        receipts = [cp["objects"][oid] for oid in cp["current"].values()
                    if cp["objects"][oid]["kind"] == "AssumptionValidation"
                    and cp["objects"][oid]["payload"]["assumption_object_id"] == obj["id"]]
        if not any(usable(root, cp, row["id"], verified=True) for row in receipts):
            pending.append(obj["id"])
    return pending


def projection(root, state):
    from copilot_runtime import object_errors
    cp = state["copilot"]
    pending = set(pending_validation(root, cp))
    current = records(cp)
    rows = []
    for obj in current:
        data = obj["payload"]
        errors = object_errors(root, cp, obj["id"])
        gate = "blocked" if errors else "clear"
        if obj["kind"] == "AmbiguityEntry" and data["status"] == "open":
            accepted = [entry for entry in current if entry["kind"] == "AssumptionEntry"
                        and entry["payload"]["question"] == data["question"]
                        and data["ambiguity_id"] in entry["payload"]["linked_ambiguity_ids"]
                        and entry["payload"]["status"] == "accepted" and entry["payload"]["reversible"]
                        and not object_errors(root, cp, entry["id"])]
            gate = "conditional" if not errors and data["severity"] in {"low", "medium"} and accepted else "blocked"
        elif obj["kind"] == "AssumptionEntry" and data["status"] == "proposed":
            gate = "blocked"
        rows.append({"object_id": obj["id"], "kind": obj["kind"], "question": data["question"],
                     "status": data["status"], "payload": copy.deepcopy(data), "freeze_gate": gate,
                     "current_errors": errors,
                     "mathematical_validation": "pending" if obj["id"] in pending else
                         "validated_checks" if obj["kind"] == "AssumptionEntry" and data["status"] == "accepted" else "not_claimed"})
    return rows
