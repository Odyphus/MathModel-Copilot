"""Teaching is available without a project; read endpoints never grant writes."""
import copy
import hashlib
import http.client
import json
import os
import socket
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_dashboard import make_server
from copilot_tutorial import catalog, lesson


class TutorialTests(unittest.TestCase):
    def test_complete_public_catalog_and_single_lessons(self):
        value = catalog()
        topics = [row["topic"] for row in value["features"]]
        self.assertEqual(len(topics), len(set(topics)))
        self.assertEqual(set(topics), {"start", "problem", "models", "runs", "evidence", "workbench",
                                      "paper", "handoff", "rules", "recap", "experience", "feedback"})
        self.assertEqual(len(lesson()["sections"]), len(topics))
        for row in value["features"]:
            self.assertTrue(all(row[key] for key in ("title", "purpose", "when_to_use", "prompt", "entry", "status", "limits")))
            single = lesson(row["topic"])
            self.assertTrue(single["read_only"])
            self.assertEqual(len(single["sections"]), 1)
            self.assertGreaterEqual(len(single["sections"][0]["steps"]), 3)
            self.assertIn("核对当前项目状态", single["exit_prompt"])

    def test_requests_are_static_guidance_and_keep_professional_terms(self):
        source = json.dumps(lesson(), ensure_ascii=False)
        for word in ("线性规划", "MILP", "有限体积法", "实际运行", "接收", "采用", "核验", "人主导"):
            self.assertIn(word, source)
        self.assertIn("不会唤醒 AI", json.dumps(catalog(), ensure_ascii=False))
        self.assertIn("不要发送", lesson("feedback")["sections"][0]["prompt"])
        self.assertIn("不要新增对话留存", lesson("recap")["sections"][0]["prompt"])

    def test_unknown_topics_and_paths_fail_instead_of_becoming_file_reads(self):
        for topic in (None, "", "../private", "C:/private.json", "all&path=x", [], {}):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                lesson(topic)

    def test_catalog_and_lesson_are_fresh_copies(self):
        first = catalog()
        first["features"][0]["title"] = "forged"
        self.assertNotEqual(catalog()["features"][0]["title"], "forged")
        first = lesson("models")
        first["sections"][0]["steps"].clear()
        self.assertTrue(lesson("models")["sections"][0]["steps"])


class TutorialHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.workspace = self.base / "uninitialized-project"
        self.personal = self.base / "isolated-profile"
        env = patch.dict(os.environ, {"MATHMODEL_COPILOT_DATA_DIR": str(self.personal)})
        env.start()
        self.addCleanup(env.stop)
        self.server = make_server(self.workspace)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method="GET", headers=None, read_header=True):
        con = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(con.close)
        con.request(method, path, headers={**({"X-Copilot-Read": "1"} if read_header else {}), **(headers or {})})
        response = con.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data

    def test_help_available_before_initialization_without_any_personal_write(self):
        for path in ("/api/tutorial", "/api/tutorial?topic=all", "/api/tutorial?topic=models"):
            code, headers, raw = self.request(path)
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(raw)["result"]["read_only"])
            self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.personal.exists())

    def test_static_resource_burst_survives_a_delayed_accept_loop(self):
        server = make_server(self.workspace, port=0)
        clients = []; thread = None
        try:
            # A page has six independent JS/CSS files plus concurrent reads.
            # Accept is deliberately delayed to reproduce the old backlog loss.
            for _ in range(8):
                clients.append(socket.create_connection(server.server_address, timeout=1))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            for client in clients:
                client.settimeout(5)
                con = http.client.HTTPConnection(*server.server_address, timeout=5); con.sock = client
                con.request("GET", "/help.js")
                response = con.getresponse(); body = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn(b"createController", body)
                con.close()
        finally:
            for client in clients: client.close()
            if thread is not None: server.shutdown(); thread.join(2)
            server.server_close()
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.personal.exists())

    def test_recap_only_calls_current_workspace_without_paths_or_other_bindings(self):
        overview = Mock(return_value={"enabled": True, "recap": None, "notice": "尚未保存本项目复盘"})
        with patch.dict(sys.modules, {"copilot_recap": types.SimpleNamespace(overview=overview)}):
            code, _, raw = self.request("/api/recap")
        self.assertEqual(code, 200)
        overview.assert_called_once_with(self.workspace.resolve())
        self.assertIsNone(json.loads(raw)["result"]["recap"])
        self.assertNotIn(str(self.base), raw.decode())
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.personal.exists())

    def test_recap_rejects_all_query_parameters_before_personal_read(self):
        overview = Mock(side_effect=AssertionError("must not read"))
        with patch.dict(sys.modules, {"copilot_recap": types.SimpleNamespace(overview=overview)}):
            for query in ("path=secret.json", "user_data=C:/other", "workspace=other", "binding=other", "topic=all", "path=", "unused"):
                self.assertEqual(self.request("/api/recap?" + query)[0], 400)
        overview.assert_not_called()

    def test_tutorial_rejects_duplicate_blank_unknown_and_path_parameters(self):
        for query in ("topic=all&topic=start", "topic=", "topic=unknown", "path=README.md", "topic=all&path=x", "topic=../private", "unused"):
            self.assertEqual(self.request("/api/tutorial?" + query)[0], 400)

    def test_new_apis_keep_local_origin_and_read_header_protection(self):
        for path in ("/api/tutorial", "/api/recap"):
            self.assertEqual(self.request(path, read_header=False)[0], 403)
            self.assertEqual(self.request(path, headers={"Origin": "https://untrusted.example"})[0], 403)
            self.assertEqual(self.request(path, headers={"Host": "untrusted.example"})[0], 403)

    def test_teaching_and_recap_have_no_write_route(self):
        for path in ("/api/tutorial", "/api/recap"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertEqual(self.request(path, method=method)[0], 405)
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.personal.exists())

    def test_static_help_asset_and_markup_preserve_four_navigation_design(self):
        code, _, raw = self.request("/help.js")
        self.assertEqual(code, 200)
        self.assertIn("页面没有启动 AI", raw.decode("utf-8"))
        code, _, raw = self.request("/")
        self.assertEqual(code, 200)
        text = raw.decode("utf-8")
        self.assertIn('id="help-link"', text)
        self.assertIn('id="help-dialog"', text)
        self.assertIn('id="navigation"', text)
        self.assertIn('id="interaction"', text)
        self.assertEqual(self.request("/help.js?path=private")[0], 404)

    def test_corrupt_personal_data_is_not_echoed_as_html_or_raw_server_error(self):
        overview = Mock(side_effect=ValueError("C:/private-user/secret.json corrupted"))
        with patch.dict(sys.modules, {"copilot_recap": types.SimpleNamespace(overview=overview)}):
            code, _, raw = self.request("/api/recap")
        self.assertEqual(code, 400)
        self.assertNotIn(b"private-user", raw)


if __name__ == "__main__":
    unittest.main()
