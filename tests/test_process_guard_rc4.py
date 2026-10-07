"""Real, short-lived process families; no AI, accounts or network requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_process as guard_module


class ProcessGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.outputs = []
        self.child = self.root / "descendant.py"
        self.child.write_text(
            "import pathlib,sys,time\n"
            "pathlib.Path(sys.argv[1]).write_text('ready')\n"
            "time.sleep(float(sys.argv[3]))\n"
            "pathlib.Path(sys.argv[2]).write_text('survived')\n", encoding="utf-8")
        self.parent = self.root / "entry.py"
        self.parent.write_text(
            "import pathlib,subprocess,sys,time\n"
            "child=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            "deadline=time.monotonic()+5\n"
            "while not pathlib.Path(sys.argv[2]).exists():\n"
            " if time.monotonic()>deadline: raise RuntimeError('child never ready')\n"
            " time.sleep(0.01)\n"
            "time.sleep(float(sys.argv[5]))\n", encoding="utf-8")

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), "Fixture did not start: " + str(path))

    def family(self, name="guarded", *, entry_delay=0, child_delay=1):
        ready, marker = self.root / (name + ".ready"), self.root / (name + ".marker")
        argv = [sys.executable, str(self.parent), str(self.child), str(ready), str(marker),
                str(child_delay), str(entry_delay)]
        return argv, ready, marker

    def spawn(self, argv):
        output, errors = tempfile.TemporaryFile(), tempfile.TemporaryFile()
        self.addCleanup(output.close)
        self.addCleanup(errors.close)
        guard = guard_module.spawn(argv, cwd=self.root, stdin=subprocess.PIPE, stdout=output, stderr=errors)
        self.addCleanup(guard.process.stdin.close)
        self.addCleanup(guard.close)
        self.outputs.append((output, errors))
        return guard

    def test_binary_stdio_exit_status_and_repeat_close(self):
        guard = self.spawn([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stderr.write('diagnostic'); sys.exit(7)"])
        guard.process.communicate("中文\n".encode("utf-8"), timeout=10)
        self.assertEqual(guard.process.returncode, 7)
        output, errors = self.outputs[-1]
        output.seek(0); errors.seek(0)
        self.assertEqual(output.read(), "中文\n".encode("utf-8"))
        self.assertEqual(errors.read(), b"diagnostic")
        guard.close()
        guard.close()

    def test_unprotected_fixture_proves_orphan_can_outlive_entry(self):
        argv, ready, marker = self.family("baseline", child_delay=0.5)
        entry = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(entry.wait(timeout=6), 0)
        self.wait_file(ready)
        self.wait_file(marker)

    def test_closing_after_entry_exit_stops_orphan_descendant(self):
        argv, ready, marker = self.family()
        guard = self.spawn(argv)
        self.assertEqual(guard.process.wait(timeout=6), 0)
        self.assertTrue(ready.exists())
        self.assertFalse(marker.exists())
        guard.close()
        guard.close()
        time.sleep(1.15)
        self.assertFalse(marker.exists(), "Orphan descendant survived closing its guard")

    def test_cancel_stops_live_family_and_preserves_unrelated_process(self):
        ready, marker = self.root / "unrelated.ready", self.root / "unrelated.marker"
        unrelated = subprocess.Popen([sys.executable, str(self.child), str(ready), str(marker), "0.6"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            argv, own_ready, own_marker = self.family("cancelled", entry_delay=3)
            guard = self.spawn(argv)
            self.wait_file(own_ready)
            guard.close()
            self.assertIsNotNone(guard.process.poll())
            self.assertEqual(unrelated.wait(timeout=5), 0)
            self.assertTrue(marker.exists(), "Unrelated process was affected")
            time.sleep(0.7)
            self.assertFalse(own_marker.exists())
        finally:
            if unrelated.poll() is None:
                unrelated.kill()
                unrelated.wait(timeout=5)

    def test_timeout_cleanup_stops_family(self):
        argv, ready, marker = self.family("timeout", entry_delay=3)
        guard = self.spawn(argv)
        self.wait_file(ready)
        with self.assertRaises(subprocess.TimeoutExpired):
            guard.process.wait(timeout=0.05)
        guard.close()
        time.sleep(1.1)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job creation negative case")
    def test_job_creation_failure_never_launches_unguarded_process(self):
        with patch.object(guard_module, "_WindowsJob", side_effect=OSError("injected job restriction")), \
                patch.object(guard_module.subprocess, "Popen") as launch:
            with self.assertRaises(OSError):
                guard_module.spawn([sys.executable, "-c", "pass"], cwd=self.root,
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        launch.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows Job assignment negative case")
    def test_invalid_job_assignment_never_launches_cli(self):
        marker = self.root / "must-not-launch.marker"
        command = [sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('bad')", str(marker)]
        result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/copilot_process.py"),
                                 "_job-wrapper", "0", json.dumps(command)],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 125, result.stderr)
        self.assertIn(b"Process guard unavailable", result.stderr)
        self.assertFalse(marker.exists())

    def test_spawn_rejects_shell_string(self):
        with self.assertRaises(ValueError):
            guard_module.spawn("echo no shell", cwd=self.root, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
