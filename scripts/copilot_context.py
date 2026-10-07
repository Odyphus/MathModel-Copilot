"""Task-scoped, read-only contexts and explicit receipt/adoption/review records."""
from __future__ import annotations

import copy
from copilot_store import digest, ConflictError, utc_now, state_at_revision
from copilot_runtime import Runtime, ROLES, usable, project_status, bind_file

PROJECTION_VERSION = "0.1.1"

ROLE_KINDS = {
    "modeler": {"ProblemContract", "ModelSpec", "ParameterSet", "ValidationPlan", "ValidationReport", "AmbiguityEntry", "AssumptionEntry", "AssumptionValidation"},
    "coder": {"ModelSpec", "ParameterSet", "DataContract", "CodeManifest", "RunRecord", "ValidationPlan", "ValidationReport"},
    "writer": {"EvidenceMapEntry", "ResultRecord", "PaperSection", "ArtifactRecord", "ValidationReport"},
}


def capture_revision_projection(workspace, state):
    """Store-only commit observation; no Store calls, writes, or new authority.

    Keeping the derived result at its revision makes historical file and
    validator observations replayable without pretending that today's files
    existed at that time. New exports also compare it with live observations.
    """
    projection = {"version": PROJECTION_VERSION, "revision": state["copilot"]["revision"],
                  "observed_at": utc_now(), "status": project_status(workspace, state)}
    if state['copilot'].get('feedback'):
        from copilot_interaction import basis
        projection['feedback_basis'] = basis(workspace, state)
    return projection


def _recorded_status(state):
    cp = state["copilot"]
    record = cp.get("context_projection")
    if not record:
        raise ConflictError("该 revision 没有完整 Context 观测；请显式 reconcile 后重新导出，不能补造旧历史")
    if record["version"] != PROJECTION_VERSION:
        raise ConflictError(f"不支持 Context projection_version={record['version']}；当前项目请显式 reconcile 升级后导出，历史版本须用相应投影器")
    return record["status"]


def _received_cursor(record):
    """Only contiguous, explicitly receipted event ranges count as sync.

    Legacy receipts have no range and cannot certify cumulative coverage.
    Their original declarations remain in the history and member record.
    """
    ranges = []
    for item in record.get("receipts", []):
        start, end = item.get("changes_since"), item.get("revision")
        if type(start) is int and type(end) is int and 0 <= start <= end:
            ranges.append((start, end))
    cursor = 0
    for start, end in sorted(ranges):
        if start > cursor:
            break
        cursor = max(cursor, end)
    return cursor


def _revision_context(state, *, role, task_id=None, member=None, since=None, selection=None):
    """Pure, complete projection of a retained revision and declared selectors."""
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError("未知角色")
    if member is not None and (not isinstance(member, str) or not member.strip()):
        raise ValueError("Context member 必须是非空成员名或 null")
    cp = state["copilot"]
    status = _recorded_status(state)
    if selection is None:
        selection = {"task": "current" if task_id is None else "explicit",
                     "baseline": ("member_received" if member else "origin") if since is None else "explicit"}
    if (not isinstance(selection, dict) or set(selection) != {"task", "baseline"}
            or selection["task"] not in {"current", "explicit", "all"}
            or selection["baseline"] not in {"member_received", "origin", "explicit"}):
        raise ValueError("Context 角色/任务/基线选择结构无效")
    if selection["baseline"] == "member_received":
        if member is None:
            raise ValueError("成员接收基线必须绑定成员")
        since = _received_cursor(cp["members"].get(member, {}))
    elif selection["baseline"] == "origin":
        since = 0
    if type(since) is not int or not 0 <= since <= cp["revision"]:
        raise ValueError("累计变化基线不属于源版本历史")
    if selection["task"] == "current":
        task_id = cp.get("current_task")
    elif selection['task'] == 'all':
        task_id = None
    elif not isinstance(task_id, str) or not task_id:
        raise ValueError("显式 Task ID 必须是非空标识")
    task = cp["tasks"].get(task_id) if task_id else None
    if task_id and not task:
        raise ValueError("Task 不存在")
    current = status["current_objects"]
    common = {"project_id": cp["project_id"], "competition": state["competition"],
              "problem": state["problem_meta"], "navigation_stage": state["current_stage"],
              "requirements": status["requirements"], "current": current,
              "decisions": cp["decisions"], "blockers": status["blockers"],
              "stale_objects": status["stale_objects"], "submission": status["submission"],
              "contracts": {}, "models": {}, "parameters": {}, "verified_results": {}}
    # User feedback is attributed input, not an adopted modeling decision.
    # Optional on historical snapshots, derived exactly like other common facts.
    if cp.get('feedback'):
        common['feedback'] = copy.deepcopy(cp['feedback'])
        for row in common['feedback'].values():
            if row['status'] == 'completed' and row['basis'] != cp['context_projection'].get('feedback_basis'):
                row.update(status='stale', error='项目依据已变化，此回复仅供历史参考，请重新分析。')
    if status.get("interpretations"):
        common["interpretations"] = copy.deepcopy(status["interpretations"])
    buckets = {"ProblemContract": "contracts", "ModelSpec": "models", "ParameterSet": "parameters", "ResultRecord": "verified_results"}
    for obj_id in current.values():
        obj = cp["objects"][obj_id]
        bucket = buckets.get(obj["kind"])
        if bucket:
            payload = obj["payload"]
            if obj["kind"] == "ResultRecord" and obj["status"] != "verified":
                continue
            common[bucket][obj_id] = {"payload_hash": obj["payload_hash"], "question": payload.get("question"),
                                     "payload": payload}
    # Task inputs/outputs and their dependency closure are included even when
    # they fall outside the role's preferred view.
    selected = set(task.get("dependencies", []) + task.get("outputs", [])) if task else set()
    if task:
        for rid in task.get("requirements", []):
            req = cp["requirements"][rid]
            selected.add(req["contract_id"])
            selected.update(req.get("coverage", {}).values())
    else:
        kinds = ROLE_KINDS.get(role)
        selected.update(x for x in current.values() if kinds is None or cp["objects"][x]["kind"] in kinds)
    pending = list(selected)
    while pending:
        obj_id = pending.pop()
        for dep in cp["objects"][obj_id]["dependencies"]:
            if dep not in selected:
                selected.add(dep)
                pending.append(dep)
    objects = {x: copy.deepcopy(cp["objects"][x]) for x in sorted(selected)}
    for obj_id, obj in objects.items():
        errors = status["stale_objects"].get(obj_id, [])
        obj["current_errors"] = copy.deepcopy(errors)
        if errors:
            obj["status"] = "stale"
    result = {"schema_version": PROJECTION_VERSION, "projection_version": PROJECTION_VERSION,
              "file_observation": {"basis": "source_revision_commit", "at": cp["context_projection"]["observed_at"]},
              "selection": copy.deepcopy(selection),
              "project_id": cp["project_id"], "source_revision": cp["revision"],
              "source_state_hash": cp["state_hash"], "role": role, "member": member,
              "task_id": task_id, "task": copy.deepcopy(task), "common": common, "common_hash": digest(common),
              "objects": objects, "changes_since": since,
              "changes": [copy.deepcopy(x) for x in cp["journal"] if x["revision"] > since],
              "next_action": status["next_action"]}
    result["context_id"] = digest(result)
    return copy.deepcopy(result)


def build_context(workspace, *, role, task_id=None, member=None, since=None, all_tasks=False):
    """Export without writing; require an explicit transaction after drift."""
    rt = Runtime(workspace)
    state = rt.read()
    if not state.get("copilot"):
        raise ValueError("请先 migrate 旧状态")
    recorded = _recorded_status(state)
    if digest(recorded) != digest(project_status(rt.root, state)):
        raise ConflictError("文件或校验规则已偏离该 revision 的 Context 观测；请显式 reconcile 后重新导出")
    if all_tasks and task_id is not None:
        raise ValueError('全项目 Context 不能同时指定任务')
    selection = ({'task':'all', 'baseline':('member_received' if member else 'origin')
                  if since is None else 'explicit'} if all_tasks else None)
    return _revision_context(state, role=role, task_id=task_id, member=member, since=since, selection=selection)


def _difference(shown, expected, path="Context"):
    """Exact shape, value and JSON type comparison, including absent/extra keys."""
    if type(shown) is not type(expected):
        return path
    if isinstance(expected, dict):
        if set(shown) != set(expected):
            return path + " 字段/对象集合"
        for key in expected:
            mismatch = _difference(shown[key], expected[key], path + "." + key)
            if mismatch:
                return mismatch
    elif isinstance(expected, list):
        if len(shown) != len(expected):
            return path + " 数组长度"
        for index, (actual, wanted) in enumerate(zip(shown, expected)):
            mismatch = _difference(actual, wanted, f"{path}[{index}]")
            if mismatch:
                return mismatch
    elif shown != expected:
        return path
    return None


def acknowledge(workspace, revision, snapshot, *, member, action, object_ids=(),
                actor_kind="agent", note="", evidence=None):
    if action not in {"received", "adopted", "verified"}:
        raise ValueError("action 必须是 received/adopted/verified")
    if not member or not isinstance(member, str):
        raise ValueError("member 不能为空")
    if not isinstance(snapshot, dict):
        raise ValueError("Context 必须是 object")
    raw = copy.deepcopy(snapshot)
    context_id = raw.pop("context_id", None)
    if context_id != digest(raw):
        raise ValueError("Context 已损坏或被修改")
    if snapshot.get("member") is not None and snapshot.get("member") != member:
        raise ValueError("Context 属于另一成员")
    rt = Runtime(workspace)
    def change(state):
        cp = state["copilot"]
        if snapshot.get("project_id") != cp["project_id"]:
            raise ValueError("Context 来自另一项目")
        if snapshot.get("schema_version") != PROJECTION_VERSION or snapshot.get("projection_version") != PROJECTION_VERSION:
            raise ValueError("旧版或不支持的 Context 投影格式；请重新导出，不能用旧哈希认证缺失的历史事实")
        seen_revision = snapshot.get("source_revision")
        source = state_at_revision(state, seen_revision)
        if not isinstance(snapshot.get("selection"), dict):
            raise ValueError("Context 缺少角色/任务/基线选择依据")
        expected = _revision_context(source, role=snapshot.get("role"), member=snapshot.get("member"),
                                     task_id=snapshot.get("task_id"), since=snapshot.get("changes_since"),
                                     selection=snapshot["selection"])
        mismatch = _difference(snapshot, expected)
        if mismatch:
            raise ValueError(f"Context 与 revision {seen_revision} 的完整权威投影不一致: {mismatch}")
        record = cp["members"].setdefault(member, {"received_revision": 0, "receipts": [], "adoptions": [], "verifications": []})
        if action == "received":
            if any("changes_since" not in item for item in record["receipts"]):
                record.setdefault("legacy_received_revision", record["received_revision"])
            receipt = {"context_id": context_id, "revision": seen_revision,
                       "changes_since": snapshot["changes_since"], "at": utc_now()}
            record["receipts"].append(receipt)
            record["received_revision"] = _received_cursor(record)
            receipt["scope"] = "cumulative_history" if record["received_revision"] >= seen_revision else "partial_history"
            receipt["received_revision_after"] = record["received_revision"]
        else:
            if not any(x["context_id"] == context_id for x in record["receipts"]):
                raise ValueError("必须先明确接收此 Context；收到不等于采用")
            if not object_ids or any(x not in snapshot["objects"] for x in object_ids):
                raise ValueError("只能采用/核验该 Task Context 实际包含的对象")
            for obj_id in object_ids:
                if not usable(rt.root, cp, obj_id):
                    raise ConflictError(f"{obj_id} 已过期，请重新获取 Context")
                current = cp["objects"][obj_id]
                if snapshot["objects"][obj_id]["payload_hash"] != current["payload_hash"]:
                    raise ConflictError("Context 对象版本已变化")
            item = {"context_id": context_id, "source_revision": seen_revision, "object_ids": list(object_ids),
                    "at": utc_now(), "note": note, "actor_kind": actor_kind}
            if action == "adopted":
                record["adoptions"].append(item)
            else:
                if actor_kind not in {"human", "agent_evaluator"} or len(note.strip()) < 8 or not evidence:
                    raise ValueError("核验须声明真实核验身份、范围说明和证据；agent 不得冒充 human")
                if not all(any(obj_id in x["object_ids"] for x in record["adoptions"]) for obj_id in object_ids):
                    raise ValueError("该成员尚未采用所核验对象")
                item["evidence"] = bind_file(rt.root, evidence)
                record["verifications"].append(item)
        return copy.deepcopy(record)
    return rt._tx(revision, member, f"Context {action}", change)
