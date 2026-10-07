"""Simulated gh transport only: no login, real GitHub repositories or invitations."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_github as cg

REPOSITORY = "captain/mathmodel-team"
USER = {"id": 1, "login": "captain", "type": "User"}
TEAMMATE = {"id": 2, "login": "teammate", "type": "User"}
REPO = {"id": 10, "full_name": REPOSITORY, "private": True, "visibility": "private",
        "permissions": {"admin": True}, "owner": USER, "archived": False, "disabled": False}
INVITATION = {"id": 30, "invitee": TEAMMATE, "permissions": "write", "repository": REPO}


def reply(method, endpoint, code=200, data=None, *, body=None, raw=None, error=None):
    return {"method": method, "endpoint": endpoint, "code": code, "data": data,
            "body": body, "raw": raw, "error": error}


class FakeGh:
    """Assert the actual outbound command, body and effect order, not a wrapper."""
    def __init__(self, test, replies):
        self.test, self.replies, self.calls = test, list(replies), []

    def __call__(self, argv, **kwargs):
        t = self.test
        t.assertTrue(self.replies, "unexpected additional outbound request")
        expected = self.replies.pop(0)
        method = argv[argv.index("--method") + 1]
        endpoint = argv[-3] if "--input" in argv else argv[-1]
        t.assertEqual(argv[:2], ["gh", "api"])
        t.assertEqual(argv[argv.index("--hostname") + 1], "github.com")
        t.assertIn("--include", argv)
        t.assertIn("X-GitHub-Api-Version: " + cg.API_VERSION, argv)
        t.assertNotIn("--paginate", argv)
        t.assertFalse(kwargs["shell"])
        t.assertEqual(kwargs["timeout"], 30)
        t.assertEqual(Path(kwargs["cwd"]), self.test.workspace)
        t.assertNotIn("GH_DEBUG", kwargs["env"])
        body = json.loads(kwargs["input"]) if kwargs["input"] else None
        self.calls.append((method, endpoint, body))
        t.assertEqual((method, endpoint, body), (expected["method"], expected["endpoint"], expected["body"]))
        if expected["error"]:
            raise expected["error"]
        code = expected["code"]
        data = b"" if code == 204 else json.dumps(expected["data"]).encode()
        raw = expected["raw"] if expected["raw"] is not None else f"HTTP/2.0 {code} Test\r\nContent-Type: application/json\r\n\r\n".encode() + data
        return subprocess.CompletedProcess(argv, int(code >= 400), raw, b"PRIVATE_RESPONSE_TOKEN_DO_NOT_ECHO")


class GitHubTeamTests(unittest.TestCase):
    def setUp(self):
        # Respect the project's non-Git private test temp, when supplied.
        base = os.environ.get("MATHMODEL_PRIVATE_TEST_TEMP")
        temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name).resolve()
        for name, data in {"state/decision_log.json": b'{"authority":"must stay unchanged"}',
                           ".copilot/runs/sealed.json": b"sealed historical evidence",
                           ".git/config": b"[remote \"origin\"]\n url = PRIVATE_EXISTING_REMOTE\n",
                           "problem.txt": b"PRIVATE_PROBLEM_DO_NOT_UPLOAD"}.items():
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.before = self.files()
        self.addCleanup(self.assert_unchanged)

    def files(self):
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def assert_unchanged(self):
        self.assertEqual(self.before, self.files(), "authority/history/remote or workspace files changed")

    def run_with(self, operation, replies):
        fake = FakeGh(self, replies)
        with patch.object(cg.shutil, "which", return_value="gh"), patch.object(cg.subprocess, "run", side_effect=fake):
            report = operation()
        self.assertEqual(fake.replies, [], "expected network readback was skipped")
        self.assertFalse(report["authority_changed"])
        self.assertFalse(report["local_git_changed"])
        self.assertFalse(report["files_uploaded"])
        encoded = json.dumps(report)
        for private in ("PRIVATE_RESPONSE_TOKEN", "PRIVATE_PROBLEM", "PRIVATE_EXISTING_REMOTE"):
            self.assertNotIn(private, encoded)
        return report, fake.calls

    def create(self, confirm=False):
        return cg.create_private_repository(self.workspace, "mathmodel-team", confirm=confirm)

    def invite(self, confirm=False):
        return cg.invite_collaborator(self.workspace, REPOSITORY, "teammate", confirm=confirm)

    def create_preflight(self, repository=None):
        return [reply("GET", "user", data=USER), reply("GET", "repos/" + REPOSITORY,
                code=200 if repository else 404, data=repository)]

    def invite_preflight(self, permission=None, invitations=()):
        return [reply("GET", "user", data=USER), reply("GET", "repos/" + REPOSITORY, data=REPO),
                reply("GET", "users/teammate", data=TEAMMATE),
                reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", code=200 if permission else 404,
                      data={"permission": permission, "role_name": permission, "user": TEAMMATE} if permission else None),
                *([] if permission in {"admin", "write"} else
                  [reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=list(invitations))])]

    def test_missing_gh_is_actionable_and_has_no_network(self):
        with patch.object(cg.shutil, "which", return_value=None), patch.object(cg.subprocess, "run") as run:
            report = self.create(True)
        run.assert_not_called()
        self.assertEqual(report["status"], "missing_gh")
        self.assertFalse(report["ok"])
        self.assertFalse(report["mutation_attempted"])
        self.assertTrue(report["next_steps"])

    def test_not_logged_in_never_creates(self):
        report, calls = self.run_with(lambda: self.create(True), [reply("GET", "user", 401)])
        self.assertEqual(report["status"], "authentication_required")
        self.assertFalse(report["remote_changed"])
        self.assertEqual(len(calls), 1)

    def test_local_gh_login_prompt_is_not_echoed(self):
        result = subprocess.CompletedProcess([], 4, b"", b"gh auth login; SECRET_LOCAL_CREDENTIAL")
        with patch.object(cg.shutil, "which", return_value="gh"), patch.object(cg.subprocess, "run", return_value=result):
            report = self.create(True)
        self.assertEqual(report["status"], "authentication_required")
        self.assertNotIn("SECRET_LOCAL", json.dumps(report))

    def test_invalid_names_and_repositories_never_touch_network(self):
        invalid_names = ("../secret", "--public", "a/b", "x.git", "a\n", "你好", "x" * 101, None)
        with patch.object(cg.subprocess, "run") as run:
            for value in invalid_names:
                self.assertEqual(cg.create_private_repository(self.workspace, value, confirm=True)["status"], "invalid_input")
            for value in ("https://github.com/x/y", "x/y/z", "--owner/repo", "captain/a?b", "captain/repo.git"):
                self.assertEqual(cg.github_team_status(self.workspace, value)["status"], "invalid_input")
            for value in ("@teammate", "a--b", "a@example.org", "-x", "x/../../a", "x" * 40):
                self.assertEqual(cg.invite_collaborator(self.workspace, REPOSITORY, value, confirm=True)["status"], "invalid_input")
        run.assert_not_called()

    def test_non_boolean_confirmation_never_touches_network(self):
        with patch.object(cg.subprocess, "run") as run:
            for confirmation in (1, "yes", None):
                self.assertEqual(self.create(confirmation)["status"], "invalid_input")
                self.assertEqual(self.invite(confirmation)["status"], "invalid_input")
        run.assert_not_called()

    def test_status_verifies_private_admin_and_pending_is_not_accepted(self):
        replies = self.create_preflight(REPO) + [reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[INVITATION])]
        report, calls = self.run_with(lambda: cg.github_team_status(self.workspace, REPOSITORY), replies)
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["pending_invitations"][0]["accepted"])
        self.assertEqual(report["pending_invitations"][0]["user_id"], TEAMMATE["id"])
        self.assertEqual(report["pending_invitations"][0]["repository_id"], REPO["id"])
        self.assertEqual(report["repository"]["owner"]["id"], USER["id"])
        self.assertTrue(all(method == "GET" for method, _, _ in calls))

    def test_create_without_confirmation_only_previews(self):
        report, calls = self.run_with(self.create, self.create_preflight())
        self.assertEqual(report["status"], "confirmation_required")
        self.assertFalse(report["completed"])
        self.assertFalse(report["created"])
        self.assertFalse(report["mutation_attempted"])
        self.assertEqual(report["target_repository"], REPOSITORY)
        self.assertTrue(all(method == "GET" for method, _, _ in calls))

    def test_create_private_empty_then_reads_actual_repository_and_branches(self):
        replies = self.create_preflight() + [reply("POST", "user/repos", 201, REPO,
                  body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                  reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/branches?per_page=1", data=[])]
        report, calls = self.run_with(lambda: self.create(True), replies)
        self.assertEqual(report["status"], "created")
        self.assertTrue(report["completed"])
        self.assertTrue(report["empty_repository_verified"])
        self.assertEqual(sum(m == "POST" for m, _, _ in calls), 1)

    def test_duplicate_create_returns_existing_without_post(self):
        report, calls = self.run_with(lambda: self.create(True), self.create_preflight(REPO))
        self.assertEqual(report["status"], "already_exists")
        self.assertFalse(report["created"])
        self.assertFalse(report["remote_changed"])
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_public_existing_repository_is_never_overwritten(self):
        repo = {**REPO, "private": False, "visibility": "public"}
        report, calls = self.run_with(lambda: self.create(True), self.create_preflight(repo))
        self.assertEqual(report["status"], "unsafe_repository")
        self.assertFalse(report["ok"])
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_invitation_requires_private_admin_and_active_repository(self):
        for change, status in (({"permissions": {"admin": False}}, "admin_required"),
                               ({"private": False, "visibility": "public"}, "unsafe_repository"),
                               ({"archived": True}, "unsafe_repository"),
                               ({"private": "true"}, "unsafe_repository")):
            with self.subTest(change=change):
                report, calls = self.run_with(lambda: self.invite(True), self.create_preflight({**REPO, **change}))
                self.assertEqual(report["status"], status)
                self.assertFalse(report["mutation_attempted"])
                self.assertEqual(len(calls), 2)

    def test_account_identity_is_validated(self):
        for user in ({**USER, "login": "--bad"}, {**USER, "type": "Organization"}, {**USER, "id": True}):
            report, _ = self.run_with(lambda: self.create(True), [reply("GET", "user", data=user)])
            self.assertFalse(report["ok"])
            self.assertFalse(report["mutation_attempted"])

    def test_cannot_invite_self_or_an_organization(self):
        replies = self.create_preflight(REPO)
        report, _ = self.run_with(lambda: cg.invite_collaborator(self.workspace, REPOSITORY, "CAPTAIN", confirm=True), replies)
        self.assertEqual(report["status"], "invalid_input")
        replies = self.create_preflight(REPO) + [reply("GET", "users/teammate", data={**TEAMMATE, "type": "Organization"})]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "invalid_input")

    def test_invite_default_is_read_only_preview(self):
        report, calls = self.run_with(self.invite, self.invite_preflight())
        self.assertEqual(report["status"], "confirmation_required")
        self.assertFalse(report["accepted"])
        self.assertFalse(report["collaboration_ready"])
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_confirmed_invite_sends_only_push_and_reads_pending(self):
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                  INVITATION, body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", 404),
                  reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[INVITATION])]
        report, calls = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "invitation_pending")
        self.assertTrue(report["completed"])
        self.assertFalse(report["accepted"])
        self.assertFalse(report["collaboration_ready"])
        self.assertEqual([(m, b) for m, _, b in calls if m != "GET"], [("PUT", {"permission": "push"})])

    def test_duplicate_pending_invite_does_not_resend(self):
        report, calls = self.run_with(lambda: self.invite(True), self.invite_preflight(invitations=[INVITATION]))
        self.assertEqual(report["status"], "invitation_pending")
        self.assertFalse(report["accepted"])
        self.assertFalse(report["remote_changed"])
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_existing_write_or_admin_is_observed_and_never_changed(self):
        for permission in ("write", "admin"):
            report, calls = self.run_with(lambda: self.invite(True), self.invite_preflight(permission=permission))
            self.assertEqual(report["status"], "already_collaborator")
            self.assertTrue(report["collaboration_ready"])
            self.assertEqual(report["membership"]["permission"], permission)
            self.assertFalse(report["remote_changed"])
            self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_pending_admin_or_expired_invitation_requires_review(self):
        for changes in ({"permissions": "admin"}, {"expired": True}):
            entry = {**INVITATION, **changes}
            report, calls = self.run_with(lambda: self.invite(True), self.invite_preflight(invitations=[entry]))
            self.assertEqual(report["status"], "invitation_requires_review")
            self.assertFalse(report["ok"])
            self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_read_collaborator_upgrade_204_requires_write_readback(self):
        permission = {"permission": "write", "role_name": "write", "user": TEAMMATE}
        replies = self.invite_preflight(permission="read") + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 204,
                  body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", data=permission)]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "collaborator_access_verified")
        self.assertTrue(report["accepted"])
        self.assertTrue(report["collaboration_ready"])

    def test_invite_204_with_no_verified_access_is_uncertain(self):
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 204,
                  body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", 404),
                  reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[])]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["completed"])
        self.assertFalse(report["collaboration_ready"])

    def test_definitive_mutation_rejections_are_not_success_or_retried(self):
        for code in (403, 422, 429):
            for operation, replies in ((lambda: self.create(True), self.create_preflight() +
                    [reply("POST", "user/repos", code, body={"name": "mathmodel-team", "private": True, "auto_init": False})]),
                    (lambda: self.invite(True), self.invite_preflight() +
                    [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", code, body={"permission": "push"})])):
                report, calls = self.run_with(operation, replies)
                self.assertFalse(report["ok"])
                self.assertFalse(report["remote_changed"])
                self.assertNotEqual(report["status"], "uncertain")
                self.assertEqual(sum(m != "GET" for m, _, _ in calls), 1)
                self.assertTrue(report["next_steps"])

    def test_timeout_or_server_failure_is_uncertain_and_not_retried(self):
        for error, code in ((subprocess.TimeoutExpired("gh", 30), 200), (None, 500)):
            replies = self.create_preflight() + [reply("POST", "user/repos", code,
                      body={"name": "mathmodel-team", "private": True, "auto_init": False}, error=error)]
            report, calls = self.run_with(lambda: self.create(True), replies)
            self.assertEqual(report["status"], "uncertain")
            self.assertIsNone(report["remote_changed"])
            self.assertFalse(report["ok"])
            self.assertEqual(sum(m == "POST" for m, _, _ in calls), 1)

    def test_success_receipt_without_repository_readback_is_uncertain(self):
        replies = self.create_preflight() + [reply("POST", "user/repos", 201, REPO,
                  body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                  reply("GET", "repos/" + REPOSITORY, 403)]
        report, _ = self.run_with(lambda: self.create(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertTrue(report["remote_changed"])
        self.assertFalse(report["completed"])

    def test_created_repo_must_match_receipt_and_be_actually_empty(self):
        for created, branches in (({**REPO, "id": 11}, None), (REPO, [{"name": "main"}])):
            replies = self.create_preflight() + [reply("POST", "user/repos", 201, created,
                      body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                      reply("GET", "repos/" + REPOSITORY, data=REPO)]
            if branches is not None:
                replies.append(reply("GET", f"repos/{REPOSITORY}/branches?per_page=1", data=branches))
            report, _ = self.run_with(lambda: self.create(True), replies)
            self.assertEqual(report["status"], "uncertain")
            self.assertFalse(report["completed"])

    def test_wrong_invitation_receipt_cannot_claim_success(self):
        for change in ({"invitee": USER}, {"permissions": "admin"}, {"repository": {**REPO, "id": 11}}):
            replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                      {**INVITATION, **change}, body={"permission": "push"})]
            report, _ = self.run_with(lambda: self.invite(True), replies)
            self.assertEqual(report["status"], "uncertain")
            self.assertFalse(report["ok"])
            self.assertFalse(report["accepted"])

    def test_full_invitation_page_is_followed_before_inviting(self):
        entries = [{**INVITATION, "id": i + 1, "invitee": {**TEAMMATE, "id": i + 100, "login": f"other{i}"}} for i in range(100)]
        replies = self.invite_preflight(invitations=entries) + [reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=2", data=[INVITATION])]
        report, calls = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "invitation_pending")
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_partial_invitation_list_blocks_mutation(self):
        replies = self.invite_preflight()
        replies[-1] = reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", 403)
        report, calls = self.run_with(lambda: self.invite(True), replies)
        self.assertFalse(report["ok"])
        self.assertFalse(report["mutation_attempted"])
        self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_unknown_or_malformed_responses_do_not_pass(self):
        for raw in (b"invalid", b"HTTP/2.0 200 Test\n\nnot-json", b"x" * (cg.MAX_RESPONSE + 1)):
            report, _ = self.run_with(lambda: self.create(True), [reply("GET", "user", raw=raw)])
            self.assertFalse(report["ok"])
            self.assertFalse(report["mutation_attempted"])

    def test_environment_uses_existing_local_auth_without_debug_or_host_override(self):
        with patch.dict(os.environ, {"GH_HOST": "example.invalid", "GH_DEBUG": "api", "GH_TOKEN": "SECRET_DO_NOT_PRINT"}):
            report, _ = self.run_with(lambda: cg.github_team_status(self.workspace), [reply("GET", "user", data=USER)])
        self.assertEqual(report["status"], "authenticated")
        self.assertNotIn("SECRET_DO_NOT_PRINT", json.dumps(report))

    def test_same_login_with_different_permission_user_id_is_rejected(self):
        for user_id in (999, None, 0, -1, True, "2"):
            replies = self.invite_preflight(permission="write")
            replies[-1]["data"]["user"] = {**TEAMMATE, "id": user_id}
            report, calls = self.run_with(lambda: self.invite(True), replies)
            self.assertFalse(report["ok"])
            self.assertFalse(report["accepted"])
            self.assertFalse(report["collaboration_ready"])
            self.assertFalse(report["mutation_attempted"])
            self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_pending_invitation_binds_user_and_repository_ids(self):
        entries = [{**INVITATION, "invitee": {**TEAMMATE, "id": user_id}}
                   for user_id in (999, None, 0, True, "2")]
        entries += [{**INVITATION, "repository": {**REPO, "id": repository_id}}
                    for repository_id in (999, None, 0, True, "10")]
        for entry in entries:
            report, calls = self.run_with(lambda: self.invite(True), self.invite_preflight(invitations=[entry]))
            self.assertFalse(report["ok"])
            self.assertFalse(report["accepted"])
            self.assertFalse(report["collaboration_ready"])
            self.assertFalse(report["mutation_attempted"])
            self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_status_invitation_repo_id_and_user_id_must_be_valid(self):
        entries = [{**INVITATION, "repository": {**REPO, "id": 999}}]
        entries += [{**INVITATION, "invitee": {**TEAMMATE, "id": user_id}}
                    for user_id in (None, 0, -1, True, "2")]
        for entry in entries:
            replies = self.create_preflight(REPO) + [reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[entry])]
            report, _ = self.run_with(lambda: cg.github_team_status(self.workspace, REPOSITORY), replies)
            self.assertFalse(report["ok"])
            self.assertFalse(report["completed"])
            self.assertFalse(report["mutation_attempted"])

    def test_permission_user_id_drift_after_write_is_uncertain(self):
        permission = {"permission": "write", "role_name": "write", "user": {**TEAMMATE, "id": 999}}
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 204,
                  body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", data=permission)]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["accepted"])
        self.assertFalse(report["collaboration_ready"])

    def test_pending_user_id_drift_after_write_is_uncertain(self):
        entry = {**INVITATION, "invitee": {**TEAMMATE, "id": 999}}
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                  INVITATION, body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", 404),
                  reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[entry])]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["accepted"])

    def test_repository_id_drift_after_write_is_uncertain(self):
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                  INVITATION, body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data={**REPO, "id": 999})]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["accepted"])

    def test_new_invitation_receipt_binds_target_user_id(self):
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                  {**INVITATION, "invitee": {**TEAMMATE, "id": 999}}, body={"permission": "push"})]
        report, _ = self.run_with(lambda: self.invite(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["accepted"])

    def test_create_existing_owner_must_match_authenticated_account_id(self):
        for owner in ({**USER, "id": 999}, {**USER, "login": "other"}, {**USER, "type": "Organization"}):
            report, calls = self.run_with(lambda: self.create(True), self.create_preflight({**REPO, "owner": owner}))
            self.assertFalse(report["ok"])
            self.assertFalse(report["mutation_attempted"])
            self.assertTrue(all(m == "GET" for m, _, _ in calls))

    def test_create_receipt_owner_must_match_account_and_readback_ids(self):
        for owner in ({**USER, "id": 999}, {**USER, "id": True}, {**USER, "login": "other"}, None):
            replies = self.create_preflight() + [reply("POST", "user/repos", 201, {**REPO, "owner": owner},
                      body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                      reply("GET", "repos/" + REPOSITORY, data=REPO)]
            report, _ = self.run_with(lambda: self.create(True), replies)
            self.assertEqual(report["status"], "uncertain")
            self.assertFalse(report["ok"])
            self.assertFalse(report["completed"])

    def test_create_readback_owner_must_match_authenticated_account(self):
        replies = self.create_preflight() + [reply("POST", "user/repos", 201, REPO,
                  body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                  reply("GET", "repos/" + REPOSITORY, data={**REPO, "owner": {**USER, "id": 999}})]
        report, _ = self.run_with(lambda: self.create(True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["completed"])

    def test_status_repository_owner_requires_valid_id_type_and_matching_handle(self):
        owners = [{**USER, "id": user_id} for user_id in (None, 0, -1, True, "1", 999)]
        owners += [{**USER, "login": "other"}, {**USER, "type": "Bot"}]
        for owner in owners:
            report, _ = self.run_with(lambda: cg.github_team_status(self.workspace, REPOSITORY),
                                      self.create_preflight({**REPO, "owner": owner}))
            self.assertFalse(report["ok"])
            self.assertFalse(report["completed"])
            self.assertFalse(report["mutation_attempted"])

    def test_status_can_read_private_organization_owner_with_valid_identity(self):
        repository = "team-org/mathmodel-team"
        owner = {"login": "team-org", "id": 20, "type": "Organization"}
        repo = {**REPO, "full_name": repository, "owner": owner}
        replies = [reply("GET", "user", data=USER), reply("GET", "repos/" + repository, data=repo),
                   reply("GET", f"repos/{repository}/invitations?per_page=100&page=1", data=[])]
        report, _ = self.run_with(lambda: cg.github_team_status(self.workspace, repository), replies)
        self.assertTrue(report["ok"])
        self.assertEqual(report["repository"]["owner"], owner)

    def test_organization_owner_id_drift_after_invite_is_uncertain(self):
        repository = "team-org/mathmodel-team"
        owner = {"login": "team-org", "id": 20, "type": "Organization"}
        repo = {**REPO, "full_name": repository, "owner": owner}
        invitation = {**INVITATION, "repository": repo}
        replies = [reply("GET", "user", data=USER), reply("GET", "repos/" + repository, data=repo),
                   reply("GET", "users/teammate", data=TEAMMATE),
                   reply("GET", f"repos/{repository}/collaborators/teammate/permission", 404),
                   reply("GET", f"repos/{repository}/invitations?per_page=100&page=1", data=[]),
                   reply("PUT", f"repos/{repository}/collaborators/teammate", 201, invitation, body={"permission": "push"}),
                   reply("GET", "repos/" + repository, data={**repo, "owner": {**owner, "id": 999}})]
        report, _ = self.run_with(lambda: cg.invite_collaborator(self.workspace, repository, "teammate", confirm=True), replies)
        self.assertEqual(report["status"], "uncertain")
        self.assertFalse(report["ok"])
        self.assertFalse(report["accepted"])
        self.assertFalse(report["collaboration_ready"])

    def test_cli_parser_dispatches_exact_scope_and_confirmation(self):
        args = cg.parser().parse_args(["--workspace", str(self.workspace), "create-private", "--name", "mathmodel-team"])
        report, _ = self.run_with(lambda: cg.execute(args), self.create_preflight())
        self.assertEqual(report["status"], "confirmation_required")
        args = cg.parser().parse_args(["--workspace", str(self.workspace), "invite", "--repository", REPOSITORY,
                                      "--username", "teammate", "--confirm"])
        report, _ = self.run_with(lambda: cg.execute(args), self.invite_preflight(invitations=[INVITATION]))
        self.assertEqual(report["status"], "invitation_pending")

    def check_public_cli(self, arguments, replies, expected_status, expected_code=0):
        import copilot
        import copilot_git
        for entry, prefix in ((copilot.main, ["git", "team"]), (copilot_git.main, ["team"]), (cg.main, [])):
            with self.subTest(entry=entry.__module__, arguments=arguments):
                fake = FakeGh(self, replies)
                capture = io.StringIO()
                with patch.object(cg.shutil, "which", return_value="gh"), patch.object(cg.subprocess, "run", side_effect=fake), patch("sys.stdout", capture):
                    code = entry(["--workspace", str(self.workspace), *prefix, *arguments])
                self.assertEqual(code, expected_code)
                emitted = json.loads(capture.getvalue())
                report = emitted.get("result", emitted)
                self.assertEqual(report["status"], expected_status)
                self.assertEqual(emitted["ok"], expected_code == 0)
                self.assertEqual(fake.replies, [])
                self.assertNotIn("PRIVATE_", capture.getvalue())

    def test_public_status_cli_forwarding_and_failure_exit(self):
        self.check_public_cli(["status"], [reply("GET", "user", data=USER)], "authenticated")
        self.check_public_cli(["status", "--repository", REPOSITORY],
                              [reply("GET", "user", 401)], "authentication_required", 2)

    def test_public_create_cli_forwarding_mutation_and_failure_exit(self):
        replies = self.create_preflight() + [reply("POST", "user/repos", 201, REPO,
                  body={"name": "mathmodel-team", "private": True, "auto_init": False}),
                  reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/branches?per_page=1", data=[])]
        self.check_public_cli(["create-private", "--name", "mathmodel-team", "--confirm"], replies, "created")
        self.check_public_cli(["create-private", "--name", "mathmodel-team", "--confirm"],
                              self.create_preflight({**REPO, "permissions": {"admin": False}}), "admin_required", 2)

    def test_public_invite_cli_forwarding_mutation_and_failure_exit(self):
        replies = self.invite_preflight() + [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 201,
                  INVITATION, body={"permission": "push"}), reply("GET", "repos/" + REPOSITORY, data=REPO),
                  reply("GET", f"repos/{REPOSITORY}/collaborators/teammate/permission", 404),
                  reply("GET", f"repos/{REPOSITORY}/invitations?per_page=100&page=1", data=[INVITATION])]
        args = ["invite", "--repository", REPOSITORY, "--username", "teammate", "--confirm"]
        self.check_public_cli(args, replies, "invitation_pending")
        self.check_public_cli(args, self.invite_preflight() +
                              [reply("PUT", f"repos/{REPOSITORY}/collaborators/teammate", 403, body={"permission": "push"})],
                              "forbidden", 2)


if __name__ == "__main__":
    unittest.main()
