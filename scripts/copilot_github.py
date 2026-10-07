#!/usr/bin/env python3
"""Explicit GitHub team setup via gh; never transports workspace files.

This adapter has no Store, Git, remote-configuration or credential writes.
GET preflight is separate from a caller's explicit confirm=True mutation.
An invitation receipt is never evidence that the teammate accepted it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

HOST = "github.com"
API_VERSION = "2026-03-10"
MAX_RESPONSE = 2 * 1024 * 1024
MAX_INVITATION_PAGES = 10


class GitHubError(ValueError):
    def __init__(self, code, message, *, uncertain=False, http_status=None):
        super().__init__(message)
        self.code, self.uncertain, self.http_status = code, uncertain, http_status


def _username(value):
    if (not isinstance(value, str) or len(value) > 39
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", value)
            or "--" in value):
        raise GitHubError("invalid_input", "需要 GitHub 用户名；不接受邮箱、URL、@ 前缀或命令选项")
    return value


def _repo_name(value):
    if (not isinstance(value, str) or len(value) > 100
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
            or value.endswith(".") or value.casefold().endswith(".git")):
        raise GitHubError("invalid_input", "仓库名需为 1–100 个 ASCII 字母、数字、点、下划线或连字符，并以字母或数字开头；不含 .git 后缀")
    return value


def _repository(value):
    if not isinstance(value, str) or value.count("/") != 1:
        raise GitHubError("invalid_input", "仓库必须明确写成 owner/name；不接受 URL 或本地 remote 推断")
    owner, name = value.split("/")
    return _username(owner) + "/" + _repo_name(name)


def _identity(data, *, login=None, user_id=None, organization=False):
    """Bind an API subject to its immutable ID as well as its current handle."""
    if (not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0
            or data.get("type") not in ({"User", "Organization"} if organization else {"User"})):
        raise GitHubError("unexpected_response", "GitHub 主体 ID 或账号类型无法核对")
    try:
        observed_login = _username(data.get("login"))
    except GitHubError as exc:
        raise GitHubError("unexpected_response", "GitHub 主体用户名无法核对") from exc
    if ((login is not None and observed_login.casefold() != login.casefold())
            or (user_id is not None and data["id"] != user_id)):
        raise GitHubError("verification_failed", "GitHub 主体用户名或不可变 ID 与首次观察不一致")
    return {"id": data["id"], "login": observed_login, "type": data["type"]}


def _report(action):
    return {"action": action, "ok": False, "completed": False, "status": "not_started",
            "host": HOST, "observed_at": datetime.now(timezone.utc).isoformat(),
            "account": None, "repository": None, "gh_available": False,
            "mutation_attempted": False, "remote_changed": False, "network_actions": [],
            "authority_changed": False, "local_git_changed": False, "files_uploaded": False,
            "message": "", "next_steps": []}


def _fail(report, exc):
    uncertain = exc.uncertain or report["remote_changed"] is True
    if report["mutation_attempted"] and not uncertain:
        report["remote_changed"] = False  # A definitive HTTP rejection.
    report.update(ok=False, completed=False, status="uncertain" if uncertain else exc.code,
                  error_code=exc.code, message=str(exc))
    if exc.http_status is not None:
        report["http_status"] = exc.http_status
    if uncertain:
        report["next_steps"] = ["先在 GitHub 核对目标仓库或邀请状态，再执行只读 status；结果未确认前不要重复创建或邀请"]
    elif exc.code == "missing_gh":
        report["next_steps"] = ["安装官方 GitHub CLI：https://cli.github.com/", "由本人运行 gh auth login --hostname github.com，再重试只读检查；不要把令牌发给 AI"]
    elif exc.code == "authentication_required":
        report["next_steps"] = ["由本人运行 gh auth login --hostname github.com；已有登录时运行 gh auth status --hostname github.com 核对账号", "不要把密码或令牌发给 AI"]
    elif exc.code in {"forbidden", "admin_required"}:
        report["next_steps"] = ["核对 gh 当前账号对目标私有仓库的管理权限，以及本机凭据的仓库管理授权，再重试；不要把令牌发给 AI"]
    else:
        report["next_steps"] = ["核对具体账号、owner/name 和网络状态后重试只读检查；已存在仓库或邀请不会被自动覆盖"]
    return report


def _safe_env():
    # Existing gh authentication stays local. Never print tokens or raw stderr.
    env = {k: v for k, v in os.environ.items() if k.upper() not in
           {"GH_HOST", "GH_REPO", "GH_DEBUG", "GH_PAGER", "PAGER", "CLICOLOR_FORCE"}}
    env.update(GH_PROMPT_DISABLED="1", GH_PAGER="", NO_COLOR="1")
    return env


class _GitHub:
    def __init__(self, workspace, report):
        try:
            self.workspace = Path(workspace).resolve()
            exists = self.workspace.is_dir()
        except (TypeError, ValueError, OSError) as exc:
            raise GitHubError("invalid_input", "workspace 必须是已存在的目录") from exc
        if not exists:
            raise GitHubError("invalid_input", "workspace 必须是已存在的目录")
        self.report = report
        self.repositories = {}
        self.executable = shutil.which("gh")
        report["gh_available"] = bool(self.executable)
        if not self.executable:
            raise GitHubError("missing_gh", "未发现 GitHub CLI；本地建模仍可继续")

    def api(self, method, endpoint, *, body=None, allowed=(200,)):
        argv = [self.executable, "api", "--hostname", HOST, "--method", method,
                "--include", "-H", "Accept: application/vnd.github+json",
                "-H", "X-GitHub-Api-Version: " + API_VERSION, endpoint]
        payload = None
        if body is not None:
            argv += ["--input", "-"]
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        record = {"method": method, "endpoint": endpoint, "http_status": None}
        self.report["network_actions"].append(record)
        mutation = method != "GET"
        if mutation:
            self.report.update(mutation_attempted=True, remote_changed=None)
        try:
            result = subprocess.run(argv, cwd=self.workspace, env=_safe_env(), input=payload,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=30, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError("transport_unavailable", "GitHub 请求未得到可核对结果；检查 gh 与网络",
                              uncertain=mutation) from exc
        if len(result.stdout) > MAX_RESPONSE:
            raise GitHubError("response_limit", "GitHub 响应超出读取上限；未据此确认成功", uncertain=mutation)
        raw = result.stdout.replace(b"\r\n", b"\n")
        headers, separator, data = raw.partition(b"\n\n")
        status = re.match(rb"HTTP/\S+ ([0-9]{3})(?:\s|$)", headers)
        if not separator or not status:
            # Gh uses this text when there is no local authentication. It is
            # classified, never echoed (stderr may include private data).
            needs_login = b"gh auth login" in result.stderr or b"GH_TOKEN" in result.stderr
            raise GitHubError("authentication_required" if needs_login else "transport_unavailable",
                              "GitHub 登录不可用；请由本人检查本机 gh 登录" if needs_login else "gh 未返回可核对的 HTTP 结果",
                              uncertain=mutation)
        status = int(status[1])
        record["http_status"] = status
        if status not in allowed or (result.returncode and status < 400):
            code = {401: "authentication_required", 403: "forbidden", 404: "not_found_or_inaccessible",
                    422: "validation_failed", 429: "rate_limited"}.get(status, "unexpected_response")
            raise GitHubError(code, f"GitHub 请求未通过 (HTTP {status})；未回显原始响应或凭据",
                              uncertain=mutation and (status >= 500 or status < 400), http_status=status)
        if status == 204 or status >= 400:
            return status, None
        try:
            parsed = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise GitHubError("unexpected_response", "GitHub 响应不是可核对的 JSON", uncertain=mutation) from exc
        return status, parsed

    def account(self):
        _, user = self.api("GET", "user")
        identity = _identity(user)
        self.report["account"] = {"login": identity["login"], "id": identity["id"]}
        return identity["login"]

    def repo(self, repository, *, missing=False, expected_owner=None):
        code, data = self.api("GET", "repos/" + repository, allowed=(200, 404) if missing else (200,))
        if code == 404:
            return None
        if (not isinstance(data, dict) or not isinstance(data.get("full_name"), str)
                or data["full_name"].casefold() != repository.casefold()
                or type(data.get("id")) is not int or data["id"] <= 0
                or not isinstance(data.get("owner"), dict)
                or data["owner"].get("type") not in {"User", "Organization"}
                or not isinstance(data.get("permissions"), dict)):
            raise GitHubError("unexpected_response", "仓库身份或权限响应无法核对")
        if data.get("private") is not True or data.get("visibility") != "private":
            raise GitHubError("unsafe_repository", "目标仓库不是已核对的私有仓库；不会修改可见性或上传文件")
        if data["permissions"].get("admin") is not True:
            raise GitHubError("admin_required", "当前账号没有已核对的仓库管理权限；未开放协作权限")
        if data.get("archived") is not False or data.get("disabled") is not False:
            raise GitHubError("unsafe_repository", "目标仓库已归档、停用或状态无法核对")
        owner = _identity(data["owner"], login=repository.split("/")[0], organization=True)
        account = self.report["account"]
        if account and owner["login"].casefold() == account["login"].casefold():
            _identity(data["owner"], login=account["login"], user_id=account["id"])
        if expected_owner is not None:
            _identity(data["owner"], login=expected_owner["login"], user_id=expected_owner["id"])
        previous = self.repositories.get(repository.casefold())
        if previous and (previous["id"] != data["id"] or previous["owner"]["id"] != owner["id"]):
            raise GitHubError("verification_failed", "仓库或所有者不可变 ID 与首次观察不一致")
        summary = {"id": data["id"], "full_name": _repository(data["full_name"]),
                   "private": True, "admin": True, "owner_type": owner["type"], "owner": owner,
                   "html_url": "https://github.com/" + data["full_name"]}
        self.repositories[repository.casefold()] = summary
        self.report["repository"] = summary
        return summary

    def permission(self, repository, username, *, user_id):
        code, data = self.api("GET", f"repos/{repository}/collaborators/{username}/permission", allowed=(200, 404))
        if code == 404:
            return {"permission": "none", "role_name": "none"}
        if (not isinstance(data, dict) or data.get("permission") not in {"admin", "write", "read", "none"}
                or not isinstance(data.get("user"), dict)
                or not isinstance(data["user"].get("login"), str)
                or data["user"]["login"].casefold() != username.casefold()
                or not isinstance(data.get("role_name"), str)
                or not re.fullmatch(r"[A-Za-z0-9 _-]{1,100}", data["role_name"])):
            raise GitHubError("unexpected_response", "队友权限响应无法核对；未据此重发邀请")
        _identity(data["user"], login=username, user_id=user_id)
        return {"permission": data["permission"], "role_name": data["role_name"]}

    def invitations(self, repository):
        expected_repository = self.repositories.get(repository.casefold())
        if expected_repository is None:
            raise GitHubError("verification_failed", "必须先回读目标仓库身份，再核对邀请")
        invitations = []
        for page in range(1, MAX_INVITATION_PAGES + 1):
            _, data = self.api("GET", f"repos/{repository}/invitations?per_page=100&page={page}")
            if not isinstance(data, list) or len(data) > 100:
                raise GitHubError("unexpected_response", "待接受邀请列表无法核对")
            for entry in data:
                if (not isinstance(entry, dict) or type(entry.get("id")) is not int or entry["id"] <= 0
                        or not isinstance(entry.get("invitee"), dict)
                        or entry.get("permissions") not in {"read", "write", "triage", "maintain", "admin"}
                        or not isinstance(entry.get("repository"), dict)
                        or not isinstance(entry["repository"].get("full_name"), str)
                        or entry["repository"]["full_name"].casefold() != repository.casefold()
                        or type(entry["repository"].get("id")) is not int
                        or entry["repository"]["id"] != expected_repository["id"]
                        or type(entry.get("expired", False)) is not bool):
                    raise GitHubError("unexpected_response", "待接受邀请的身份或权限无法核对")
                invitee = _identity(entry["invitee"])
                invitations.append({"id": entry["id"], "username": invitee["login"], "user_id": invitee["id"],
                                    "repository_id": expected_repository["id"],
                                    "permission": entry["permissions"], "accepted": False,
                                    "expired": entry.get("expired", False)})
            if len(data) < 100:
                return invitations
        raise GitHubError("response_limit", "待接受邀请超过 1000 条，未检查完整；未发送新邀请")


def github_team_status(workspace, repository=None):
    """Read current account and, when explicit, private/admin team repository."""
    report = _report("status")
    try:
        if repository is not None:
            repository = _repository(repository)
        client = _GitHub(workspace, report)
        client.account()
        if repository is not None:
            client.repo(repository)
            report["pending_invitations"] = client.invitations(repository)
        report.update(ok=True, completed=True, status="ready" if repository else "authenticated",
                      message="已回读当前账号及目标私有仓库权限" if repository else "已回读当前 GitHub 账号；尚未指定队伍仓库")
        return report
    except GitHubError as exc:
        return _fail(report, exc)


def create_private_repository(workspace, repo_name, *, confirm=False):
    """Preview or create an empty private repository under the current user."""
    report = _report("create-private")
    try:
        repo_name = _repo_name(repo_name)
        if type(confirm) is not bool:
            raise GitHubError("invalid_input", "confirm 必须是明确的布尔值")
        client = _GitHub(workspace, report)
        account = client.account()
        repository = account + "/" + repo_name
        report["target_repository"] = repository
        existing = client.repo(repository, missing=True, expected_owner=report["account"])
        if existing:
            report.update(ok=True, completed=True, status="already_exists", created=False,
                          message="同名私有仓库已存在且当前账号可管理；未覆盖或更改仓库")
            return report
        report["planned_action"] = {"method": "POST", "endpoint": "user/repos",
                                    "name": repo_name, "private": True, "auto_init": False}
        if not confirm:
            report.update(ok=True, status="confirmation_required", created=False,
                          message=f"准备在 {account} 下创建空私有仓库 {repo_name}；尚未创建",
                          next_steps=["向本人说明具体账号、仓库名及私有空仓库范围；已有明确授权时使用 --confirm 执行"])
            return report
        _, created = client.api("POST", "user/repos", body={"name": repo_name, "private": True, "auto_init": False}, allowed=(201,))
        report["remote_changed"] = True
        observed = client.repo(repository, expected_owner=report["account"])
        if (not isinstance(created, dict) or type(created.get("id")) is not int or created["id"] != observed["id"]
                or not isinstance(created.get("full_name"), str) or created["full_name"].casefold() != repository.casefold()
                or observed["owner_type"] != "User"):
            raise GitHubError("verification_failed", "创建回执与仓库回读不一致；未确认创建结果")
        _identity(created.get("owner"), login=observed["owner"]["login"], user_id=observed["owner"]["id"])
        # auto_init=false is the request boundary; read branches to establish
        # actual emptiness rather than treating the request alone as evidence.
        _, branches = client.api("GET", f"repos/{repository}/branches?per_page=1")
        if branches != []:
            raise GitHubError("verification_failed", "仓库回读发现分支或空仓库状态无法核对；请先检查 GitHub")
        report.update(ok=True, completed=True, status="created", created=True, empty_repository_verified=True,
                      message="空私有队伍仓库已创建并回读；请把队友的 GitHub 用户名发给 AI 以准备写权限邀请",
                      next_steps=["提供队友 GitHub 用户名，并明确允许向该仓库发送协作邀请；队友收到后自行接受", "如需上传代码或文稿，另行审查具体文件与远端关联；当前未配置 remote 或推送"])
        return report
    except GitHubError as exc:
        return _fail(report, exc)


def _membership(client, repository, username, user_id):
    permission = client.permission(repository, username, user_id=user_id)
    if permission["permission"] in {"write", "admin"}:
        return "collaborator", permission
    matching = [entry for entry in client.invitations(repository)
                if entry["username"].casefold() == username.casefold()]
    if len(matching) > 1:
        raise GitHubError("unexpected_response", "同一用户名存在多条邀请；未自动重发")
    if matching and matching[0]["user_id"] != user_id:
        raise GitHubError("verification_failed", "待接受邀请的队友不可变 ID 与首次观察不一致")
    return ("pending", matching[0]) if matching else ("absent", permission)


def invite_collaborator(workspace, repository, username, *, confirm=False):
    """Preview or request push/write permission; read back pending vs accepted."""
    report = _report("invite")
    report.update(accepted=False, collaboration_ready=False, requested_permission="push")
    try:
        repository, username = _repository(repository), _username(username)
        report.update(target_repository=repository, username=username)
        if type(confirm) is not bool:
            raise GitHubError("invalid_input", "confirm 必须是明确的布尔值")
        client = _GitHub(workspace, report)
        account = client.account()
        client.repo(repository)
        if account.casefold() == username.casefold():
            raise GitHubError("invalid_input", "不能把当前登录账号当作待邀请队友")
        _, user = client.api("GET", "users/" + username, allowed=(200,))
        try:
            identity = _identity(user, login=username)
        except GitHubError as exc:
            raise GitHubError("invalid_input", "未核对到目标个人 GitHub 用户；不能邀请组织或猜测身份") from exc
        report["teammate"] = identity
        state, observed = _membership(client, repository, username, identity["id"])
        report["membership"] = observed
        if state == "collaborator":
            report.update(ok=True, completed=True, status="already_collaborator", accepted=True, collaboration_ready=True,
                          message="队友已有写权限或更高权限；未重发邀请或改动已有权限")
            return report
        if state == "pending":
            if observed["expired"] or observed["permission"] != "write":
                raise GitHubError("invitation_requires_review", "已有邀请已过期或权限不是 write；请在 GitHub 审查，未自动改权限或重发")
            report.update(ok=True, completed=True, status="invitation_pending",
                          message="已有写权限邀请待队友接受；未重发，尚不能确认队友可协作",
                          next_steps=["请队友在 GitHub 通知中自行接受，再执行 invite 只读预检核对生效权限"])
            return report
        report["planned_action"] = {"method": "PUT", "endpoint": f"repos/{repository}/collaborators/{username}", "permission": "push"}
        if not confirm:
            report.update(ok=True, status="confirmation_required",
                          message=f"准备向 {username} 开放 {repository} 的写权限；尚未发送邀请或改权限",
                          next_steps=["向本人列明仓库、具体 GitHub 用户名和写权限；已有明确邀请授权时使用 --confirm 执行"])
            return report
        code, receipt = client.api("PUT", f"repos/{repository}/collaborators/{username}",
                                   body={"permission": "push"}, allowed=(201, 204))
        report["remote_changed"] = True
        if code == 201 and (not isinstance(receipt, dict) or type(receipt.get("id")) is not int or receipt["id"] <= 0
                            or receipt.get("permissions") != "write"
                            or not isinstance(receipt.get("invitee"), dict)
                            or not isinstance(receipt["invitee"].get("login"), str)
                            or receipt["invitee"]["login"].casefold() != username.casefold()
                            or type(receipt["invitee"].get("id")) is not int
                            or receipt["invitee"]["id"] != identity["id"]
                            or not isinstance(receipt.get("repository"), dict)
                            or not isinstance(receipt["repository"].get("full_name"), str)
                            or receipt["repository"]["full_name"].casefold() != repository.casefold()
                            or type(receipt["repository"].get("id")) is not int
                            or receipt["repository"].get("id") != report["repository"]["id"]):
            raise GitHubError("verification_failed", "邀请回执的仓库、用户名或写权限无法核对")
        if code == 201:
            _identity(receipt["invitee"], login=username, user_id=identity["id"])
        # Recheck visibility/admin and then membership. A 204 may be a role
        # update or immediate organization grant, not a pending invitation.
        client.repo(repository)
        state, observed = _membership(client, repository, username, identity["id"])
        report["membership"] = observed
        if state == "pending" and observed["permission"] == "write" and not observed["expired"]:
            if (code != 201 or not isinstance(receipt, dict) or receipt.get("id") != observed["id"]):
                raise GitHubError("verification_failed", "邀请回执与待接受邀请回读不一致")
            report.update(ok=True, completed=True, status="invitation_pending",
                          message="写权限邀请已发送并回读，等待队友自行接受；尚不能确认可协作",
                          next_steps=["请队友在 GitHub 通知中自行接受，再执行 invite 只读预检核对生效权限"])
        elif state == "collaborator" and observed == {"permission": "write", "role_name": "write"}:
            report.update(ok=True, completed=True, status="collaborator_access_verified", accepted=True, collaboration_ready=True,
                          message="已回读队友当前写权限；可开始传递经审查的协作材料")
        else:
            raise GitHubError("verification_failed", "未回读到预期写权限或待接受邀请；不能确认权限开放成功")
        return report
    except GitHubError as exc:
        return _fail(report, exc)


def parser():
    p = argparse.ArgumentParser(description="GitHub private team setup; explicit remote authorization, no uploads")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status")
    s.add_argument("--repository")
    s = sub.add_parser("create-private")
    s.add_argument("--name", required=True)
    s.add_argument("--confirm", action="store_true")
    s = sub.add_parser("invite")
    s.add_argument("--repository", required=True)
    s.add_argument("--username", required=True)
    s.add_argument("--confirm", action="store_true")
    return p


def execute(args):
    if args.command == "status": return github_team_status(args.workspace, args.repository)
    if args.command == "create-private": return create_private_repository(args.workspace, args.name, confirm=args.confirm)
    if args.command == "invite": return invite_collaborator(args.workspace, args.repository, args.username, confirm=args.confirm)
    raise ValueError("Unknown GitHub team command")


def main(argv=None):
    report = execute(parser().parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
