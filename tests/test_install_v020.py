"""Observable packaging boundaries; original regression files are untouched."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_support import selected_files, scan, inventory_sha256, PRIVATE_PATH

spec = importlib.util.spec_from_file_location("install_skill_v020", ROOT / "tools/install_skill.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

spec = importlib.util.spec_from_file_location("verify_install_v020", ROOT / "tools/verify_install.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class InstallationV020Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-B", "-S", "-m", "mathmodel_copilot", *map(str, args)],
                              cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_standard_library_entrypoint_creates_and_resumes_without_rewriting(self):
        project = self.root / "project"
        result = self.invoke("--workspace", project, "init", "--competition", "mcm")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        authority = project / "state/decision_log.json"
        before = authority.read_bytes()
        self.assertEqual(self.invoke("--workspace", project, "init", "--competition", "mcm").returncode, 0)
        status = self.invoke("--workspace", project, "status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(authority.read_bytes(), before)
        self.assertFalse(json.loads(status.stdout)["result"]["submission"]["ready"])

    def test_allowlist_preserves_resources_and_excludes_official_assets(self):
        names = {path.as_posix() for path in selected_files(ROOT, payload=True)}
        for name in ("scripts/copilot.py", "competitions/cumcm/pack.json", "templates/shared/decision_log.json",
                     "references/copilot_runtime.md", "dashboard/index.html", "examples/mcm2009a/run_example.py",
                     "DESIGN.md", ".impeccable/design.json"):
            self.assertIn(name, names)
        self.assertFalse(any("examples/cumcm2018b/assets/" in name for name in names))
        self.assertNotIn("assets/status-demo.svg", names)
        self.assertFalse(any(name.startswith(("state/", "cases/", "work/", "outputs/")) for name in names))

    def test_candidate_has_no_personal_paths_or_credentials(self):
        self.assertEqual(scan(ROOT), [])

    def test_manifest_order_is_portable_between_windows_and_linux(self):
        names = [path.as_posix() for path in selected_files(ROOT)]
        self.assertEqual(names, sorted(names))

    def test_privacy_scan_detects_real_paths_without_matching_its_rule(self):
        for value in ("/".join(("", "home", "reviewer", "private.txt")),
                      "/".join(("", "Users", "reviewer", "private.txt")),
                      "\\".join(("C:", "Users", "reviewer", "private.txt"))):
            self.assertIsNotNone(PRIVATE_PATH.search(value))
        self.assertIsNone(PRIVATE_PATH.search((ROOT / "release_support.py").read_text(encoding="utf-8")))

    def test_review_zip_verifies_exact_members_and_rejects_tampering(self):
        payload = b"review source\n"
        files = [{"path": "README.md", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]
        manifest = {"schema": "mathmodel-copilot.review-manifest/v1", "files": files,
                    "source_manifest_sha256": inventory_sha256(files)}
        for mode in ("valid", "changed", "missing", "extra", "traversal"):
            archive_path = self.root / (mode + ".zip")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("mathmodel-copilot/RELEASE_MANIFEST.json", json.dumps(manifest))
                if mode != "missing":
                    archive.writestr("mathmodel-copilot/README.md", b"tampered\n" if mode == "changed" else payload)
                if mode == "extra":
                    archive.writestr("mathmodel-copilot/unlisted.txt", b"unexpected")
                if mode == "traversal":
                    archive.writestr("mathmodel-copilot/../escape.txt", b"escape")
            target = self.root / (mode + "-unpack")
            if mode == "valid":
                source, _ = verifier.unpack_review(archive_path, target)
                self.assertEqual((source / "README.md").read_bytes(), payload)
            else:
                with self.assertRaises(ValueError):
                    verifier.unpack_review(archive_path, target)
                self.assertFalse(target.exists())

    def test_default_discovery_name_does_not_install_legacy_alias(self):
        result = installer.install(self.root / "skills")
        self.assertIsNone(result["legacy_alias"])
        destination = Path(result["installation"])
        self.assertTrue((destination / "SKILL.md").is_file())
        self.assertEqual([p.relative_to(destination).as_posix() for p in destination.rglob("SKILL.md")], ["SKILL.md"])
        self.assertFalse((self.root / "skills/mathmodel-skill").exists())
        with self.assertRaises(FileExistsError):
            installer.install(self.root / "skills")

    def test_installed_doctor_checks_new_primary_discovery(self):
        destination = Path(installer.install(self.root / "skills")["installation"])
        result = subprocess.run([sys.executable, "-B", str(destination / "scripts/doctor.py"),
                                 "--competition", "mcm", "--skip-tools", "--json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata = next(x for x in json.loads(result.stdout) if x["name"] == "skill-metadata")
        self.assertEqual(metadata["status"], "pass")
        self.assertIn("mathmodel-copilot", metadata["detail"])

    def test_legacy_alias_cannot_mask_broken_primary_discovery(self):
        for broken in ("shim", "plugin"):
            with self.subTest(broken=broken):
                # Plugin validation belongs to full source distributions;
                # default user installations intentionally have no plugin shim.
                destination = self.root / broken
                for relative in selected_files(ROOT):
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / relative, target)
                legacy = destination / "skills/mathmodel-skill/SKILL.md"
                legacy.parent.mkdir(parents=True)
                legacy.write_text("---\nname: mathmodel-skill\n---\nLegacy alias only\n", encoding="utf-8")
                if broken == "shim":
                    (destination / "skills/mathmodel-copilot/SKILL.md").write_text(
                        "---\nname: mathmodel-skill\n---\nWrong discovery name\n", encoding="utf-8")
                else:
                    plugin_path = destination / ".codex-plugin/plugin.json"
                    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
                    plugin["name"] = "mathmodel-skill"
                    plugin_path.write_text(json.dumps(plugin), encoding="utf-8")
                result = subprocess.run([sys.executable, "-B", str(destination / "scripts/doctor.py"),
                                         "--competition", "mcm", "--skip-tools", "--json"],
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                metadata = next(x for x in json.loads(result.stdout) if x["name"] == "skill-metadata")
                self.assertEqual(metadata["status"], "fail")

    def test_legacy_alias_is_explicit_and_upstream_collision_prevents_all_writes(self):
        directory = self.root / "skills"
        upstream = directory / "mathmodel-skill"
        upstream.mkdir(parents=True)
        marker = upstream / "SKILL.md"
        marker.write_bytes(b"original upstream installation")
        with self.assertRaises(FileExistsError):
            installer.install(directory, legacy_alias=True)
        self.assertEqual(marker.read_bytes(), b"original upstream installation")
        self.assertFalse((directory / "mathmodel-copilot").exists())
        selected = installer.install(self.root / "opt-in", legacy_alias=True)
        self.assertIn("../mathmodel-copilot/SKILL.md", (Path(selected["legacy_alias"]) / "SKILL.md").read_text(encoding="utf-8"))

    def test_release_metadata_does_not_invent_a_publisher_or_license(self):
        metadata = json.loads((ROOT / "RELEASE_METADATA.json").read_text(encoding="utf-8"))
        plugin = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertFalse(metadata["public_release_allowed"])
        self.assertEqual(metadata["maintainer"], "Odyphus")
        self.assertEqual(metadata["repository"], "https://github.com/Odyphus/MathModel-Copilot")
        self.assertEqual(metadata["repository_visibility"], "public")
        self.assertTrue(metadata["published"])
        self.assertEqual(metadata["status"], "public_github_preview")
        self.assertEqual(metadata["distribution_scope"], "public_github_preview")
        self.assertNotIn("author", plugin)
        self.assertEqual(plugin["name"], "mathmodel-copilot")
        self.assertFalse((ROOT / "skills/mathmodel-skill/SKILL.md").exists())

    def test_public_mode_refuses_before_creating_archive(self):
        destination = self.root / "release"
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build_release.py"), "--public", "--output", str(destination)],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("blocked", result.stderr)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
