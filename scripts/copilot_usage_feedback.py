"""Private usage-feedback drafts and explicitly authorized GitHub issues.

Human requests are recorded attestations, not authentication. This module does
not defend against malicious local processes rewriting code or private files.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from copilot_experience import ExperienceStorage, _safe_component
from copilot_store import file_lock, utc_now

COMPONENTS = {"installation": "安装", "dashboard": "建模工作台", "workflow": "建模流程",
              "paper": "论文辅助", "handoff": "任务交接", "documentation": "使用说明"}
EVENTS = {"cannot_start": "无法启动", "hard_to_understand": "内容难以理解",
          "hard_to_find": "功能不易找到", "unexpected_behavior": "行为与预期不符",
          "suggestion": "改进建议"}
AUTO_EVENTS = {"no_experience": "尚无当前工作区的体验记录", "experience_active": "存在未收尾的体验记录",
               "recap_goal_finished": "记录以目标阶段结束收尾（不证明题目完成）", "recap_handoff": "记录以交接收尾",
               "recap_stopped": "记录以停止收尾", "recap_failed": "记录以失败原因收尾（不判断故障根因）",
               "recap_manual": "记录由手动收尾", "recap_recovered": "记录以恢复后收尾", "unknown": "记录状态未知"}
MODES = {"off", "review", "limited_auto"}
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
ACCOUNT = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}\Z")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _repository(value):
    if not isinstance(value, str) or not REPO.fullmatch(value) or any(x in {".", ".."} for x in value.split("/")):
        raise ValueError("目标必须是明确的 GitHub owner/repository，不接受网址或命令选项")
    return value


def _text(value, name, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"{name} 必须是长度不超过 {limit} 的文本")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"{name} 含无效控制字符")
    return value.strip()


def redact(text):
    """Deterministic conservative masking; a human must review semantic privacy."""
    text = _text(text, "反馈文本", 16000, empty=True)
    patterns = [
        (r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9_-]{8,})", "[已隐藏凭据]"),
        (r'''(?i)["']?\b(?:authorization|proxy-authorization)["']?\s*[:=]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;]+)''', "[已隐藏认证字段]"),
        (r'''(?i)["']?\b(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)''', "[已隐藏凭据字段]"),
        (r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]{8,}=*", "[已隐藏认证凭据]"),
        (r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", "[已隐藏邮箱]"),
        (r"(?i)\b[A-Z]:[\\/][^\s<>\"'，。；]+", "[已隐藏本机路径]"),
        (r"\\\\[^\s<>\"'，。；]+", "[已隐藏网络路径]"),
        (r"(?<![:\w])/(?:Users|home|tmp|var|mnt|private|workspace|root)/[^\s<>\"'，。；]+", "[已隐藏本机路径]"),
        (r"(?i)\bhttps?://[^\s<>\"']+", "[已隐藏链接]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def program_facts():
    """Re-observe only allowlisted facts; no hostname, path, log, data or metric."""
    version = "unknown"
    metadata = Path(__file__).resolve().parents[1] / "RELEASE_METADATA.json"
    if metadata.is_file():
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
            candidate = data.get("version", data.get("product_version", "unknown"))
            if isinstance(candidate, str) and re.fullmatch(r"v?[0-9][A-Za-z0-9.+_-]{0,49}", candidate):
                version = candidate
        except (OSError, ValueError, AttributeError):
            pass
    system = platform.system()
    return {"product_version": version, "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": system if system in {"Windows", "Linux", "Darwin"} else "other", "format_version": 1}


REPRO_FIELDS = {"goal": "原本想做什么", "expected": "预期发生什么", "actual": "实际发生什么",
                "recovery": "尝试过的处理", "outcome": "目前是否解决"}
REPRO_SOURCES = {"user_report": "用户报告（未独立复核）", "agent_summary": "AI 整理（不是用户逐字原话）"}


def reproduction_example():
    return {"goal": {"text": "重新运行修改参数后的模型。", "source": "user_report"},
            "steps": [{"text": "修改参数后尝试准备运行输入。", "source": "agent_summary"}],
            "expected": {"text": "知道需要使用哪些当前版本。", "source": "user_report"},
            "actual": {"text": "不清楚代码和验证计划是否仍可使用。", "source": "user_report"},
            "missing_context": ["示例未提供实际报错和执行记录；不能据此复现。"]}


def validate_reproduction(value):
    """Optional, bounded context; provenance is declared, not authenticated."""
    allowed = set(REPRO_FIELDS) | {"steps", "missing_context"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("reproduction 仅接受 goal/steps/expected/actual/recovery/outcome/missing_context")

    def item(entry):
        if (not isinstance(entry, dict) or set(entry) != {"text", "source"}
                or not isinstance(entry["source"], str) or entry["source"] not in REPRO_SOURCES):
            raise ValueError("复现片段必须包含 text 和 source；source 为 user_report / agent_summary")
        return {"text": _text(entry["text"], "复现片段", 1500), "source": entry["source"]}

    result = {key: item(value[key]) for key in REPRO_FIELDS if key in value}
    if "steps" in value:
        if not isinstance(value["steps"], list) or len(value["steps"]) > 8:
            raise ValueError("复现步骤必须是至多 8 项的数组")
        result["steps"] = [item(entry) for entry in value["steps"]]
    if "missing_context" in value:
        if not isinstance(value["missing_context"], list) or len(value["missing_context"]) > 5:
            raise ValueError("上下文缺口必须是至多 5 项的数组")
        result["missing_context"] = [_text(entry, "上下文缺口", 500) for entry in value["missing_context"]]
    texts = [entry["text"] for key, entry in result.items() if key in REPRO_FIELDS]
    texts += [entry["text"] for entry in result.get("steps", [])] + result.get("missing_context", [])
    if sum(map(len, texts)) > 8000:
        raise ValueError("复现上下文文本总量不得超过 8000 字符；保留与问题有关的最小片段")
    return result


def reproduction_lines(value):
    context = validate_reproduction(value)
    lines = ["", "## 问题经过与复现线索", "以下为填报者整理的部分上下文，来源标签不代表独立复核；字段齐全也不等于已成功复现。"]
    missing = []
    for key, label in REPRO_FIELDS.items():
        if key == "expected":
            lines += ["", "### 操作步骤"]
            steps = context.get("steps", [])
            for number, step in enumerate(steps, 1):
                lines += [f"{number}. [{REPRO_SOURCES[step['source']]}] {redact(step['text'])}"]
            if not steps:
                missing.append("操作步骤")
                lines.append("未提供。")
        entry = context.get(key)
        lines += ["", "### " + label]
        if entry:
            lines += [REPRO_SOURCES[entry["source"]], redact(entry["text"])]
        else:
            missing.append(label)
            lines.append("未提供。")
    lines += ["", "### 上下文缺口", "未填写的内容：" + ("、".join(missing) if missing else "上述字段均已填写，真实性和复现仍需排查。")]
    lines += ["- " + redact(gap) for gap in context.get("missing_context", [])]
    lines.append("仅使用明确提供或选定的片段；没有读取完整会话。")
    return lines


class TransportError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class GitHubTransport:
    """Real gh only; no shell and no pretend-success production switch."""
    def _run(self, *arguments):
        executable = shutil.which("gh")
        if not executable:
            raise TransportError("gh_missing", "未找到 GitHub CLI；反馈仍保存在本机")
        env = dict(os.environ)
        env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_PAGER="cat")
        try:
            result = subprocess.run([executable, *arguments], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=45, env=env, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise TransportError("timeout", "GitHub 请求超时；发送结果需回读核对") from exc
        except OSError as exc:
            raise TransportError("gh_unavailable", "GitHub CLI 无法运行；保留本机记录") from exc
        if result.returncode:
            raise TransportError("gh_request_failed", f"GitHub CLI 请求失败（退出码 {result.returncode}）：{redact(result.stderr[:500])}")
        if len(result.stdout) > 4 * 1024 * 1024:
            raise TransportError("response_too_large", "GitHub 返回过大，尚未核验发送结果")
        return result.stdout.strip()

    def _api(self, endpoint, *extra):
        try:
            return json.loads(self._run("api", "--hostname", "github.com", "--method", "GET", endpoint, *extra))
        except (json.JSONDecodeError, TypeError) as exc:
            raise TransportError("invalid_response", "GitHub 返回格式无法核验") from exc

    def inspect(self, repository):
        repository = _repository(repository)
        user = self._api("user")
        repo = self._api("repos/" + repository)
        if (not isinstance(user, dict) or not isinstance(repo, dict) or not isinstance(user.get("login"), str)
                or not ACCOUNT.fullmatch(user["login"]) or type(repo.get("private")) is not bool
                or not isinstance(repo.get("full_name"), str) or repo["full_name"].casefold() != repository.casefold()):
            raise TransportError("identity_unverified", "无法核验目标仓库、当前账号或可见性")
        return {"repository": _repository(repo["full_name"]), "account": user["login"],
                "visibility": "private" if repo["private"] else "public"}

    def create(self, payload, body_file):
        output = self._run("issue", "create", "--repo", "github.com/" + payload["repository"],
                           "--title", payload["title"], "--body-file", str(body_file))
        match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/issues/([1-9][0-9]*)", output)
        if not match or match[1].casefold() != payload["repository"].casefold():
            raise TransportError("creation_unknown", "GitHub 未返回可核验的 Issue 地址；先回读，不重复发送")
        return output

    def read_issue(self, repository, url):
        match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/issues/([1-9][0-9]*)", url or "")
        if not match or match[1].casefold() != repository.casefold():
            raise TransportError("invalid_receipt", "Issue 回执不属于批准的仓库")
        return self._api(f"repos/{repository}/issues/{match[2]}")

    def find(self, payload, marker):
        pages = self._api(f"repos/{payload['repository']}/issues?state=all&per_page=100", "--paginate", "--slurp")
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise TransportError("invalid_response", "Issue 回读列表格式无效")
        return [issue for page in pages for issue in page if isinstance(issue, dict)
                and marker in str(issue.get("body", "")) and "pull_request" not in issue]


def _authorization(request, action, scope):
    expected = {"source", "actor_type", "request_id", "text", "action", "scope"}
    if (not isinstance(request, dict) or set(request) != expected or request.get("source") != "direct_user"
            or request.get("actor_type") != "human" or request.get("action") != action
            or _digest(request.get("scope")) != _digest(scope)):
        raise ValueError("需要用户直接表达的明确授权记录，且 action/scope 必须与本次内容一致；不能从 AI 报告推断批准")
    _text(request["request_id"], "授权来源编号", 200)
    _text(request["text"], "用户原话", 6000)
    return copy.deepcopy(request)


class UsageFeedback:
    def __init__(self, workspace=None, user_data=None, *, transport=None):
        self.storage = ExperienceStorage(workspace, user_data=user_data)
        self.transport = transport if transport is not None else GitHubTransport()
        self.settings_id = "settings-" + self.storage.binding[:24]

    def _lock(self):
        self.storage.prepare_write()
        return file_lock(self.storage.path("locks", "feedback-" + self.storage.binding[:24] + ".lock"))

    def _save(self, record):
        saved = copy.deepcopy(record)
        saved["updated_at"] = utc_now()
        return self.storage.write("feedback", saved["id"], saved, expected_revision=record.get("record_revision"))

    def _event(self, record, event, error=None, detail=None):
        item = {"event": event, "at": utc_now()}
        if error:
            item["error"] = {"code": getattr(error, "code", "local_error"), "message": redact(str(error)[:1000])}
        if detail is not None:
            item["detail"] = copy.deepcopy(detail)
        record["audit"].append(item)

    def _get(self, identity):
        record = self.storage.read("feedback", identity)
        if not record or record.get("type") != "usage_feedback":
            raise ValueError("未找到当前工作区的使用反馈")
        return record

    def settings(self):
        record = self.storage.read("feedback", self.settings_id)
        if record is None:
            return {"id": self.settings_id, "type": "usage_feedback_settings", "mode": "off", "repository": None,
                    "target": None, "allowed_events": [], "max_submissions": 0, "automatic_count": 0,
                    "automatic_sources": {}, "audit": [], "record_revision": 0}
        if (record.get("type") != "usage_feedback_settings" or record.get("mode") not in MODES
                or not isinstance(record.get("allowed_events"), list) or not set(record["allowed_events"]) <= AUTO_EVENTS.keys()
                or type(record.get("automatic_count")) is not int or type(record.get("max_submissions")) is not int
                or not isinstance(record.get("automatic_sources", {}), dict)
                or not 0 <= record["automatic_count"] <= record["max_submissions"] <= 20):
            raise ValueError("使用反馈设置格式无效；不能默认为关闭或覆盖")
        return record

    def configure(self, mode, repository, allowed_events, max_submissions, user_request, settings_revision):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError("使用反馈模式必须为 off/review/limited_auto")
        if repository is not None:
            repository = _repository(repository)
        if (not isinstance(allowed_events, list) or any(not isinstance(x, str) or x not in AUTO_EVENTS for x in allowed_events)
                or len(set(allowed_events)) != len(allowed_events) or type(max_submissions) is not int):
            raise ValueError("有限自动反馈的事件范围或次数无效")
        if mode == "limited_auto" and (not repository or not allowed_events or not 1 <= max_submissions <= 20):
            raise ValueError("有限自动反馈需要明确仓库、允许事件及 1–20 次总上限")
        if mode != "limited_auto" and (allowed_events or max_submissions):
            raise ValueError("只有 limited_auto 可以设置自动反馈事件和次数")
        with self._lock():
            previous = self.settings()
            if type(settings_revision) is not int or previous["record_revision"] != settings_revision:
                raise ValueError("使用反馈设置版本已变化；请重新读取")
            target = self.transport.inspect(repository) if mode == "limited_auto" else None
            scope = {"binding": self.storage.binding, "mode": mode, "repository": repository,
                     "target": target, "allowed_events": sorted(allowed_events), "max_submissions": max_submissions}
            request = _authorization(user_request, "configure_usage_feedback", scope)
            record = dict(previous, **{key: value for key, value in scope.items() if key != "binding"},
                          automatic_count=0, authorization=request)
            if not previous["record_revision"]:
                record.pop("record_revision")
            self._event(record, "configured", detail={"request": request, "scope": scope})
            return self._save(record)

    def revoke(self, user_request, settings_revision):
        request = _authorization(user_request, "revoke_usage_feedback", {"binding": self.storage.binding})
        with self._lock():
            previous = self.settings()
            if type(settings_revision) is not int or previous["record_revision"] != settings_revision:
                raise ValueError("使用反馈设置版本已变化；请重新读取")
            record = dict(previous, mode="off", allowed_events=[], max_submissions=0, automatic_count=0,
                          target=None, repository=None, authorization=request)
            if not previous["record_revision"]:
                record.pop("record_revision")
            self._event(record, "revoked", detail={"request": request})
            return self._save(record)

    @staticmethod
    def _draft_payload(payload):
        if not isinstance(payload, dict) or set(payload) - {"title", "description", "component", "event", "reproduction"}:
            raise ValueError("草稿仅接受 title/description/component/event/reproduction；不接收整份日志、文件或状态报告")
        if (not isinstance(payload.get("component"), str) or payload["component"] not in COMPONENTS
                or not isinstance(payload.get("event"), str) or payload["event"] not in EVENTS):
            raise ValueError("请选择已列出的反馈组件与事件类型")
        draft = {"title": _text(payload.get("title", ""), "标题", 200, empty=True),
                "description": _text(payload.get("description", ""), "说明", 12000, empty=True),
                "component": payload["component"], "event": payload["event"]}
        if "reproduction" in payload:
            draft["reproduction"] = validate_reproduction(payload["reproduction"])
        return draft

    def _experience(self, identity):
        record = self.storage.read("experiences", identity)
        if not record or record.get("kind") != "experience":
            raise ValueError("来源体验必须是当前工作区已经保存的真实记录")
        return record

    def _event_selection(self, experience_id, event_ids):
        if (not isinstance(event_ids, list) or len(event_ids) > 5
                or any(not isinstance(value, str) or not value for value in event_ids)
                or len(set(event_ids)) != len(event_ids)):
            raise ValueError("每份反馈只能明确选取不重复的至多 5 个已保存过程片段")
        if event_ids and not experience_id:
            raise ValueError("选择过程片段前必须绑定当前工作区的来源体验")
        if experience_id:
            experience = self._experience(experience_id)
            known = {event.get("event_id") for event in experience.get("events", []) if isinstance(event, dict)}
            if not set(event_ids) <= known:
                raise ValueError("选择的过程片段不属于绑定体验")
        return list(event_ids)

    def draft(self, payload, request_id=None, experience_id=None, event_ids=None):
        draft = self._draft_payload(payload)
        if request_id is not None:
            _text(request_id, "反馈请求编号", 120)
        selected = self._event_selection(experience_id, event_ids or [])
        identity = ("feedback-" + _digest([self.storage.binding, "experience", experience_id])[:32] if experience_id else
                    "feedback-" + _digest([self.storage.binding, "request", request_id])[:32] if request_id else
                    "feedback-" + uuid.uuid4().hex)
        record = {"id": identity, "type": "usage_feedback", "created_at": utc_now(),
                  "status": "draft", "draft": draft, "preview": None, "approval": None,
                  "attempt": None, "receipt": None, "audit": [], "request_id": request_id,
                  "request_ids": [request_id] if request_id is not None else [],
                  "experience_id": experience_id, "event_ids": selected}
        with self._lock():
            if request_id is not None:
                existing = next((item for item in self.list() if request_id in item.get("request_ids", [item.get("request_id")])), None)
                if existing:
                    if (existing.get("draft") != draft or existing.get("experience_id") != experience_id
                            or existing.get("event_ids", []) != selected):
                        raise ValueError("同一反馈 request_id 已用于不同内容或来源；未新建或覆盖")
                    return existing
            previous = self.storage.read("feedback", identity)
            if previous:
                if (previous.get("type") != "usage_feedback" or previous.get("draft") != draft
                        or previous.get("experience_id") != experience_id or previous.get("event_ids", []) != selected):
                    raise ValueError("同一反馈请求或体验已有不同内容；请读取并编辑原反馈，不重复新建")
                if request_id is not None:
                    aliases = previous.setdefault("request_ids", [previous["request_id"]] if previous.get("request_id") else [])
                    if len(aliases) >= 100:
                        raise ValueError("同一反馈的重试来源过多；请读取原反馈记录")
                    aliases.append(request_id)
                    self._event(previous, "request_reused_existing_experience")
                    return self._save(previous)
                return previous
            self._event(record, "draft_created")
            return self._save(record)

    def edit(self, identity, payload, record_revision, event_ids=None):
        draft = self._draft_payload(payload)
        with self._lock():
            record = self._get(identity)
            self._editable(record, record_revision)
            record.update(draft=draft, status="draft", preview=None, approval=None)
            if event_ids is not None:
                record["event_ids"] = self._event_selection(record.get("experience_id"), event_ids)
            self._event(record, "edited_approval_invalidated")
            return self._save(record)

    @staticmethod
    def _editable(record, revision):
        if type(revision) is not int or record["record_revision"] != revision:
            raise ValueError("反馈版本已变化；请重新读取")
        if record["status"] in {"sending", "unknown", "sent"}:
            raise ValueError("已经尝试发送的反馈不可重写；未知结果必须先回读核对")

    def _automatic_observation(self, record):
        records = [item for item in self.storage.list("experiences") if item.get("kind") == "experience"]
        event, coverage = "no_experience", "unknown"
        closed = [item for item in records if item.get("state") == "closed" and isinstance(item.get("recaps"), list)
                  and item["recaps"] and isinstance(item["recaps"][-1], dict)]
        selected = self._experience(record["experience_id"]) if record.get("experience_id") else max(
            records, key=lambda item: str(item["recaps"][-1].get("created_at", ""))
            if isinstance(item.get("recaps"), list) and item["recaps"] and isinstance(item["recaps"][-1], dict)
            else str(item.get("created_at", "")), default=None)
        if selected and selected.get("state") == "active":
            event = "experience_active"
        elif selected in closed:
            last = selected["recaps"][-1]
            proposed = "recap_" + str(last.get("reason", ""))
            event = proposed if proposed in AUTO_EVENTS else "unknown"
            coverage = "partial" if last.get("context_coverage") == "partial" else "unknown"
        elif records:
            event = "unknown"
        return {"experience_present": bool(records), "has_closed_record": bool(closed),
                "lifecycle_event": event, "context_coverage": coverage,
                "_source_key": _digest([self.storage.binding, selected["id"] if selected else "no-experience"])}

    def _selected_evidence(self, record):
        selected = record.get("event_ids", [])
        if not selected:
            return ["", "## 过程来源与覆盖", "没有选定已保存的过程片段；本反馈不声称覆盖完整会话。"]
        experience = self._experience(record["experience_id"])
        self._event_selection(record["experience_id"], selected)
        entries = {event["event_id"]: event for event in experience.get("events", [])}
        labels = {"artifact_excerpt": "登记时核对的逐字文件片段（此处未重新核验原文件）",
                  "user_report": "用户报告（来源身份未认证）", "agent_summary": "AI 转述（不能当作人的原话）"}
        lines = ["", "## 明确选定的过程片段", "仅覆盖以下保存片段，缺少其余对话与上下文；不代表完整会话。"]
        for number, event_id in enumerate(selected, 1):
            event = entries[event_id]
            source = event.get("source", {})
            kind = source.get("kind") if isinstance(source, dict) else None
            if kind not in labels:
                raise ValueError("所选片段来源类型无法核对；不能伪装为原话")
            scope = _text(source.get("scope", ""), "片段来源范围", 1000, empty=True)
            lines += ["", f"片段 {number} · {labels[kind]}", "记录的来源范围：" + (redact(scope) or "未填写"), redact(event["text"])]
        return lines

    def _build(self, record, target, mode, automatic=None):
        draft = record["draft"]
        facts = program_facts()
        if mode == "limited_auto":
            automatic = automatic if automatic is not None else self._automatic_observation(record)
            facts.update({key: value for key, value in automatic.items() if not key.startswith("_")})
            title = "使用反馈：程序环境与体验记录概况"
            lines = ["## 有限自动使用反馈", "", "只发送白名单程序观察，不含草稿分类或自由文本。",
                     "体验记录：" + ("存在" if automatic["experience_present"] else "不存在"),
                     "已收尾记录：" + ("存在" if automatic["has_closed_record"] else "不存在"),
                     "记录状态：" + AUTO_EVENTS[automatic["lifecycle_event"]],
                     "过程覆盖：" + ("部分片段" if automatic["context_coverage"] == "partial" else "未知")]
        else:
            title = f"使用反馈：{COMPONENTS[draft['component']]} · {EVENTS[draft['event']]}"
            lines = ["## 使用反馈", "", f"组件：{COMPONENTS[draft['component']]}",
                     f"类型（填报分类，非程序故障判定）：{EVENTS[draft['event']]}"]
        lines += ["",
                 "## 程序直接观测的基本环境", f"产品版本：{facts['product_version']}",
                 f"Python：{facts['python_version']}", f"操作系统类别：{facts['platform']}"]
        if mode == "review":
            title = redact(draft["title"]) or title
            lines += ["", "## 反馈说明（需审阅）", redact(draft["description"]) or "未补充说明。"]
            if "reproduction" in draft:
                lines += reproduction_lines(draft["reproduction"])
            lines += self._selected_evidence(record)
        marker = "<!-- mathmodel-copilot-feedback:" + record["id"] + " -->"
        lines += ["", "本通道不自动读取题目、论文或运行结果；正文需检查，不构成建模结论核验。", "", marker]
        payload = {"title": title, "body": "\n".join(lines), **target}
        return {"payload": payload, "payload_sha256": _digest(payload), "mode": mode,
                "marker": marker, "observed_at": utc_now(), "program_facts": facts,
                "notice": "脱敏规则不能理解全部语义隐私；review 需检查将发送的完整内容。填报分类不是程序检测事实，也不证明用户亲自选择。"}

    def preview(self, identity, repository=None):
        with self._lock():
            record = self._get(identity)
            self._editable(record, record["record_revision"])
            settings = self.settings()
            repository = repository or settings["repository"]
            record.update(approval=None, status="draft")
            local = {"title": redact(record["draft"]["title"]), "description": redact(record["draft"]["description"])}
            local["body"] = self._build(record, {}, "review")["payload"]["body"]
            record["local_preview"] = local
            if not repository:
                record["preview"] = None
                self._event(record, "preview_needs_repository")
                return self._save(record)
            try:
                target = self.transport.inspect(_repository(repository))
            except TransportError as exc:
                record["preview"] = None
                self._event(record, "preview_unavailable", exc)
                return self._save(record)
            mode = "limited_auto" if settings["mode"] == "limited_auto" else "review"
            record.update(preview=self._build(record, target, mode), status="preview")
            self._event(record, "previewed")
            return self._save(record)

    def approve(self, identity, preview_hash, user_request, record_revision):
        with self._lock():
            record = self._get(identity)
            self._editable(record, record_revision)
            settings = self.settings()
            preview = record.get("preview")
            if settings["mode"] != "review" or not preview or preview["mode"] != "review":
                raise ValueError("先启用 review 并取得完整预览；当前没有可批准的内容")
            if preview["payload_sha256"] != preview_hash or _digest(preview["payload"]) != preview_hash:
                raise ValueError("批准哈希与当前精确预览不一致")
            target = {key: preview["payload"][key] for key in ("repository", "account", "visibility")}
            if self.transport.inspect(target["repository"]) != target:
                raise ValueError("目标账号或仓库可见性已变化；请重新预览")
            scope = {"binding": self.storage.binding, "feedback_id": identity, "payload_sha256": preview_hash, **target}
            record["approval"] = {"request": _authorization(user_request, "send_usage_feedback", scope),
                                  "payload_sha256": preview_hash, "settings_revision": settings["record_revision"], "at": utc_now()}
            record["status"] = "approved"
            self._event(record, "approved_exact_payload", detail={"approval": record["approval"], "payload": preview["payload"]})
            return self._save(record)

    @staticmethod
    def _verified_receipt(issue, payload):
        if (not isinstance(issue, dict) or issue.get("title") != payload["title"] or issue.get("body") != payload["body"]
                or not isinstance(issue.get("user"), dict) or issue["user"].get("login") != payload["account"]):
            raise TransportError("receipt_mismatch", "远端 Issue 的内容或作者与批准内容不一致")
        url = issue.get("html_url", "")
        match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/issues/([1-9][0-9]*)", url)
        if not match or match[1].casefold() != payload["repository"].casefold():
            raise TransportError("receipt_mismatch", "远端回执不属于指定仓库")
        return {"url": url, "number": int(match[2]), "account": payload["account"], "repository": payload["repository"],
                "visibility_at_send": payload["visibility"], "payload_sha256": _digest(payload), "verified_at": utc_now()}

    def _reconcile_locked(self, record):
        if record["status"] == "sent":
            return record
        if record["status"] not in {"sending", "unknown"} or not record.get("attempt"):
            raise ValueError("此反馈没有待核对的发送尝试")
        payload = record["attempt"]["payload"]
        try:
            matches = self.transport.find(payload, record["attempt"]["marker"])
            if len(matches) != 1:
                raise TransportError("unknown_remote_result", "未找到唯一匹配回执；暂不重复发送，请核对 GitHub")
            record["receipt"] = self._verified_receipt(matches[0], payload)
            record["status"] = "sent"
            self._event(record, "reconciled_sent")
        except TransportError as exc:
            record["status"] = "unknown"
            self._event(record, "reconcile_unknown", exc)
        return self._save(record)

    def reconcile(self, identity):
        with self._lock():
            return self._reconcile_locked(self._get(identity))

    def send(self, identity):
        with self._lock():
            record = self._get(identity)
            if record["status"] in {"sending", "unknown", "sent"}:
                return self._reconcile_locked(record)
            settings = self.settings()
            if settings["mode"] == "off":
                raise ValueError("使用反馈发送已关闭；草稿仍保存在本机")
            try:
                if settings["mode"] == "limited_auto":
                    automatic = self._automatic_observation(record)
                    if (automatic["lifecycle_event"] not in settings["allowed_events"]
                            or settings["automatic_count"] >= settings["max_submissions"]):
                        raise ValueError("反馈不在有限自动授权的事件/次数范围内")
                    if automatic["_source_key"] in settings.get("automatic_sources", {}):
                        raise ValueError("本体验已经预留或发送过自动反馈；更换草稿不能绕过每次体验最多一份的限制")
                    target = self.transport.inspect(settings["repository"])
                    if target != settings["target"]:
                        raise ValueError("有限自动反馈的账号、仓库或可见性已变化；需重新授权")
                    preview = self._build(record, target, "limited_auto", automatic)
                    authorization = {"kind": "limited_auto", "settings_revision": settings["record_revision"],
                                     "request": copy.deepcopy(settings["authorization"])}
                else:
                    preview, approval = record.get("preview"), record.get("approval")
                    if (not preview or not approval or preview["mode"] != "review" or record["status"] != "approved"
                            or approval["settings_revision"] != settings["record_revision"]
                            or approval["payload_sha256"] != preview["payload_sha256"]
                            or _digest(preview["payload"]) != approval["payload_sha256"]):
                        raise ValueError("缺少当前精确内容的用户批准；编辑、撤回或设置变化后需重新审阅")
                    target = {key: preview["payload"][key] for key in ("repository", "account", "visibility")}
                    if self.transport.inspect(target["repository"]) != target:
                        raise ValueError("账号或目标可见性已变化；发送前需重新预览和批准")
                    authorization = {"kind": "review", **copy.deepcopy(approval)}
            except TransportError as exc:
                self._event(record, "send_preflight_unavailable", exc)
                return self._save(record)
            payload = preview["payload"]
            directory = self.storage.path("outbox")
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, suffix=".md", delete=False) as handle:
                body_file = Path(handle.name)
                handle.write(payload["body"])
            try:
                if settings["mode"] == "limited_auto":
                    settings["automatic_count"] += 1
                    settings.setdefault("automatic_sources", {})[automatic["_source_key"]] = {
                        "feedback_id": record["id"], "reserved_at": utc_now()}
                    self._event(settings, "automatic_slot_reserved")
                    self._save(settings)
                record.update(status="sending", preview=preview,
                              attempt={"payload": payload, "marker": preview["marker"], "authorization": authorization,
                                       "started_at": utc_now(), "url": None})
                self._event(record, "send_started")
                record = self._save(record)
                try:
                    url = self.transport.create(payload, body_file)
                    record["attempt"]["url"] = url
                    record = self._save(record)
                    issue = self.transport.read_issue(payload["repository"], url)
                    record["receipt"] = self._verified_receipt(issue, payload)
                    record["status"] = "sent"
                    self._event(record, "remote_content_verified")
                except TransportError as exc:
                    record["status"] = "unknown"
                    self._event(record, "send_unknown", exc)
                return self._save(record)
            finally:
                body_file.unlink(missing_ok=True)

    def show(self, identity):
        return self._get(identity)

    def list(self):
        return [item for item in self.storage.list("feedback") if item.get("type") == "usage_feedback"]

    def export(self, identity, output):
        """Explicit local Markdown export; never inspects or contacts GitHub."""
        record = self._get(identity)
        path = Path(output)
        if not path.is_absolute():
            path = self.storage.workspace / path
        path = path.absolute()
        for part in path.parts[1:]:
            _safe_component(part)
        if path.suffix.lower() != ".md" or path.exists():
            raise ValueError("导出需要尚不存在的 Markdown 文件；不会覆盖已有文件")
        if any(part.casefold() in {"state", ".copilot", ".git"} for part in path.parts):
            raise ValueError("使用反馈不能导出到建模状态或运行内部目录")
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                raise ValueError("导出路径不能经过符号链接或目录联接")
        try:
            path.relative_to(self.storage.root)
        except ValueError:
            pass
        else:
            raise ValueError("导出必须另选普通文件，不能写入个人记录内部目录")
        preview = self._build(record, {"repository": None, "account": None, "visibility": "unconfigured"}, "review")
        note = ("原反馈已有核验回执；本文件是本机导出稿，未触发再次发送。" if record.get("receipt")
                else "尚未送达：这是本机草稿导出，不代表已提交 GitHub 或已被开发者接收。")
        markdown = ("# 使用反馈草稿\n\n" + note + "\n\n标题：" + preview["payload"]["title"] + "\n\n"
                    + preview["payload"]["body"].replace(preview["marker"], "").rstrip()
                    + "\n\n自动脱敏不能理解全部隐私；手动转发前请检查全文。\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(markdown)
        if path.read_text(encoding="utf-8") != markdown:
            raise ValueError("导出文件回读不一致；不能报告成功")
        return {"saved_to": str(path), "sent": False, "notice": note}


def parser():
    p = argparse.ArgumentParser(description="使用反馈：本机草稿、精确审阅和有范围的 GitHub 发送")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--user-data", type=Path)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("settings")
    for name in ("draft", "edit"):
        child = sub.add_parser(name)
        child.add_argument("--input", required=True)
        child.add_argument("--event-ids", nargs="*")
        if name == "draft":
            child.add_argument("--request-id")
            child.add_argument("--experience-id")
        if name == "edit":
            child.add_argument("--id", required=True)
            child.add_argument("--record-revision", type=int, required=True)
    for name in ("show", "preview", "send", "reconcile"):
        child = sub.add_parser(name)
        child.add_argument("--id", required=True)
        if name == "preview":
            child.add_argument("--repository")
    child = sub.add_parser("approve")
    child.add_argument("--id", required=True)
    child.add_argument("--preview-hash", required=True)
    child.add_argument("--authorization", required=True)
    child.add_argument("--record-revision", type=int, required=True)
    child = sub.add_parser("export")
    child.add_argument("--id", required=True)
    child.add_argument("--output", type=Path, required=True)
    for name in ("configure", "revoke"):
        child = sub.add_parser(name)
        child.add_argument("--authorization", required=True)
        child.add_argument("--settings-revision", type=int, required=True)
        if name == "configure":
            child.add_argument("--mode", choices=sorted(MODES), required=True)
            child.add_argument("--repository")
            child.add_argument("--allowed-events", nargs="*", choices=sorted(AUTO_EVENTS), default=[])
            child.add_argument("--max-submissions", type=int, default=0)
    return p


def _input(workspace, reference):
    from copilot_runtime import safe_path
    path = safe_path(workspace, reference)
    if path.stat().st_size > 128 * 1024:
        raise ValueError("反馈输入过大")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("反馈 JSON 不接受重复字段")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("不接受非有限数字")))


def execute(args):
    service = UsageFeedback(args.workspace, args.user_data)
    action = args.action
    if action in {"list", "settings"}:
        return getattr(service, action)()
    if action == "draft":
        return service.draft(_input(args.workspace, args.input), args.request_id, args.experience_id, args.event_ids)
    if action == "edit":
        return service.edit(args.id, _input(args.workspace, args.input), args.record_revision, args.event_ids)
    if action == "preview":
        return service.preview(args.id, args.repository)
    if action == "approve":
        return service.approve(args.id, args.preview_hash, _input(args.workspace, args.authorization), args.record_revision)
    if action == "configure":
        return service.configure(args.mode, args.repository, args.allowed_events, args.max_submissions,
                                 _input(args.workspace, args.authorization), args.settings_revision)
    if action == "revoke":
        return service.revoke(_input(args.workspace, args.authorization), args.settings_revision)
    if action == "export":
        return service.export(args.id, args.output)
    return getattr(service, action)(args.id)


if __name__ == "__main__":
    try:
        print(json.dumps(execute(parser().parse_args()), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
