#!/usr/bin/env python3
"""Optional, local Git transport; Store remains the only business authority.

No command in this module fetches, pushes, checks out, merges, runs a hook,
executes imported code, or sends a draft to GitHub. Git references are local
observations, not proof of a remote's current state.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from copilot_store import ConflictError, IntegrityError, digest, state_at_revision, utc_now

FORMAT = "mathmodel-git-proposal/0.2"
PROTECTED = ("state", ".copilot")
MAX_BLOB = 4 * 1024 * 1024


class GitError(ValueError):
    pass


def _protected(path):
    # Windows treats trailing dots/spaces as aliases. Reject them conservatively
    # on every host instead of letting Git spelling hide a protected directory.
    return path.replace("\\", "/").split("/", 1)[0].rstrip(" .").casefold() in PROTECTED


def _relative(path):
    """Git paths and public paths are data, never shell fragments."""
    if (not isinstance(path, str) or not path or path.startswith(("/", "-"))
            or "\\" in path or ":" in path or any(ord(c) < 32 for c in path)
            or any(p.casefold() in {"", ".", "..", ".git"} or p.endswith((" ", ".")) for p in path.split("/"))):
        raise GitError("需要规范的项目内相对路径")
    return path


def _reference(value):
    if (not isinstance(value, str) or len(value) > 240
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value)
            or ".." in value or "//" in value or value.endswith(("/", ".", ".lock"))):
        raise GitError("比较对象必须是本地 ref 名或 commit ID；不接受命令选项或 revision 表达式")
    return value


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _safe_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
               GIT_PAGER="", LC_ALL="C")
    return env


class LocalGit:
    """Bounded subprocess argv, no shell and no remote operations."""
    def __init__(self, workspace, *, executable=None):
        self.workspace = Path(workspace).resolve()
        self.executable = executable if executable is not None else shutil.which("git")
        self.root = None
        self.git_dir = None
        self.prefix = ""
        self.filters = []
        if not self.executable:
            return
        # Read config as data and disable all named filters before status/diff.
        # --get-regexp also sees included config; no returned values are exposed.
        configured = self._run("config", "--null", "--get-regexp", r"^filter\..*\.(clean|smudge|process|required)$", ok=(0, 1), bootstrap=True)
        for entry in configured.split(b"\0"):
            if entry:
                key = entry.split(b"\n", 1)[0].decode("utf-8", "replace")
                if re.fullmatch(r"filter\.[^\r\n=]+\.(clean|smudge|process|required)", key):
                    self.filters += ["-c", key + ("=false" if key.endswith(".required") else "=")]
                else:
                    raise GitError("不支持异常 Git filter 配置名；未执行此工作树的状态命令")
        raw = self._run("rev-parse", "--show-toplevel", ok=(0, 128))
        if not raw:
            return
        self.root = Path(raw.decode("utf-8").strip()).resolve()
        try:
            prefix = self.workspace.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise GitError("Git 工作树不包含此项目") from exc
        self.prefix = "" if prefix == "." else prefix + "/"
        if self.prefix:
            _relative(self.prefix[:-1])
        self.git_dir = Path(self._run("rev-parse", "--absolute-git-dir").decode("utf-8").strip()).resolve()

    def _run(self, *args, ok=(0,), bootstrap=False):
        if not self.executable:
            raise GitError("Git 未安装；Local 模式仍可使用")
        options = ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                   "-c", "core.hooksPath=" + os.devnull, "-c", "core.attributesFile=" + os.devnull,
                   "-c", "credential.helper=", "-c", "diff.external=", "-c", "diff.relative=false", "-c", "core.pager="]
        if not bootstrap:
            options += self.filters
        try:
            result = subprocess.run([str(self.executable), "--no-pager", "--no-optional-locks", *options,
                                     "-C", str(self.workspace), *args], env=_safe_env(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=15, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError("Git 本地读取不可用或超时；未执行网络操作") from exc
        if result.returncode not in ok:
            # Raw stderr may contain credentials, private remote paths or config.
            raise GitError(f"Git {args[0]} 本地读取失败 (exit {result.returncode})；未回显原始配置或凭据")
        if result.returncode:
            return b""
        if len(result.stdout) > 16 * MAX_BLOB:
            raise GitError("Git 结果超出本地读取上限")
        return result.stdout

    def names(self, *args):
        return [x.decode("utf-8", "strict") for x in self._run(*args).split(b"\0") if x]

    def in_project(self, name):
        # Conservatively catch case aliases on Windows and case-sensitive hosts.
        if name.casefold().startswith(self.prefix.casefold()):
            return name[len(self.prefix):]
        return None

    def tracked_protected(self):
        return sorted({p for name in self.names("ls-files", "--full-name", "-z")
                       if (p := self.in_project(name)) and _protected(p)})

    def submodules(self):
        result = []
        for entry in self.names("ls-files", "--stage", "--full-name", "-z"):
            header, name = entry.split("\t", 1)
            local = self.in_project(name)
            if header.split()[0] == "160000" and local:
                result.append(local)
        return sorted(set(result))

    def commit(self, ref="HEAD"):
        _reference(ref)
        raw = self._run("rev-parse", "--verify", "--end-of-options", ref + "^{commit}", ok=(0, 128))
        result = raw.decode("ascii").strip()
        return result if re.fullmatch(r"[a-f0-9]{40,64}", result) else None

    def blob(self, commit, path):
        spec = commit + ":" + self.prefix + _relative(path)
        # cat-file is raw object access: no smudge, textconv or external diff.
        size = self._run("cat-file", "-s", spec, ok=(0, 128))
        if not size:
            return None
        if int(size) > MAX_BLOB:
            raise GitError("文件大于 4 MiB；请单独审查，不能省略后声称无影响")
        return self._run("cat-file", "blob", spec)


def _marker(git):
    identity = git.prefix.casefold() if os.name == "nt" else git.prefix
    # Short filename keeps ordinary Windows workspaces below MAX_PATH. Full
    # project_prefix is checked in the policy; any ID collision fails closed.
    return git.git_dir / "copilot-protect" / (_sha(identity.encode())[:24] + ".json")


def _policy(git):
    return {"format": "mathmodel-git-protection/0.2",
            "project_prefix": git.prefix.casefold() if os.name == "nt" else git.prefix}


def _marker_without_git(workspace):
    root = Path(workspace).resolve()
    for parent in (root, *root.parents):
        entry = parent / ".git"
        if entry.is_dir():
            git_dir = entry.resolve()
        elif entry.is_file():
            line = entry.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir: "):
                return None
            git_dir = (parent / line[8:]).resolve()
        else:
            continue
        prefix = root.relative_to(parent).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        identity = prefix.casefold() if os.name == "nt" else prefix
        return git_dir / "copilot-protect" / (_sha(identity.encode())[:24] + ".json")
    return None


def assert_authority_boundary(workspace):
    """Store.read hook. A marker is local policy, never a state authority copy.

    Unenabled projects need neither Git nor a subprocess. Enabled projects fail
    closed if protected files enter the index, even with internally valid JSON.
    This is not identity authentication against arbitrary filesystem writers.
    """
    marker = _marker_without_git(workspace)
    if marker is None or not marker.is_file():
        return
    try:
        policy = json.loads(marker.read_text(encoding="utf-8"))
        git = LocalGit(workspace)
        if not git.root or _marker(git) != marker or policy != _policy(git):
            raise GitError("本地 Git 保护标记无效或 Git 不可用")
        tracked = git.tracked_protected()
        if tracked:
            raise GitError("Git 正在跟踪权威/运行历史文件；必须恢复集成端的可信副本并移出 Git 跟踪，不能把 merge 当权威事务: " + ", ".join(tracked[:10]))
    except (ValueError, OSError, UnicodeError) as exc:
        raise IntegrityError("Git 权威边界拒绝: " + str(exc)) from exc


def protect(workspace):
    """Explicit opt-in; only local .git metadata, never changes tracked files."""
    git = LocalGit(workspace)
    if not git.root:
        raise GitError("protect 需要现有本地工作树；不会自动建仓库")
    if git.tracked_protected():
        raise IntegrityError("权威 state/ 与 .copilot/ 已被跟踪；拒绝启用，不自动移除或覆盖它们")
    from copilot_runtime import Runtime
    Runtime(workspace).read()
    marker = _marker(git)
    policy = _policy(git)
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != policy:
        raise IntegrityError("已有不同的本地保护策略；不覆盖")
    # For worktrees --git-path locates common info/exclude correctly.
    exclude = Path(git._run("rev-parse", "--path-format=absolute", "--git-path", "info/exclude").decode().strip())
    attributes = Path(git._run("rev-parse", "--path-format=absolute", "--git-path", "info/attributes").decode().strip())
    literal = re.sub(r"([*?\[\]#!])", r"\\\1", git.prefix)
    patterns = ["/" + literal + folder + "/**" for folder in PROTECTED]
    for path, lines in ((exclude, patterns), (attributes, [json.dumps(x[1:], ensure_ascii=False) + " -merge" for x in patterns])):
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [x for x in lines if x not in old.splitlines()]
        if missing:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(("\n" if old and not old.endswith("\n") else "") + "# MathModel Copilot local authority protection\n" + "\n".join(missing) + "\n")
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open("x", encoding="utf-8") as handle:
            json.dump(policy, handle, ensure_ascii=False, indent=2)
    assert_authority_boundary(workspace)
    return {"enabled": True, "tracked_files_changed": False, "global_config_changed": False,
            "protected": ["state/**", ".copilot/**"], "policy": "authority and sealed histories stay outside Git"}


def _remote_summary(git):
    records = []
    # Remote names alone are sufficient; URLs are deliberately never returned.
    for name in git._run("remote").decode("utf-8").splitlines():
        records.append({"name": name, "network_observation": "not_executed",
                        "url": "redacted", "authorization": "not_established"})
    return records


def repository_status(workspace, compare=None, *, executable=None):
    report = {"mode": "local", "git_available": False, "is_repository": False,
              "remote_live_state": "unknown_not_fetched", "network_actions": [],
              "observed_at": utc_now(), "comparison": {"status": "unknown", "reason": "未指定本地比较对象"}}
    git = LocalGit(workspace, executable=executable)
    report["git_available"] = bool(git.executable)
    if not git.root:
        report["reason"] = "此目录不是 Git 工作树" if git.executable else "Git 未安装；本地核心功能可继续"
        return report
    report.update(is_repository=True, repository_root=str(git.root), project_prefix=git.prefix)
    commit = git.commit()
    branch = git._run("symbolic-ref", "--quiet", "--short", "HEAD", ok=(0, 1)).decode().strip() or None
    report.update(branch=branch, commit=commit, detached=branch is None and commit is not None, unborn=commit is None)
    # Git status otherwise recurses into submodules, whose *own* filter config
    # is outside the root's filter neutralization. Do not run child Git there.
    raw = git._run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all").split(b"\0")
    paths, index = [], 0
    while index < len(raw):
        entry = raw[index]
        index += 1
        if not entry:
            continue
        code, name = entry[:2].decode("ascii"), entry[3:].decode("utf-8")
        original = None
        if "R" in code or "C" in code:
            original = raw[index].decode("utf-8")
            index += 1
        local = git.in_project(name)
        if local:
            paths.append({"path": local, "index": code[0], "worktree": code[1], "untracked": code == "??",
                          "conflict": code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"},
                          "previous_path": git.in_project(original) if original else None})
    report.update(changes=paths, dirty=bool(paths), conflicts=[x["path"] for x in paths if x["conflict"]],
                  remotes=_remote_summary(git), uninspected_submodules=git.submodules(),
                  submodule_scope="not_recursed_not_certified", authority_protection={"enabled": _marker(git).is_file(),
                  "tracked_protected": git.tracked_protected()})
    if compare is not None:
        base = git.commit(_reference(compare))
        info = {"requested_ref": compare, "reference_commit": base, "status": "unknown",
                "basis": "local_saved_reference_not_remote_live", "merge_base": None}
        if not base or not commit:
            info["reason"] = "比较对象不存在或当前尚无 commit"
        else:
            common = git._run("merge-base", commit, base, ok=(0, 1)).decode().strip()
            info["merge_base"] = common or None
            if common:
                ahead, behind = map(int, git._run("rev-list", "--left-right", "--count", commit + "..." + base).split())
                info.update(status="known", ahead=ahead, behind=behind)
            else:
                info["reason"] = "不存在共同基线"
        report["comparison"] = info
    return report


def _file_snapshot(root, path):
    from copilot_runtime import safe_path
    path = _relative(path)
    if (Path(root) / path).is_symlink():
        raise GitError("符号链接不能作为提案文件快照")
    target = safe_path(root, path, exists=False)
    if not target.exists():
        return {"path": path, "sha256": None, "byte_size": 0, "exists": False}
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_BLOB:
        raise GitError("只支持项目内普通文件且单文件不超过 4 MiB；其他材料需单独审查")
    data = target.read_bytes()
    return {"path": path, "sha256": _sha(data), "byte_size": len(data), "exists": True}


def _impact(cp, files):
    from copilot_domain import impact_analysis
    paths = {x["path"] for x in files}
    direct = sorted(oid for oid in cp["current"].values()
                    if paths.intersection(x["path"] for x in cp["objects"][oid].get("files", [])))
    edges = [{"from_id": dep, "to_id": oid, "invalidates": True}
             for oid, obj in cp["objects"].items() for dep in obj["dependencies"]]
    downstream = set(direct)
    for oid in direct:
        downstream.update(x["id"] for x in impact_analysis(edges, oid)["impacted"])
    known = {x["path"] for oid in direct for x in cp["objects"][oid].get("files", [])}
    return {"direct_objects": direct, "affected_objects": sorted(downstream),
            "affected_kinds": sorted({cp["objects"][x]["kind"] for x in downstream}),
            "unknown_paths": sorted(paths - known), "basis": "registered file hashes and dependency edges",
            "unknown_means": "未登记映射，须人工确认；不表示无影响"}


def diff_report(workspace, compare, *, patch=False):
    from copilot_runtime import Runtime, safe_path
    git = LocalGit(workspace)
    report = repository_status(workspace, compare)
    if not report["is_repository"] or report["comparison"]["status"] != "known":
        return {"status": "unknown", "repository": report, "changes": [], "impact": None}
    base = report["comparison"]["merge_base"]
    names = set()
    for name in git.names("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", base, report["commit"], "--"):
        local = git.in_project(name)
        if local:
            names.add(local)
    for item in report["changes"]:
        names.add(item["path"])
        if item["previous_path"]:
            names.add(item["previous_path"])
    changes = []
    for name in sorted(names):
        # Protected content never enters a proposal/patch; report the violation.
        if _protected(name):
            changes.append({"path": name, "protected": True, "content": "not_exported"})
            continue
        if name in report["uninspected_submodules"]:
            changes.append({"path": name, "change": "gitlink_not_inspected", "content": "not_exported"})
            continue
        old = git.blob(base, name)
        item = _file_snapshot(workspace, name)
        if item["sha256"] == (_sha(old) if old is not None else None):
            continue
        item["base_sha256"] = _sha(old) if old is not None else None
        item["base_byte_size"] = len(old) if old is not None else 0
        item["change"] = "added" if old is None else "modified" if item["exists"] else "deleted"
        if patch:
            new = safe_path(workspace, name).read_bytes() if item["exists"] else b""
            try:
                lines = list(difflib.unified_diff((old or b"").decode("utf-8").splitlines(), new.decode("utf-8").splitlines(),
                                                 fromfile="base/" + name, tofile="worktree/" + name, lineterm=""))
                item["patch"] = "\n".join(lines[:2000])
                item["patch_truncated"] = len(lines) > 2000
                if not lines and old != new:
                    item["patch_reason"] = "line endings or final newline differ; inspect byte hashes"
            except UnicodeError:
                item["patch"] = None
                item["patch_reason"] = "binary; hashes only"
        changes.append(item)
    state = Runtime(workspace).read()
    impact = _impact(state["copilot"], changes)
    impact["uninspected_submodules"] = report["uninspected_submodules"]
    return {"status": "known", "repository": report, "project_id": state["copilot"]["project_id"],
            "revision": state["copilot"]["revision"], "source_state_hash": state["copilot"]["state_hash"],
            "changes": changes, "impact": impact,
            "authority_read_only": True}


def _action(action):
    from copilot_runtime import SOURCE_KINDS
    if (not isinstance(action, dict) or set(action) != {"kind", "key", "payload", "dependencies", "files"}
            or action["kind"] not in SOURCE_KINDS | {"ArtifactRecord"}
            or not isinstance(action["payload"], dict) or not isinstance(action["key"], str)
            or not isinstance(action["dependencies"], list) or not isinstance(action["files"], list)
            or any(not isinstance(x, str) for x in action["dependencies"] + action["files"])):
        raise ValueError("提案只支持一个明确源对象/生成产物 register 操作；Run/Claim/核验必须走原专用入口")
    for name in action["files"]:
        if _protected(_relative(name)):
            raise ValueError("提案不得写入权威/运行历史")
    return copy.deepcopy(action)


def create_proposal(workspace, *, compare, reason, action, task_id=None, test_receipts=()):
    from copilot_runtime import Runtime
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("需要具体修改原因")
    action = _action(action)
    report = diff_report(workspace, compare)
    if report["status"] != "known" or report["repository"]["conflicts"]:
        raise ConflictError("缺少明确共同 Git 基线或存在文件合并冲突")
    if report["repository"]["authority_protection"]["tracked_protected"] or any(x.get("protected") for x in report["changes"]):
        raise IntegrityError("密封状态/历史不允许作为普通 Git 提案传输")
    rt = Runtime(workspace)
    state = rt.read()
    cp = state["copilot"]
    if cp["state_hash"] != report["source_state_hash"]:
        raise ConflictError("读取期间权威版本改变，请重试")
    task_id = task_id or cp.get("current_task")
    if task_id is not None and task_id not in cp["tasks"]:
        raise ValueError("Task 不存在")
    selected = set(action["dependencies"])
    if cp["current"].get(action["key"]):
        selected.add(cp["current"][action["key"]])
    pending = list(selected)
    while pending:
        oid = pending.pop()
        if oid not in cp["objects"]:
            raise ValueError("提案依赖不存在")
        for dep in cp["objects"][oid]["dependencies"]:
            if dep not in selected:
                selected.add(dep)
                pending.append(dep)
    base_objects = {cp["objects"][oid]["key"]: oid for oid in selected}
    if any(cp["current"].get(key) != oid for key, oid in base_objects.items()):
        raise ConflictError("提案依赖不是源工作区的当前对象")
    base_objects.setdefault(action["key"], None)
    # Only explicit action files (and its typed payload references) are the
    # transfer allowlist. Other real diff entries remain review metadata.
    paths = set(action["files"])
    # Capture payload file references too; register decides their full validity.
    if action["payload"].get("path"):
        paths.add(action["payload"]["path"])
    paths.update(x["path"] for x in action["payload"].get("files", []))
    paths.update(x["path"] for x in action["payload"].get("source_files", []))
    if isinstance(action["payload"].get("checker"), dict):
        paths.add(action["payload"]["checker"].get("path", ""))
    if any(_protected(_relative(p)) for p in paths):
        raise ValueError("权威/运行历史路径不允许进入提案")
    receipts = []
    for supplied in test_receipts:
        if (not isinstance(supplied, dict) or set(supplied) != {"command", "exit_code", "log"}
                or not isinstance(supplied["command"], list) or not supplied["command"]
                or any(not isinstance(x, str) for x in supplied["command"])
                or type(supplied["exit_code"]) is not int):
            raise ValueError("外部测试记录须有真实 command/exit_code/log；不接受按文件名推断通过")
        receipts.append({**copy.deepcopy(supplied), "log_binding": _file_snapshot(workspace, supplied["log"]),
                         "basis": "caller_supplied_receipt_not_reexecuted_or_certified"})
        if not receipts[-1]["log_binding"]["exists"]:
            raise ValueError("测试记录必须绑定实际日志")
    result = {"format": FORMAT, "project_id": cp["project_id"], "task_id": task_id,
              "base_revision": cp["revision"], "base_state_hash": cp["state_hash"],
              "base_objects": base_objects, "source_commit": report["repository"]["commit"],
              "comparison": report["repository"]["comparison"], "dirty": report["repository"]["dirty"],
              "reason": reason, "action": action, "changed_files": report["changes"],
              "file_snapshots": [_file_snapshot(workspace, p) for p in sorted(paths)],
              "impact": report["impact"], "test_receipts": receipts,
              "tests_executed_by_adapter": [], "not_executed": ["remote GitHub operations", "automatic merge", "independent test execution"],
              "handoff_semantics": "received != adopted != verified", "created_at": utc_now()}
    result["proposal_id"] = digest(result)
    return result


def _unseal(proposal):
    if not isinstance(proposal, dict) or proposal.get("format") != FORMAT:
        raise ValueError("未知提案格式")
    raw = copy.deepcopy(proposal)
    proposal_id = raw.pop("proposal_id", None)
    if digest(raw) != proposal_id:
        raise IntegrityError("提案内容已改变；摘要哈希不是签名或发送者认证")
    _action(raw.get("action"))
    return raw


def apply_proposal(workspace, proposal, *, expected_revision, actor="integrator"):
    """Only the integrator's explicit Store register transaction can adopt it."""
    from copilot_runtime import Runtime
    _unseal(proposal)
    git = LocalGit(workspace)
    if not git.root or not _marker(git).is_file():
        raise IntegrityError("接纳 Git 提案前须在集成端显式执行 git protect")
    assert_authority_boundary(workspace)
    if repository_status(workspace)["conflicts"]:
        raise ConflictError("工作树仍有文件合并冲突")

    class ProposalRuntime(Runtime):
        def _tx(self, revision, who, reason, mutate, request_id=None, intent=None):
            def guarded(state):
                cp = state["copilot"]
                if cp["project_id"] != proposal["project_id"]:
                    raise ConflictError("提案来自另一项目")
                base = state_at_revision(state, proposal["base_revision"])
                if base["copilot"]["state_hash"] != proposal["base_state_hash"]:
                    raise ConflictError("基础 revision 不属于集成端同一权威历史")
                for key, oid in proposal["base_objects"].items():
                    if base["copilot"]["current"].get(key) != oid or cp["current"].get(key) != oid:
                        raise ConflictError("对象版本冲突: " + key)
                # Do not trust a resealed bundle that omits a dependency guard.
                action = proposal["action"]
                required = {action["key"]}
                pending = list(action["dependencies"])
                while pending:
                    oid = pending.pop()
                    obj = base["copilot"]["objects"].get(oid)
                    if obj is None:
                        raise ConflictError("提案依赖不属于基础 revision")
                    if obj["key"] not in required:
                        required.add(obj["key"])
                        pending.extend(obj["dependencies"])
                if not required <= set(proposal["base_objects"]):
                    raise IntegrityError("提案遗漏基础对象版本保护")
                snapshots = proposal["file_snapshots"]
                if len({x["path"] for x in snapshots}) != len(snapshots):
                    raise IntegrityError("提案文件快照重复")
                for item in snapshots:
                    if _protected(item["path"]) or _file_snapshot(self.root, item["path"]) != item:
                        raise ConflictError("文件不匹配提案实际快照: " + item["path"])
                result = mutate(state)
                # Runtime may add implicit payload references; all must be bound.
                created = cp["objects"][result["object_id"]]
                supplied = {x["path"]: x for x in snapshots}
                for binding in created["files"]:
                    item = supplied.get(binding["path"])
                    if not item or item["sha256"] != binding["sha256"].lower() or item["byte_size"] != binding["byte_size"]:
                        raise IntegrityError("登记文件未被提案完整绑定")
                result["git_proposal_id"] = proposal["proposal_id"]
                result["source_commit"] = proposal["source_commit"]
                return result
            return super()._tx(revision, who, "接纳 Git 提案 " + proposal["proposal_id"] + ": " + proposal["reason"],
                               guarded, request_id, intent)

    action = proposal["action"]
    return ProposalRuntime(workspace).register(expected_revision, action["kind"], action["key"], action["payload"],
                                               dependencies=action["dependencies"], files=action["files"], actor=actor)


def draft_proposal(proposal):
    _unseal(proposal)
    action = proposal["action"]
    lines = ["# 本地 PR 描述草稿", "", "未发送至 GitHub；不是已创建的 PR。", "",
             "目的：" + proposal["reason"], "", f"项目：`{proposal['project_id']}`；任务：`{proposal['task_id']}`",
             f"基础 revision：`{proposal['base_revision']}`；来源 commit：`{proposal['source_commit'] or 'unknown'}`",
             "commit 只描述 Git 历史；实际未提交内容以本提案 file_snapshots 的 SHA-256 为准。", "",
             f"拟采用：`{action['kind']} / {action['key']}`，经既有 register 事务核对当前基线。", "", "来源工作区记录的改动（接纳前按快照复核；提案不是身份签名）："]
    lines += ["- `" + x["path"] + "` (" + x.get("change", "unknown") + ")" for x in proposal["changed_files"]] or ["- 没有文件 diff；提案为显式对象变更。"]
    lines += ["", "依赖影响：" + (", ".join(proposal["impact"]["affected_objects"]) or "尚无已登记映射"),
              "待确认文件：" + (", ".join(proposal["impact"]["unknown_paths"]) or "无额外未映射文件"), "",
              "未递归检查的子模块：" + (", ".join(proposal["impact"].get("uninspected_submodules", [])) or "无"), "",
              "协作适配器未运行任何测试。以下仅为调用者提供且绑定实际日志的外部记录；未独立认证："]
    lines += ["- " + json.dumps(x["command"], ensure_ascii=False) + f"；exit={x['exit_code']}；日志 `{x['log']}`" for x in proposal["test_receipts"]] or ["- 未提供，不能填写测试通过。"]
    lines += ["", "待办：审查未知影响；转移清单内文件；接纳事务；重新运行/核验受影响结果；导出新 Context。",
              "接收 ≠ 采用 ≠ 核验。普通 Git merge、分支名 main 或本草稿不能增加 verified/Ready。", ""]
    return "\n".join(lines)


def handoff(workspace, *, role, member=None, task_id=None, since=None, compare=None):
    from copilot_context import build_context
    assert_authority_boundary(workspace)
    ctx = build_context(workspace, role=role, member=member, task_id=task_id, since=since)
    return {"format": "mathmodel-git-handoff/0.2", "context": ctx,
            "repository": repository_status(workspace, compare),
            "semantics": "Context uses existing ack; wrapping or viewing is not receipt, adoption or verification"}


def verify_workspace(workspace):
    from copilot_runtime import Runtime, project_status
    assert_authority_boundary(workspace)
    rt = Runtime(workspace)
    before = rt.store.path.read_bytes()
    state = rt.read()
    status = project_status(workspace, state)
    current = set(state["copilot"]["current"].values())
    current_stale = {oid: reasons for oid, reasons in status["stale_objects"].items() if oid in current}
    after = rt.store.path.read_bytes()
    if before != after:
        raise ConflictError("复验期间权威状态改变，请重新读取")
    return {"project_id": state["copilot"]["project_id"], "revision": state["copilot"]["revision"],
            "source_state_hash": state["copilot"]["state_hash"], "authority_sha256": _sha(after),
            "authority_unchanged": True, "status": status, "repository": repository_status(workspace),
            "passed": not current_stale, "current_stale_objects": current_stale,
            "historical_stale_objects": [oid for oid in status["stale_objects"] if oid not in current],
            "submission_ready": status["submission"]["ready"],
            "scope": "current file/object bindings; not mathematical rerun, human review or submission approval"}


def parser():
    p = argparse.ArgumentParser(description="Optional Git collaboration; team setup uses GitHub only when requested, no auto merge")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("team", help="检查 GitHub 登录、创建私有队伍仓库或邀请队友")
    s.add_argument("arguments", nargs=argparse.REMAINDER)
    for name in ("status", "diff"):
        s = sub.add_parser(name)
        s.add_argument("--compare", required=name == "diff")
        if name == "diff":
            s.add_argument("--patch", action="store_true", help="Explicitly include up to 2000 lines/file; may contain workspace material")
    sub.add_parser("protect", help="Enable local-only authority exclusion; refuse already tracked sealed files")
    sub.add_parser("verify", help="Read current bindings after file integration; no automatic reconcile")
    s = sub.add_parser("proposal")
    s.add_argument("--compare", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--action", required=True, help="Project-relative structured register action JSON")
    s.add_argument("--task-id")
    s.add_argument("--test-receipts", help="Project-relative JSON array of external command/exit_code/log receipts")
    s.add_argument("--output", required=True, help="New project-relative JSON; never overwrites")
    for name in ("apply", "draft"):
        s = sub.add_parser(name)
        s.add_argument("--proposal", required=True)
        if name == "apply":
            s.add_argument("--expected-revision", required=True, type=int)
            s.add_argument("--actor", default="integrator")
        else:
            s.add_argument("--output", required=True)
    s = sub.add_parser("handoff")
    s.add_argument("--role", choices=["modeler", "coder", "writer", "integrator", "qa"], required=True)
    s.add_argument("--member")
    s.add_argument("--task-id")
    s.add_argument("--since", type=int)
    s.add_argument("--compare")
    s.add_argument("--output")
    return p


def _load(root, name):
    from copilot_runtime import safe_path
    return json.loads(safe_path(root, _relative(name)).read_text(encoding="utf-8"))


def _write_new(root, name, result):
    from copilot_runtime import safe_path
    if _protected(_relative(name)):
        raise ValueError("协作输出不得写入权威/历史目录")
    path = safe_path(root, name, exists=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {"path": name, "sha256": _sha(path.read_bytes()), "local_only": True}


def execute(args):
    root = args.workspace.resolve()
    if args.command == "team":
        from copilot_github import execute as team_execute, parser as team_parser
        return team_execute(team_parser().parse_args(["--workspace", str(root), *args.arguments]))
    if args.command == "status": return repository_status(root, args.compare)
    if args.command == "diff": return diff_report(root, args.compare, patch=args.patch)
    if args.command == "protect": return protect(root)
    if args.command == "verify": return verify_workspace(root)
    if args.command == "proposal":
        result = create_proposal(root, compare=args.compare, reason=args.reason, action=_load(root, args.action), task_id=args.task_id,
                                 test_receipts=_load(root, args.test_receipts) if args.test_receipts else ())
        return _write_new(root, args.output, result)
    if args.command == "apply":
        return apply_proposal(root, _load(root, args.proposal), expected_revision=args.expected_revision, actor=args.actor)
    if args.command == "draft": return _write_new(root, args.output, draft_proposal(_load(root, args.proposal)))
    if args.command == "handoff":
        result = handoff(root, role=args.role, member=args.member, task_id=args.task_id, since=args.since, compare=args.compare)
        return _write_new(root, args.output, result) if args.output else result
    raise ValueError("Unknown Git command")


def main(argv=None):
    try:
        result = execute(parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("ok") is False else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
