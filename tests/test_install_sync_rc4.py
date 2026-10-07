"""Single-entry installation and fail-closed persistence regressions."""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from release_support import inventory, selected_files, verified_runtime_layout
from copilot_store import atomic_write, read_authority_text, Store, IntegrityError
import copilot_host


def tool(name):
    spec = importlib.util.spec_from_file_location("rc4_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallSyncRC4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_fsync_failures_preserve_authority_and_cleanup_temporary_files(self):
        target = self.base / "state.json"
        old = b'{"old":"retained"}\n'
        for number in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EIO, errno.ENOSPC):
            with self.subTest(errno=number):
                target.write_bytes(old)
                with patch("copilot_store.os.fsync", side_effect=OSError(number, "injected")), patch("copilot_store.os.replace") as replace:
                    with self.assertRaises(OSError) as caught:
                        atomic_write(target, {"new": True})
                self.assertEqual(caught.exception.errno, number)
                self.assertIn("未替换原文件", str(caught.exception))
                replace.assert_not_called()
                self.assertEqual(target.read_bytes(), old)
                self.assertEqual(list(self.base.glob("*.tmp")), [])
                self.assertEqual(list(self.base.glob(".*.tmp")), [])

    def test_failed_first_write_creates_no_authority(self):
        target = self.base / "new" / "state.json"
        with patch("copilot_store.os.fsync", side_effect=OSError(errno.ENOTSUP, "injected")):
            with self.assertRaisesRegex(OSError, "不要通过跳过 fsync"):
                atomic_write(target, {"new": True})
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.iterdir()), [])

    def test_successful_sync_still_writes_and_replaces(self):
        target = self.base / "state.json"
        atomic_write(target, {"revision": 1})
        atomic_write(target, {"revision": 2})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"revision": 2})

    def test_windows_transient_read_denial_recovers_current_bytes(self):
        target = Mock()
        target.read_text.side_effect = [PermissionError(errno.EACCES, "sharing"), '{"revision":2}']
        with patch("copilot_store.os.name", "nt"), patch("copilot_store.time.sleep"):
            self.assertEqual(read_authority_text(target), '{"revision":2}')
        self.assertEqual(target.read_text.call_count, 2)

    def test_read_denial_has_deadline_and_preserves_original_error(self):
        target = Mock()
        denied = PermissionError(errno.EACCES, "persistent permission failure")
        target.read_text.side_effect = denied
        with patch("copilot_store.os.name", "nt"), patch("copilot_store.time.sleep"), \
                patch("copilot_store.time.monotonic", side_effect=[0, 0.1, 0.8]):
            with self.assertRaises(PermissionError) as caught:
                read_authority_text(target)
        self.assertIs(caught.exception, denied)
        self.assertEqual(target.read_text.call_count, 2)

    def test_read_does_not_retry_missing_io_or_non_windows_permission_errors(self):
        for system, error in (("nt", FileNotFoundError(errno.ENOENT, "missing")),
                              ("nt", OSError(errno.EIO, "disk failure")),
                              ("posix", PermissionError(errno.EACCES, "permissions"))):
            with self.subTest(system=system, error=type(error).__name__):
                target = Mock(); target.read_text.side_effect = error
                with patch("copilot_store.os.name", system), patch("copilot_store.time.sleep") as sleep:
                    with self.assertRaises(type(error)) as caught:
                        read_authority_text(target)
                self.assertIs(caught.exception, error)
                target.read_text.assert_called_once()
                sleep.assert_not_called()

    def test_recovered_read_still_rejects_corrupt_authority(self):
        target = self.base / "project/state/decision_log.json"
        store = Store(target)
        template = json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        state = store.create(template)
        state['copilot']['state_hash'] = 'forged'
        for invalid, error in ((json.dumps(state), IntegrityError), ('{invalid', json.JSONDecodeError)):
            with patch("copilot_store.read_authority_text", return_value=invalid) as read:
                with self.assertRaises(error):
                    store.read()
            read.assert_called_once_with(store.path)
        self.assertNotEqual(store.read()['copilot']['state_hash'], 'forged')

    def test_host_probe_reports_sync_failure_without_crash_or_available_claim(self):
        with patch("copilot_host.os.fsync", side_effect=OSError(errno.ENOTSUP, "injected")):
            report = copilot_host.probe(self.base)
        capability = report["capabilities"]["write_files"]
        self.assertEqual(capability["status"], "unavailable")
        evidence = capability["evidence"][0]
        self.assertEqual(evidence["operation"], "file_sync")
        self.assertEqual(evidence["errno"], errno.ENOTSUP)
        self.assertFalse(evidence["ok"])
        self.assertIn("本地可写目录", evidence["reason"])
        self.assertEqual(list(self.base.iterdir()), [])

    def test_runtime_installs_once_and_explicit_alias_is_separate(self):
        installer = tool("install_skill")
        root = Path(installer.install(self.base / "default")["installation"])
        self.assertTrue(verified_runtime_layout(root))
        self.assertEqual([p.relative_to(root).as_posix() for p in root.rglob("SKILL.md")], ["SKILL.md"])
        # Runtime distributions can install their optional alias without the
        # original source-only compat directory.
        with patch.object(installer, "ROOT", root):
            result = installer.install(self.base / "opt-in", legacy_alias=True)
        self.assertEqual(len(list((self.base / "opt-in").rglob("SKILL.md"))), 2)
        self.assertIn("../mathmodel-copilot/SKILL.md", (Path(result["legacy_alias"]) / "SKILL.md").read_text(encoding="utf-8"))

    def test_runtime_marker_cannot_hide_changed_missing_or_extra_discovery_files(self):
        installer = tool("install_skill")
        for mode in ("missing-marker", "changed-file", "extra-entry", "forged-marker", "wrong-marker-type"):
            with self.subTest(mode=mode):
                root = Path(installer.install(self.base / mode)["installation"])
                if mode == "missing-marker":
                    (root / "INSTALL_MANIFEST.json").unlink()
                elif mode == "changed-file":
                    (root / "SKILL.md").write_text("broken", encoding="utf-8")
                elif mode == "extra-entry":
                    (root / "extra").mkdir()
                    (root / "extra/SKILL.md").write_text("extra", encoding="utf-8")
                elif mode == "wrong-marker-type":
                    (root / "INSTALL_MANIFEST.json").write_text("[]", encoding="utf-8")
                else:
                    (root / "INSTALL_MANIFEST.json").write_text('{"distribution_profile":"runtime","files":[]}', encoding="utf-8")
                self.assertFalse(verified_runtime_layout(root))

    def test_doctor_missing_yaml_is_reported_as_dependency_not_corrupt_metadata(self):
        result = subprocess.run([sys.executable, "-B", "-S", str(ROOT / "scripts/doctor.py"),
                                 "--competition", "mcm", "--skip-tools", "--json"],
                                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 1)
        checks = {item["name"]: item for item in json.loads(result.stdout)}
        self.assertEqual(checks["frontmatter-dependency"]["status"], "fail")
        self.assertIn("依赖缺失", checks["frontmatter-dependency"]["detail"])
        self.assertIn("未验证", checks["skill-metadata"]["detail"])

    def test_runtime_pack_preserves_resources_licenses_utf8_and_only_one_entry(self):
        builder, verifier = tool("build_release"), tool("verify_install")
        # Freeze this test's input so another independent maintainer edit does
        # not masquerade as a source-changed-during-packaging failure.
        frozen = self.base / "source"
        for relative in selected_files(ROOT):
            target = frozen / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        with patch.object(builder, "ROOT", frozen):
            result = builder.build(self.base / "runtime", profile="runtime")
            source_result = builder.build(self.base / "full-source", profile="source")
        archive_path = self.base / "runtime" / result["archive"]
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.namelist()
            self.assertEqual([n for n in entries if n.endswith("/SKILL.md")], ["mathmodel-copilot/SKILL.md"])
            for name in ("LICENSE", "LICENSE_SCOPE.md", "THIRD_PARTY_NOTICES.md", "scripts/copilot.py",
                         "docs/SECTION_V012.md", "references/copilot_runtime.md", "dashboard/index.html",
                         "examples/mcm2009a/run_example.py", "templates/shared/decision_log.json"):
                self.assertIn("mathmodel-copilot/" + name, entries)
            self.assertFalse(any(n.startswith("mathmodel-copilot/tests/") for n in entries))
            chinese = archive.getinfo("mathmodel-copilot/内测使用说明.md")
            self.assertTrue(chinese.flag_bits & 0x800)
        extracted, manifest = verifier.unpack_review(archive_path, self.base / "unpack")
        self.assertEqual(manifest["distribution_profile"], "runtime")
        self.assertTrue(verified_runtime_layout(extracted))
        self.assertEqual(inventory(extracted), manifest["files"])
        with zipfile.ZipFile(self.base / "full-source" / source_result["archive"]) as archive:
            self.assertIn("mathmodel-copilot/compat/mathmodel-skill/SKILL.md", archive.namelist())
            self.assertIn("mathmodel-copilot/skills/mathmodel-copilot/SKILL.md", archive.namelist())
        # The user-facing installation path must work from the actual ZIP.
        result = subprocess.run([sys.executable, "-B", str(extracted / "scripts/doctor.py"), "--competition", "mcm", "--skip-tools"],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
