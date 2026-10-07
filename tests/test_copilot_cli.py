from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/copilot.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, "-B", str(CLI), "--workspace", str(self.root), *args],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def test_new_process_recovers_and_read_commands_are_read_only(self):
        self.call("init", "--competition", "generic")
        self.write("config.json", {"question_count": 3, "problem_year": 2018, "rules_year": 2026, "evaluation_mode": "historical_benchmark"})
        self.call("configure", "--expected-revision", "0", "--payload", "config.json")
        state = self.root / "state/decision_log.json"
        before = state.read_bytes()
        for role in ("modeler", "coder", "writer"):
            context = self.call("context", "--role", role)["result"]
            self.assertEqual(context["source_revision"], 1)
            self.assertEqual(context["common"]["requirements"]["questions"], {"Q1":"missing", "Q2":"missing", "Q3":"missing"})
        result = self.call("status")["result"]
        self.assertFalse(result["submission"]["ready"])
        self.assertEqual(state.read_bytes(), before)

    def test_conflict_and_resume_never_replace_authority(self):
        self.call("init", "--competition", "cumcm")
        self.write("config.json", {"stage": 3})
        self.call("configure", "--expected-revision", "0", "--payload", "config.json")
        state = self.root / "state/decision_log.json"
        before = state.read_bytes()
        self.assertEqual(self.call("configure", "--expected-revision", "0", "--payload", "config.json", code=3)["error"], "ConflictError")
        self.assertEqual(self.call("init", "--competition", "cumcm")["result"]["action"], "resumed")
        self.assertEqual(state.read_bytes(), before)

    def test_context_export_is_create_only_and_paths_confined(self):
        self.call("init")
        self.call("context", "--role", "writer", "--output", "contexts/writer.json")
        target = self.root / "contexts/writer.json"
        before = target.read_bytes()
        self.call("context", "--role", "coder", "--output", "contexts/writer.json", code=2)
        self.call("context", "--role", "coder", "--output", "../outside.json", code=2)
        self.assertEqual(target.read_bytes(), before)

    def test_external_state_edit_produces_integrity_error(self):
        self.call("init")
        state = self.root / "state/decision_log.json"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["current_stage"] = 9
        state.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.call("status", code=4)["error"], "IntegrityError")


if __name__ == "__main__": unittest.main()
