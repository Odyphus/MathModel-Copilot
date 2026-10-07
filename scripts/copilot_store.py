"""Single authoritative JSON store; local-process locking and optimistic commits.

The old decision log remains the only authority. Domain objects and projections
are carried in its copilot subtree, not in a competing state file.
"""
from __future__ import annotations

import copy
import errno
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ConflictError(ValueError):
    pass


class IntegrityError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def state_digest(state):
    value = copy.deepcopy(state)
    value.get("copilot", {}).pop("state_hash", None)
    return digest(value)


def new_copilot():
    return {"schema_version": "0.1", "project_id": uuid.uuid4().hex, "revision": 0, "objects": {}, "current": {},
            "requirements": {}, "tasks": {}, "current_task": None,
            "members": {}, "journal": [], "requests": {}, "checks": {},
            "rules_lock": None, "delivery": {}, "decisions": [], "host": None,
            "context_history": {}, "feedback": {}}


def _revision_snapshot(state):
    """Keep exact revision facts without recursively copying the history map.

    The omitted history can be reconstructed from immutable earlier entries.
    Its presence matters for old v0.1 states whose hashes did not include it.
    """
    cp = state["copilot"]
    facts = {key: copy.deepcopy(value) for key, value in state.items() if key != "copilot"}
    facts["copilot"] = {key: copy.deepcopy(value) for key, value in cp.items() if key != "context_history"}
    return {"state": facts,
            "history_revisions": sorted(cp["context_history"], key=int) if "context_history" in cp else None}


def state_at_revision(state, revision):
    """Read a complete, hash-checked historical authority; never consult files."""
    cp = state.get("copilot", {})
    if type(revision) is not int or not 0 <= revision <= cp.get("revision", -1):
        raise ValueError("Context revision 不属于此项目历史")
    if revision == cp["revision"]:
        return copy.deepcopy(state)
    history = cp.get("context_history", {})
    entry = history.get(str(revision))
    if entry is None:
        raise ValueError("该历史 revision 没有完整权威快照；旧版 Context 请重新导出")
    restored = copy.deepcopy(entry["state"])
    earlier = entry["history_revisions"]
    if earlier is not None:
        try:
            restored["copilot"]["context_history"] = {key: copy.deepcopy(history[key]) for key in earlier}
        except KeyError as exc:
            raise IntegrityError("Context 历史快照缺少原有历史") from exc
    expected = next((event["previous_state_hash"] for event in cp["journal"]
                     if event["base_revision"] == revision), None)
    if (not expected or restored["copilot"].get("state_hash") != expected
            or state_digest(restored) != expected):
        raise IntegrityError("Context 历史快照不匹配原始 state_hash")
    return restored


def validate_state(state):
    """Reject malformed nested state, while allowing the original 3.1 schema."""
    if not isinstance(state, dict):
        raise IntegrityError("decision_log 根节点必须是 object")
    stage = state.get("current_stage")
    if type(stage) is not int or not 0 <= stage <= 9:
        raise IntegrityError("current_stage 必须是 0–9 的整数")
    for key in ("stages", "scores", "iterations", "compliance", "problem_meta"):
        if not isinstance(state.get(key), dict):
            raise IntegrityError(f"{key} 必须是 object")
    if not isinstance(state["compliance"].get("ruleset"), dict):
        raise IntegrityError("compliance.ruleset 必须是 object")
    ai = state["compliance"].get("ai_usage")
    if ai is not None and (not isinstance(ai, list) or any(not isinstance(x, dict) for x in ai)):
        raise IntegrityError("compliance.ai_usage 必须是 null 或 object 数组")
    team = state["problem_meta"].get("team_size")
    if team is not None and (type(team) is not int or team < 1):
        raise IntegrityError("team_size 必须是正整数或 null")
    for key, value in state["stages"].items():
        if not isinstance(value, dict):
            raise IntegrityError(f"stages.{key} 必须是 object")
    s5 = state["stages"].get("5", {})
    count = s5.get("qi_count")
    if count is not None and (type(count) is not int or count < 1):
        raise IntegrityError("qi_count 必须是正整数或 null")
    if not isinstance(s5.get("qi_status", {}), dict):
        raise IntegrityError("qi_status 必须是 object")
    weights = s5.get("qi_weights", [])
    if not isinstance(weights, (dict, list)):
        raise IntegrityError("qi_weights 必须是数组或按 Qi ID 的 object")
    for weight in (weights.values() if isinstance(weights, dict) else weights):
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight <= 0:
            raise IntegrityError("qi_weights 必须是有限正数")
    cp = state.get("copilot")
    if cp is not None:
        if not isinstance(cp, dict) or cp.get("schema_version") != "0.1":
            raise IntegrityError("不支持的 copilot schema")
        if type(cp.get("revision")) is not int or cp["revision"] < 0:
            raise IntegrityError("copilot.revision 必须是非负整数")
        for key in ("objects", "current", "requirements", "tasks", "members", "checks", "requests", "delivery"):
            if not isinstance(cp.get(key), dict):
                raise IntegrityError(f"copilot.{key} 必须是 object")
        if not isinstance(cp.get("journal"), list):
            raise IntegrityError("copilot.journal 必须是数组")
        if 'feedback' in cp:
            from copilot_interaction import validate_feedback
            try:
                validate_feedback(cp['feedback'])
            except ValueError as exc:
                raise IntegrityError(str(exc)) from exc
        for object_id, obj in cp["objects"].items():
            if not isinstance(obj, dict) or obj.get("id") != object_id or type(obj.get("version")) is not int:
                raise IntegrityError("对象 ID/version 结构无效")
            if not isinstance(obj.get("payload"), dict) or digest(obj["payload"]) != obj.get("payload_hash"):
                raise IntegrityError(f"对象内容哈希无效: {object_id}")
            if (not isinstance(obj.get("dependencies"), list) or any(x not in cp["objects"] for x in obj["dependencies"])
                    or not isinstance(obj.get("files"), list)):
                raise IntegrityError(f"对象依赖/文件结构无效: {object_id}")
            if obj.get("kind") in {"AmbiguityEntry", "AssumptionEntry"}:
                from copilot_interpretation import validate_payload
                try:
                    validate_payload(obj["kind"], obj["payload"])
                except (ValueError, TypeError, KeyError) as exc:
                    raise IntegrityError(f"歧义/假设结构无效: {object_id}: {exc}") from exc
            elif obj.get("kind") == "AssumptionValidation":
                from copilot_interpretation import validation_receipt_errors
                errors = validation_receipt_errors(cp, obj)
                if errors:
                    raise IntegrityError("; ".join(errors))
        for key, object_id in cp["current"].items():
            if object_id not in cp["objects"] or cp["objects"][object_id].get("key") != key:
                raise IntegrityError("current 指向不存在或不同 key 的对象")
        from copilot_interpretation import validate_source_continuity
        try:
            validate_source_continuity(cp)
        except (ValueError, TypeError, KeyError) as exc:
            raise IntegrityError(f"歧义/假设身份连续性无效: {exc}") from exc
        projection = cp.get("context_projection")
        if projection is not None and (not isinstance(projection, dict)
                or type(projection.get("revision")) is not int or projection["revision"] != cp["revision"]
                or not isinstance(projection.get("version"), str)
                or not isinstance(projection.get("observed_at"), str)
                or not isinstance(projection.get("status"), dict)):
            raise IntegrityError("Context 提交时观测结构或版本无效")
        history = cp.get("context_history", {})
        if not isinstance(history, dict):
            raise IntegrityError("Context 历史快照必须是 object")
        for key, entry in history.items():
            if (not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key
                    or not isinstance(entry, dict) or not isinstance(entry.get("state"), dict)):
                raise IntegrityError("Context 历史快照结构无效")
            archived = entry["state"].get("copilot", {})
            previous = entry.get("history_revisions")
            if (type(archived.get("revision")) is not int or archived["revision"] != int(key)
                    or not 0 <= int(key) < cp["revision"]
                    or archived.get("project_id") != cp["project_id"]
                    or "context_history" in archived
                    or (previous is not None and (not isinstance(previous, list)
                        or any(not isinstance(item, str) or item not in history or int(item) >= int(key) for item in previous)
                        or len(set(previous)) != len(previous)))):
                raise IntegrityError("Context 历史包含无效身份、版本或嵌套历史")
    # JSON itself permits NaN in Python; the contract does not.
    digest(state)


def sync_error_message(exc):
    unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
    if exc.errno in unsupported:
        return ("当前目录的文件系统未能完成文件同步（fsync）。本次写入已停止，未替换原文件。"
                "请将完整项目复制到支持文件同步的本地可写目录，运行 host 检查后重试；"
                "保留原项目，不要通过跳过 fsync 继续写入。")
    return ("文件同步（fsync）失败，本次写入已停止，未替换原文件。"
            "请检查磁盘空间、目录权限和存储设备状态，排除故障后重试。")


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                raise OSError(exc.errno, sync_error_message(exc), str(path)) from exc
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        # Windows readers may briefly omit FILE_SHARE_DELETE. Preserve the
        # atomic replacement and the old authority while that handle closes;
        # permanent denial still fails within a small, fixed retry window.
        deadline = time.monotonic() + 0.75
        while True:
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33} or remaining <= 0:
                    raise
                time.sleep(min(0.025, remaining))
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_authority_text(path):
    """Read current bytes, allowing only bounded Windows sharing retries.

    CRT-backed open can report EACCES without winerror during replacement.
    Never substitute an earlier snapshot or retry parsing/integrity failures.
    """
    deadline = time.monotonic() + 0.75
    while True:
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError as exc:
            remaining = deadline - time.monotonic()
            if (os.name != "nt" or exc.errno != errno.EACCES
                    or getattr(exc, "winerror", None) not in {None, 5, 32, 33}
                    or remaining <= 0):
                raise
            time.sleep(min(0.025, remaining))


@contextmanager
def file_lock(path, timeout=10.0):
    """OS locks release on crash. Never unlink a live lock inode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        started = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() - started >= timeout:
                    raise ConflictError("权威状态正在写入；请重新读取后重试")
                time.sleep(0.025)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")

    def read(self):
        # Opt-in local Git protection guards the transport boundary; it does
        # not store project facts or replace the existing authority checks.
        from copilot_git import assert_authority_boundary
        assert_authority_boundary(self.path.parent.parent)
        value = json.loads(read_authority_text(self.path))
        validate_state(value)
        cp = value.get("copilot", {})
        if cp and cp.get("state_hash") != state_digest(value):
            raise IntegrityError("权威状态哈希不一致：发现绕过事务的修改或损坏，请从可核验备份恢复")
        return value

    def create(self, state):
        with file_lock(self.lock_path):
            if self.path.exists():
                raise FileExistsError(f"{self.path} 已存在，拒绝覆盖")
            value = copy.deepcopy(state)
            value["copilot"] = new_copilot()
            value["_schema_version"] = "4.0"
            validate_state(value)
            self._capture_context_projection(value)
            validate_state(value)
            value["copilot"]["state_hash"] = state_digest(value)
            atomic_write(self.path, value)
            return value

    def _capture_context_projection(self, state):
        # Lazy import avoids a module initialization cycle. The projector takes
        # the supplied state and performs read-only file checks; it never reads
        # Store or starts another transaction.
        from copilot_context import capture_revision_projection
        state["copilot"]["context_projection"] = capture_revision_projection(self.path.parent.parent, state)

    def transact(self, expected_revision, actor, reason, mutate, request_id=None,
                 request_fingerprint=None):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("写入必须携带读取时的非负 expected_revision")
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("actor 和 reason 不能为空")
        with file_lock(self.lock_path):
            before = self.read()
            state = copy.deepcopy(before)
            cp = state.setdefault("copilot", new_copilot())
            if request_id is not None:
                if not isinstance(request_id, str) or not request_id.strip() or not request_fingerprint:
                    raise ValueError("幂等请求必须携带非空 request_id 和 request_fingerprint")
                previous = cp["requests"].get(request_id)
                if previous:
                    if previous["fingerprint"] != request_fingerprint or previous["actor"] != actor:
                        raise ConflictError("request_id 已用于另一项请求")
                    return copy.deepcopy(previous["response"])
            if cp["revision"] != expected_revision:
                raise ConflictError(f"版本冲突：base={expected_revision}, current={cp['revision']}；请重新读取并合并")
            result = mutate(state)
            if state.get("copilot") is not cp or cp["revision"] != expected_revision:
                raise IntegrityError("业务操作不能替换状态容器或修改 revision")
            oldcp = before.get("copilot")
            if oldcp:
                if cp["project_id"] != oldcp["project_id"] or cp["journal"] != oldcp["journal"]:
                    raise IntegrityError("不可改写项目身份或事务历史")
                for key in ("context_history", "context_projection"):
                    if (key in cp) != (key in oldcp) or digest(cp.get(key)) != digest(oldcp.get(key)):
                        raise IntegrityError("Context 历史和提交时观测只能由 Store 生成，不能改写或删除")
                for request, entry in oldcp["requests"].items():
                    if cp["requests"].get(request) != entry:
                        raise IntegrityError("不可改写已有幂等请求")
                feedback_transitions = {
                    'recorded': {'cancelled'}, 'queued': {'running', 'cancelled', 'stale', 'interrupted'},
                    'running': {'cancelling', 'completed', 'failed', 'interrupted', 'stale'},
                    'cancelling': {'cancelled', 'failed', 'interrupted', 'stale'}}
                for key, old_feedback in oldcp.get('feedback', {}).items():
                    new_feedback = cp.get('feedback', {}).get(key)
                    if new_feedback == old_feedback:
                        continue
                    if new_feedback is None:
                        raise IntegrityError('不可删除已记录的意见或分析回执')
                    fixed = lambda row: {k:v for k,v in row.items() if k not in {'status','updated_at','reply','error'}}
                    if fixed(old_feedback) != fixed(new_feedback):
                        raise IntegrityError('不可改写原始意见及其来源；请补充新意见')
                    if new_feedback.get('status') not in feedback_transitions.get(old_feedback['status'], set()):
                        raise IntegrityError('意见处理状态不能回退或改写已完成回执')
                for object_id, original in oldcp["objects"].items():
                    current = cp["objects"].get(object_id)
                    if current is None:
                        raise IntegrityError("不可删除历史对象")
                    if original.get("status") in {"stale", "superseded", "failed", "timeout", "interrupted", "missing_outputs"} and current.get("status") not in {original["status"], "stale"}:
                        raise IntegrityError("无效版本不能复活；请创建新版本并重新核验")
                    immutable = lambda obj: {k: v for k, v in obj.items() if k not in {"status", "stale_reason"}}
                    if immutable(current) != immutable(original):
                        raise IntegrityError(f"不可改写历史对象；请创建新版本: {object_id}")
                for key, object_id in oldcp["current"].items():
                    if oldcp["objects"][object_id]["kind"] in {"AmbiguityEntry", "AssumptionEntry"} and key not in cp["current"]:
                        raise IntegrityError("不可删除当前歧义/假设以绕过冻结；请使用显式审查")
            state["_schema_version"] = "4.0"
            cp["revision"] += 1
            oldcp = before.get("copilot", new_copilot())
            changed_objects = sorted(k for k, v in cp["objects"].items() if v != oldcp["objects"].get(k))
            changed_fields = sorted(k for k, v in state.items() if k != "copilot" and v != before.get(k))
            cp_changes = sorted(k for k, v in cp.items()
                                if k not in {"state_hash", "revision", "journal", "requests", "objects", "context_history", "context_projection"}
                                and v != oldcp.get(k))
            cp["journal"].append({"revision": cp["revision"], "base_revision": expected_revision,
                                  "previous_state_hash": before.get("copilot", {}).get("state_hash"),
                                  "actor": actor, "reason": reason, "at": utc_now(),
                                  "objects": changed_objects, "fields": changed_fields,
                                  "copilot_fields": cp_changes,
                                  "current": copy.deepcopy(cp["current"]),
                                  "stale": sorted(k for k in changed_objects
                                                  if cp["objects"][k].get("status") == "stale")})
            response = {"revision": cp["revision"], "result": result}
            if request_id:
                cp["requests"][request_id] = {"fingerprint": request_fingerprint,
                                              "actor": actor, "response": copy.deepcopy(response)}
            # Archive before changing either Store-owned field. A snapshot has
            # only a list of prior revisions, so history does not nest itself.
            if before.get("copilot"):
                cp.setdefault("context_history", {})[str(expected_revision)] = _revision_snapshot(before)
            # The old cached projection refers to the prior revision. Validate
            # the new authority before running any derived, read-only checks.
            cp.pop("context_projection", None)
            validate_state(state)
            self._capture_context_projection(state)
            validate_state(state)
            cp["state_hash"] = state_digest(state)
            atomic_write(self.path, state)
            return response
