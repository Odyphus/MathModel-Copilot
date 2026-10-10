"""Local-only feedback tests: real private storage and injected fake transport."""
from __future__ import annotations

import copy
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
import copilot_usage_feedback as feedback


def request(action, scope):
    return {"source": "direct_user", "actor_type": "human", "request_id": "user-message-1",
            "text": "我明确同意在所示范围内进行本次操作。", "action": action, "scope": scope}


class FakeTransport:
    """Only injected through Python tests; never selectable by the real CLI."""
    def __init__(self):
        self.target = {"repository": "test-owner/feedback", "account": "test-user", "visibility": "private"}
        self.issues = []
        self.creates = 0
        self.body_files = []
        self.auth_error = False
        self.create_error = None
        self.read_error = False

    def inspect(self, repository):
        if self.auth_error:
            raise feedback.TransportError("auth_unavailable", "尚未登录")
        result = dict(self.target)
        result["repository"] = repository
        return result

    def create(self, payload, body_file):
        self.creates += 1
        assert body_file.read_text(encoding="utf-8") == payload["body"]
        self.body_files.append(body_file)
        url = f"https://github.com/{payload['repository']}/issues/{self.creates}"
        if self.create_error == "before_commit":
            raise feedback.TransportError("timeout", "未知是否创建")
        self.issues.append({"html_url": url, "title": payload["title"], "body": payload["body"],
                            "user": {"login": payload["account"]}})
        if self.create_error == "after_commit":
            raise feedback.TransportError("timeout", "连接中断")
        if self.create_error == "process_crash":
            raise RuntimeError("Simulated local crash after remote commit")
        return url

    def read_issue(self, repository, url):
        if self.read_error:
            raise feedback.TransportError("readback_failed", "暂时无法回读")
        return copy.deepcopy(next(issue for issue in self.issues if issue["html_url"] == url))

    def find(self, payload, marker):
        return [copy.deepcopy(issue) for issue in self.issues if marker in issue["body"]]


class UsageFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="usage-feedback-", dir=os.environ.get("MATHMODEL_PRIVATE_TEST_TEMP"))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project, self.profile = self.base / "project", self.base / "profile"
        self.project.mkdir()
        self.transport = FakeTransport()
        self.service = feedback.UsageFeedback(self.project, self.profile, transport=self.transport)

    def draft(self, **changes):
        payload = {"title": "页面看不明白", "description": "希望解释术语", "component": "dashboard", "event": "hard_to_understand"}
        payload.update(changes)
        return self.service.draft(payload)

    def configure(self, mode="review", events=None, maximum=0):
        repository = "test-owner/feedback"
        scope = {"binding": self.service.storage.binding, "mode": mode, "repository": repository,
                 "target": self.transport.inspect(repository) if mode == "limited_auto" else None,
                 "allowed_events": sorted(events or []), "max_submissions": maximum}
        return self.service.configure(mode, repository, events or [], maximum,
                                      request("configure_usage_feedback", scope), self.service.settings()["record_revision"])

    def approve(self, record):
        record = self.service.preview(record["id"])
        payload = record["preview"]["payload"]
        scope = {"binding": self.service.storage.binding, "feedback_id": record["id"],
                 "payload_sha256": record["preview"]["payload_sha256"],
                 **{key: payload[key] for key in ("repository", "account", "visibility")}}
        return self.service.approve(record["id"], scope["payload_sha256"], request("send_usage_feedback", scope), record["record_revision"])

    def prepared(self):
        self.configure()
        return self.approve(self.draft())

    def test_read_only_settings_and_listing_do_not_create_any_files(self):
        self.assertEqual("off", self.service.settings()["mode"])
        self.assertEqual([], self.service.list())
        self.assertFalse(self.profile.exists())
        self.assertEqual([], list(self.project.iterdir()))

    def test_optional_reproduction_exports_full_redacted_context_without_github(self):
        context = feedback.reproduction_example()
        private = 'a@example.org ghp_syntheticsecret123 https://example.org/private password=syntheticvalue'
        for key in feedback.REPRO_FIELDS:
            context[key] = {'text': '发生的情况 ' + private, 'source': 'user_report'}
        context['steps'] = [{'text': private, 'source': 'agent_summary'}]
        context['missing_context'] = [private]
        record = self.draft(reproduction=context)
        with patch.object(self.transport, 'inspect', side_effect=AssertionError('local preview must not contact GitHub')):
            local = self.service.preview(record['id'])
            self.service.export(record['id'], self.project/'local-feedback.md')
        body = local['local_preview']['body']
        saved = (self.project/'local-feedback.md').read_text(encoding='utf-8')
        for text in [body, saved]:
            self.assertIn('问题经过与复现线索', text)
            self.assertIn('不是用户逐字原话', text)
            for secret in ['a@example.org','ghp_synthetic','https://example.org','syntheticvalue']:
                self.assertNotIn(secret, text)
        self.assertFalse((self.project/'state').exists())
        self.assertIsNone(local['preview'])
        self.assertEqual(self.transport.creates, 0)

    def test_reproduction_gaps_do_not_become_claims_of_complete_context(self):
        record = self.draft(reproduction={'goal':{'text':'了解使用方式', 'source':'user_report'}})
        local = self.service.preview(record['id'])['local_preview']['body']
        self.assertIn('未填写的内容：操作步骤', local)
        self.assertIn('目前是否解决', local)
        self.assertIn('没有读取完整会话', local)
        self.assertNotIn('用户审阅后的', local)

    def test_invalid_reproduction_rejected_without_private_writes(self):
        invalid = [{'logs':'everything'}, {'goal':'text'}, {'goal':{'text':'x','source':'verified'}},
                   {'goal':{'text':'x','source':'agent_summary','approved':True}},
                   {'steps':[{'text':'x','source':'agent_summary'}]*9},
                   {'actual':{'text':'x'*1501,'source':'user_report'}},
                   {'missing_context':['gap']*6}, {'missing_context':'gap'},
                   {'steps':[{'text':'x'*1500,'source':'user_report'}]*6}]
        for context in invalid:
            with self.subTest(context=str(context)[:100]), self.assertRaises(ValueError):
                self.draft(reproduction=context)
        self.assertFalse(self.profile.exists())

    def test_reproduction_edit_invalidates_approval_and_request_dedup_checks_context(self):
        self.configure()
        record = self.draft(reproduction=feedback.reproduction_example())
        approved = self.approve(record)
        updated = copy.deepcopy(approved['draft'])
        updated['reproduction']['outcome'] = {'text':'还没有解决','source':'user_report'}
        changed = self.service.edit(record['id'], updated, approved['record_revision'])
        self.assertIsNone(changed['approval'])
        self.assertIsNone(changed['preview'])
        with self.assertRaises(ValueError): self.service.send(record['id'])
        first = self.service.draft(updated, request_id='reproduction-once')
        self.assertEqual(first['id'], self.service.draft(updated, request_id='reproduction-once')['id'])
        updated['reproduction']['outcome']['text'] = '后来已解决'
        with self.assertRaises(ValueError): self.service.draft(updated, request_id='reproduction-once')
        self.assertEqual(self.transport.creates, 0)

    def test_limited_auto_never_includes_reproduction_free_text(self):
        self.configure('limited_auto', ['no_experience'], 1)
        record = self.draft(reproduction={'actual':{'text':'PRIVATE-CONTEXT-SENTINEL','source':'user_report'}})
        preview = self.service.preview(record['id'])
        self.assertNotIn('PRIVATE-CONTEXT-SENTINEL', json.dumps(preview['preview']))
        self.assertNotIn('reproduction', json.dumps(preview['preview']))
        # Injected fake transport only; assert actual payload at this boundary.
        sent = self.service.send(record['id'])
        self.assertEqual(sent['status'], 'sent')
        self.assertNotIn('PRIVATE-CONTEXT-SENTINEL', self.transport.issues[0]['body'])

    def test_old_draft_shape_is_unchanged(self):
        record = self.draft()
        self.assertEqual(set(record['draft']), {'title','description','component','event'})

    def test_no_modeling_project_is_needed_and_no_store_is_created(self):
        record = self.draft()
        self.assertEqual("draft", record["status"])
        self.assertEqual(record, self.service.show(record["id"]))
        self.assertFalse((self.project / "state").exists())

    def test_default_off_never_calls_the_transport_create(self):
        record = self.draft()
        with self.assertRaisesRegex(ValueError, "关闭"):
            self.service.send(record["id"])
        self.assertEqual(0, self.transport.creates)

    def test_draft_rejects_reports_paths_logs_metrics_and_bad_types(self):
        for field in ("logs", "files", "path", "metrics", "report", "approval", "program_facts"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.draft(**{field: "private"})
        for value in (None, [], {}, True, "unexpected"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.draft(event=value)
        self.assertFalse(self.profile.exists())

    def test_redaction_masks_paths_urls_emails_and_recognizable_credentials(self):
        # Synthetic fixture paths; fixed components preserve the exact test input.
        windows_path = "\\".join(("C:", "Users", "Alice", "paper.docx"))
        unix_path = "/".join(("", "home", "alice", "data.csv"))
        raw = windows_path + " " + unix_path + " a@example.org ghp_1234567890 https://host/private?key=abc api_key=abcdef"
        cleaned = feedback.redact(raw)
        for private in ("Alice", "alice", "a@example.org", "ghp_", "https://", "abcdef"):
            self.assertNotIn(private, cleaned)

    def test_authentication_redaction_covers_full_bearer_basic_and_quoted_values(self):
        fixtures = [
            'Authorization: Bearer eyJqaSyntheticToken.secretFixture.signatureFixture',
            'Authorization: Basic dXNlcjpwYXNzd29yZA==',
            '"Authorization": "Bearer synthetic.secret.payload"',
            "'Authorization': 'Basic synthetic-secret-value'",
            'Proxy-Authorization = Bearer synthetic-secret-value',
            'Authorization:\nBearer synthetic-secret-value',
            '"api_key": "synthetic secret with spaces"',
            "password='synthetic secret with spaces'",
            'Bearer synthetic.secret.payload',
        ]
        for source in fixtures:
            with self.subTest(source=source):
                cleaned = feedback.redact(source)
                self.assertNotIn("synthetic", cleaned.casefold())
                self.assertNotIn("dXNlcjpwYXNzd29yZA", cleaned)
                self.assertNotIn("signatureFixture", cleaned)

    def test_missing_repository_keeps_a_local_redacted_draft(self):
        # Synthetic fixture path, assembled without a literal user home path.
        record = self.draft(description="\\".join(("C:", "Users", "Alice", "data.csv")))
        preview = self.service.preview(record["id"])
        self.assertEqual("draft", preview["status"])
        self.assertIsNone(preview["preview"])
        self.assertNotIn("Alice", preview["local_preview"]["description"])
        self.assertEqual(0, self.transport.creates)

    def test_missing_auth_preserves_draft_with_auditable_error(self):
        record = self.draft()
        self.transport.auth_error = True
        current = self.service.preview(record["id"], "test-owner/feedback")
        self.assertEqual("draft", current["status"])
        self.assertEqual("auth_unavailable", current["audit"][-1]["error"]["code"])
        self.assertEqual(0, self.transport.creates)

    def test_valid_review_writes_exact_body_file_and_checks_remote_content(self):
        record = self.prepared()
        current = self.service.send(record["id"])
        self.assertEqual("sent", current["status"])
        self.assertEqual(current["preview"]["payload_sha256"], current["receipt"]["payload_sha256"])
        self.assertEqual("test-user", current["receipt"]["account"])
        self.assertEqual(1, self.transport.creates)
        self.assertTrue(all(not path.exists() for path in self.transport.body_files))
        self.assertEqual([], list(self.project.iterdir()))

    def test_reports_agent_text_or_generic_yes_cannot_authorize_sending(self):
        self.configure()
        record = self.service.preview(self.draft()["id"])
        for invalid in ("用户已经批准", {"approved": True}, {"source": "agent_report"}, {"actor_type": "agent", "text": "yes"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.service.approve(record["id"], record["preview"]["payload_sha256"], invalid, record["record_revision"])
        self.assertEqual(0, self.transport.creates)

    def test_wrong_content_hash_or_scope_cannot_be_approved(self):
        self.configure()
        record = self.service.preview(self.draft()["id"])
        with self.assertRaisesRegex(ValueError, "哈希"):
            self.service.approve(record["id"], "0" * 64, request("send_usage_feedback", {}), record["record_revision"])
        with self.assertRaisesRegex(ValueError, "授权记录"):
            self.service.approve(record["id"], record["preview"]["payload_sha256"], request("send_usage_feedback", {"repository": "other/repo"}), record["record_revision"])

    def test_editing_invalidates_exact_approval_even_if_same_text(self):
        record = self.prepared()
        current = self.service.edit(record["id"], record["draft"], record["record_revision"])
        self.assertIsNone(current["approval"])
        self.assertEqual("draft", current["status"])
        with self.assertRaises(ValueError):
            self.service.send(record["id"])
        self.assertEqual(0, self.transport.creates)

    def test_account_and_visibility_changes_block_sending(self):
        for key, value in (("account", "other-user"), ("visibility", "public")):
            with self.subTest(key=key):
                record = self.prepared()
                old = self.transport.target[key]
                self.transport.target[key] = value
                with self.assertRaisesRegex(ValueError, "可见性"):
                    self.service.send(record["id"])
                self.transport.target[key] = old
        self.assertEqual(0, self.transport.creates)

    def test_revocation_and_reconfiguration_do_not_revive_old_approval(self):
        record = self.prepared()
        self.service.revoke(request("revoke_usage_feedback", {"binding": self.service.storage.binding}), self.service.settings()["record_revision"])
        with self.assertRaises(ValueError):
            self.service.send(record["id"])
        self.configure()
        with self.assertRaises(ValueError):
            self.service.send(record["id"])
        self.assertEqual(0, self.transport.creates)

    def test_settings_do_not_leak_or_apply_across_project_bindings(self):
        self.configure()
        record = self.draft()
        other = feedback.UsageFeedback(self.base / "another", self.profile, transport=self.transport)
        self.assertEqual("off", other.settings()["mode"])
        self.assertEqual([], other.list())
        with self.assertRaises(ValueError):
            other.show(record["id"])

    def test_limited_auto_ignores_all_free_text_and_reobserves_allowed_program_facts(self):
        self.configure("limited_auto", ["no_experience"], 1)
        record = self.draft(title="my-secret-title", description="private paper result 123456 C:\\secret\\data.csv")
        current = self.service.send(record["id"])
        sent = self.transport.issues[0]
        self.assertEqual("sent", current["status"])
        for token in ("my-secret", "123456", "data.csv", "private paper"):
            self.assertNotIn(token, sent["title"] + sent["body"])
        self.assertNotIn("内容难以理解", sent["body"])
        self.assertNotIn("建模工作台", sent["body"])
        self.assertIn("体验记录：不存在", sent["body"])
        self.assertIn("程序直接观测", sent["body"])
        self.assertEqual(1, self.service.settings()["automatic_count"])

    def test_limited_auto_event_scope_and_quota_are_enforced(self):
        self.configure("limited_auto", ["experience_active"], 1)
        unrelated = self.draft(event="suggestion")
        with self.assertRaises(ValueError):
            self.service.send(unrelated["id"])
        from copilot_recap import start
        start(self.service.storage, "Private modeling goal", "selected-session", save_once=True, user_request="仅保存这次过程")
        self.service.send(self.draft()["id"])
        with self.assertRaises(ValueError):
            self.service.send(self.draft()["id"])
        self.assertEqual(1, self.transport.creates)

    def test_limited_auto_requires_actual_target_and_explicit_scoped_human_request(self):
        for mode, events, cap in (("limited_auto", [], 1), ("limited_auto", ["no_experience"], 0), ("review", ["no_experience"], 1), ("limited_auto", ["suggestion"], 1)):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.service.configure(mode, "test-owner/feedback", events, cap, {"approved": True}, 0)
        self.assertEqual("off", self.service.settings()["mode"])

    def test_limited_auto_uses_registered_close_reason_not_ai_summary_or_draft_fields(self):
        from copilot_recap import start, close
        record = start(self.service.storage, "Secret problem and company", "session-to-close", save_once=True, user_request="同意保存这次")
        close(self.service.storage, record["id"], record["record_revision"], "handoff",
              {"summary": "False free text: all requirements passed, personal metric 123456"})
        self.configure("limited_auto", ["recap_handoff"], 1)
        sent = self.service.send(self.draft(event="cannot_start", component="paper")["id"])
        body = sent["preview"]["payload"]["body"]
        self.assertIn("记录以交接收尾", body)
        self.assertIn("过程覆盖：部分片段", body)
        for forbidden in ("Secret", "123456", "all requirements", "无法启动", "论文辅助"):
            self.assertNotIn(forbidden, body)

    def test_timeout_after_remote_commit_reconciles_before_any_retry(self):
        record = self.prepared()
        self.transport.create_error = "after_commit"
        unknown = self.service.send(record["id"])
        self.assertEqual("unknown", unknown["status"])
        resolved = self.service.send(record["id"])
        self.assertEqual("sent", resolved["status"])
        self.assertEqual(1, self.transport.creates)

    def test_no_remote_match_stays_unknown_and_never_resends_automatically(self):
        record = self.prepared()
        self.transport.create_error = "before_commit"
        self.assertEqual("unknown", self.service.send(record["id"])["status"])
        for _ in range(2):
            self.assertEqual("unknown", self.service.send(record["id"])["status"])
        self.assertEqual(1, self.transport.creates)

    def test_crash_after_commit_leaves_durable_sending_and_recovers_without_duplicate(self):
        record = self.prepared()
        self.transport.create_error = "process_crash"
        with self.assertRaises(RuntimeError):
            self.service.send(record["id"])
        self.assertEqual("sending", self.service.show(record["id"])["status"])
        self.assertEqual("sent", self.service.send(record["id"])["status"])
        self.assertEqual(1, self.transport.creates)

    def test_readback_failure_is_unknown_not_sent(self):
        record = self.prepared()
        self.transport.read_error = True
        self.assertEqual("unknown", self.service.send(record["id"])["status"])
        self.assertIsNone(self.service.show(record["id"])["receipt"])

    def test_duplicate_marker_or_wrong_remote_content_never_becomes_verified_receipt(self):
        record = self.prepared()
        self.transport.create_error = "after_commit"
        self.service.send(record["id"])
        self.transport.issues.append(copy.deepcopy(self.transport.issues[0]))
        self.assertEqual("unknown", self.service.reconcile(record["id"])["status"])
        self.transport.issues.pop()
        self.transport.issues[0]["body"] += "\nchanged"
        self.assertEqual("unknown", self.service.reconcile(record["id"])["status"])
        self.assertEqual(1, self.transport.creates)

    def test_sent_record_and_unknown_attempt_cannot_be_edited(self):
        record = self.prepared()
        current = self.service.send(record["id"])
        with self.assertRaises(ValueError):
            self.service.edit(current["id"], current["draft"], current["record_revision"])
        self.assertEqual(current, self.service.send(current["id"]))

    def test_cli_supports_offline_draft_and_has_no_fake_send_switch(self):
        (self.project / "input.json").write_text(json.dumps({"title": "反馈", "description": "说明", "component": "dashboard", "event": "suggestion"}), encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/copilot_usage_feedback.py"),
                              "--workspace", str(self.project), "--user-data", str(self.profile), "draft", "--input", "input.json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual("draft", json.loads(run.stdout)["status"])
        self.assertFalse((self.project / "state").exists())
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            feedback.parser().parse_args(["send", "--id", "any", "--fake-success"])

    def test_public_help_example_drafts_previews_and_exports_with_documented_flag(self):
        public = [sys.executable, "-B", str(ROOT / "scripts/copilot.py"), "--workspace", str(self.project)]
        def call(*args):
            result = subprocess.run([*public, *args], capture_output=True, text=True,
                                    encoding="utf-8", timeout=20)
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)["result"]
        help_data = call("payload-help", "usage-feedback")
        self.assertEqual("draft/edit", help_data["input_mode"].split()[0])
        flag = help_data["input_mode"].split()[1]
        (self.project / "example.json").write_text(json.dumps(help_data["example"]), encoding="utf-8")
        args = ["usage-feedback", "--user-data", str(self.profile)]
        record = call(*args, "draft", flag, "example.json")
        self.assertEqual("draft", record["status"])
        example = help_data["example"]
        example["description"] = "已补充说明；此条仍是合成示例。"
        (self.project / "example.json").write_text(json.dumps(example), encoding="utf-8")
        record = call(*args, "edit", flag, "example.json", "--id", record["id"],
                      "--record-revision", str(record["record_revision"]))
        self.assertEqual(example["description"], record["draft"]["description"])
        preview = call(*args, "preview", "--id", record["id"])
        call(*args, "export", "--id", record["id"], "--output", "example.md")
        body = (self.project / "example.md").read_text(encoding="utf-8")
        # Markdown export intentionally omits the hidden Issue dedup marker.
        self.assertIn(preview["local_preview"]["body"].split("<!-- mathmodel-copilot-feedback:")[0].rstrip(), body)
        self.assertIn("复现", body)
        self.assertIsNone(self.service.show(record["id"])["receipt"])
        self.assertEqual("off", self.service.settings()["mode"])
        self.assertIsInstance(call("experience", "--user-data", str(self.profile), "settings"), dict)
        self.assertFalse((self.project / "state").exists())

    def test_request_id_retry_reuses_the_same_draft_and_rejects_changed_content(self):
        payload = {"title": "标题", "description": "说明", "component": "dashboard", "event": "suggestion"}
        first = self.service.draft(payload, request_id="request-one")
        self.assertEqual(first, self.service.draft(payload, request_id="request-one"))
        with self.assertRaises(ValueError):
            self.service.draft(dict(payload, title="changed"), request_id="request-one")
        self.assertEqual(1, len(self.service.list()))

    def test_experience_binding_deduplicates_across_request_ids_and_checks_actual_source(self):
        from copilot_recap import start
        exp = start(self.service.storage, "Private", "source", save_once=True, user_request="本次保存")
        payload = {"title": "标题", "description": "说明", "component": "dashboard", "event": "suggestion"}
        first = self.service.draft(payload, "request-one", exp["id"])
        reused = self.service.draft(payload, "request-two", exp["id"])
        self.assertEqual(first["id"], reused["id"])
        self.assertEqual(["request-one", "request-two"], reused["request_ids"])
        another_exp = start(self.service.storage, "Other private goal", "another-source", save_once=True, user_request="本次保存")
        with self.assertRaises(ValueError):
            self.service.draft(payload, "request-two", another_exp["id"])
        with self.assertRaises(ValueError):
            self.service.draft(payload, "request-new", "EXP-not-existing")
        other = feedback.UsageFeedback(self.base / "other-project", self.profile, transport=self.transport)
        with self.assertRaises(ValueError):
            other.draft(payload, "other-request", exp["id"])
        self.assertEqual(1, len(self.service.list()))

    def test_changing_drafts_or_reconfiguring_cannot_bypass_one_automatic_feedback_per_experience(self):
        from copilot_recap import start
        start(self.service.storage, "Private", "source", save_once=True, user_request="本次保存")
        self.configure("limited_auto", ["experience_active"], 5)
        self.assertEqual("sent", self.service.send(self.draft()["id"])["status"])
        with self.assertRaisesRegex(ValueError, "最多一份"):
            self.service.send(self.draft()["id"])
        self.configure("limited_auto", ["experience_active"], 5)
        with self.assertRaisesRegex(ValueError, "最多一份"):
            self.service.send(self.draft()["id"])
        self.assertEqual(1, self.transport.creates)

    def test_unknown_automatic_send_reserves_the_experience_across_new_drafts(self):
        from copilot_recap import start
        start(self.service.storage, "Private", "source", save_once=True, user_request="本次保存")
        self.configure("limited_auto", ["experience_active"], 5)
        self.transport.create_error = "before_commit"
        self.assertEqual("unknown", self.service.send(self.draft()["id"])["status"])
        with self.assertRaisesRegex(ValueError, "最多一份"):
            self.service.send(self.draft()["id"])
        self.assertEqual(1, self.transport.creates)

    def experience_with_selected_events(self):
        from copilot_recap import start, record_event
        exp = start(self.service.storage, "Entire private goal not selected", "source", save_once=True, user_request="本次保存")
        for identity, kind, text in [("one", "user_report", "selected first fragment"),
                                     ("two", "agent_summary", "AI selected second fragment"),
                                     ("three", "agent_summary", "unselected private remainder")]:
            exp = record_event(self.service.storage, exp["id"], exp["record_revision"],
                               {"event_id": identity, "kind": "note", "text": text, "source_kind": kind, "source_ref": "saved selected message"})
        return exp

    def test_review_includes_only_selected_real_event_text_and_source_scopes(self):
        exp = self.experience_with_selected_events()
        self.configure()
        payload = {"title": "反馈", "description": "说明", "component": "dashboard", "event": "suggestion"}
        draft = self.service.draft(payload, experience_id=exp["id"], event_ids=["one", "two"])
        preview = self.service.preview(draft["id"])
        body = preview["preview"]["payload"]["body"]
        for expected in ("selected first fragment", "AI selected second fragment", "用户报告", "AI 转述", "不代表完整会话", "记录的来源范围"):
            self.assertIn(expected, body)
        self.assertNotIn("unselected private remainder", body)
        self.assertNotIn("Entire private goal", body)
        with self.assertRaises(ValueError):
            self.service.edit(draft["id"], payload, preview["record_revision"], event_ids=["other-event"])

    def test_limited_auto_ignores_even_explicitly_selected_private_event_fragments(self):
        exp = self.experience_with_selected_events()
        self.configure("limited_auto", ["experience_active"], 1)
        payload = {"title": "反馈", "description": "说明", "component": "dashboard", "event": "suggestion"}
        draft = self.service.draft(payload, experience_id=exp["id"], event_ids=["one", "two"])
        sent = self.service.send(draft["id"])
        body = sent["preview"]["payload"]["body"]
        self.assertNotIn("selected first fragment", body)
        self.assertNotIn("AI selected second fragment", body)
        self.assertNotIn("Entire private goal", body)

    def test_editing_selected_events_invalidates_previously_approved_body(self):
        exp = self.experience_with_selected_events()
        self.configure()
        payload = {"title": "反馈", "description": "说明", "component": "dashboard", "event": "suggestion"}
        draft = self.service.draft(payload, experience_id=exp["id"], event_ids=["one"])
        approved = self.approve(draft)
        current = self.service.edit(approved["id"], payload, approved["record_revision"], event_ids=["two"])
        self.assertIsNone(current["approval"])
        with self.assertRaises(ValueError):
            self.service.send(current["id"])

    def test_markdown_export_works_without_repository_auth_or_any_network_call(self):
        record = self.draft(description="Email a@example.com; Authorization: Bearer synthetic.secret.payload")
        with patch.object(self.transport, "inspect", side_effect=AssertionError("No network read allowed")), patch.object(self.transport, "create", side_effect=AssertionError("No network write allowed")):
            result = self.service.export(record["id"], "outgoing/feedback.md")
        exported = Path(result["saved_to"]).read_text(encoding="utf-8")
        self.assertFalse(result["sent"])
        self.assertIn("尚未送达", exported)
        self.assertNotIn("a@example.com", exported)
        self.assertNotIn("synthetic.secret", exported)
        self.assertNotIn(record["id"], exported)
        self.assertEqual(record, self.service.show(record["id"]))

    def test_export_refuses_overwrite_authority_private_internals_and_unsafe_paths(self):
        record = self.draft()
        original = self.project / "original.md"
        original.write_text("preserve this author document", encoding="utf-8")
        targets = [original, "state/export.md", ".copilot/export.md", ".git/export.md", self.profile / "export.md",
                   "../outside.md", "bad.txt"]
        for target in targets:
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.service.export(record["id"], target)
        self.assertEqual("preserve this author document", original.read_text(encoding="utf-8"))
        self.assertFalse((self.project / "state").exists())

    def test_cli_exports_a_local_markdown_draft_without_project_state(self):
        record = self.draft()
        args = feedback.parser().parse_args(["--workspace", str(self.project), "--user-data", str(self.profile),
                                            "export", "--id", record["id"], "--output", "feedback.md"])
        result = feedback.execute(args)
        self.assertTrue(Path(result["saved_to"]).is_file())
        self.assertFalse((self.project / "state").exists())

    def test_private_permissions_are_checked_before_the_feedback_lock_creates_directories(self):
        with patch.object(self.service.storage, "prepare_write", side_effect=ValueError("private permissions")), self.assertRaisesRegex(ValueError, "private permissions"):
            self.draft()
        self.assertFalse(self.profile.exists())


class GitHubTransportTests(unittest.TestCase):
    def test_real_adapter_uses_argv_and_body_file_without_shell(self):
        transport = feedback.GitHubTransport()
        payload = {"repository": "owner/repo", "title": "$(not a command) `literal`"}
        with patch.object(feedback.shutil, "which", return_value="gh.exe"), patch.object(feedback.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "https://github.com/owner/repo/issues/7\n", "")
            self.assertEqual("https://github.com/owner/repo/issues/7", transport.create(payload, Path("body file.md")))
            args, kwargs = run.call_args
            self.assertEqual(["gh.exe", "issue", "create", "--repo", "github.com/owner/repo", "--title", payload["title"], "--body-file", "body file.md"], args[0])
            self.assertFalse(kwargs["shell"])
            self.assertEqual("github.com", kwargs["env"]["GH_HOST"])

    def test_auth_and_visibility_are_parsed_from_actual_read_calls(self):
        transport = feedback.GitHubTransport()
        with patch.object(transport, "_run", side_effect=[json.dumps({"login": "actual-user"}), json.dumps({"full_name": "owner/repo", "private": True})]) as run:
            self.assertEqual({"repository": "owner/repo", "account": "actual-user", "visibility": "private"}, transport.inspect("owner/repo"))
            self.assertTrue(all("GET" in call.args for call in run.call_args_list))

    def test_unknown_auth_repo_or_visibility_response_is_rejected(self):
        for result in ({"full_name": "other/repo", "private": True}, {"full_name": "owner/repo", "private": "false"}):
            with self.subTest(result=result), patch.object(feedback.GitHubTransport, "_api", side_effect=[{"login": "user"}, result]), self.assertRaises(feedback.TransportError):
                feedback.GitHubTransport().inspect("owner/repo")

    def test_fake_or_cross_repository_creation_output_is_never_success(self):
        for output in ("Created successfully", "https://github.com/other/repo/issues/1", "https://evil.example/owner/repo/issues/1"):
            with self.subTest(output=output), patch.object(feedback.GitHubTransport, "_run", return_value=output), self.assertRaises(feedback.TransportError):
                feedback.GitHubTransport().create({"repository": "owner/repo", "title": "test"}, Path("body.md"))


if __name__ == "__main__":
    unittest.main()
