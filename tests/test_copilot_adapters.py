"""Host and pack acceptance tests: actual I/O plus fail-closed rule snapshots."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_host as host
import copilot_packs as packs
from copilot_domain import seal_record, sha256_file


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_actual_python_and_file_probes_leave_authority_unchanged(self):
        authority = self.root / "decision_log.json"
        authority.write_text('{"sentinel":"must remain unchanged"}', encoding="utf-8")
        before = authority.read_bytes()
        report = host.probe(self.root)
        self.assertEqual(host.require(report, ["read_files", "write_files", "execute_python"]), [])
        self.assertEqual(before, authority.read_bytes())
        self.assertEqual([p.name for p in self.root.iterdir()], ["decision_log.json"])
        evidence = report["capabilities"]["execute_python"]["evidence"][0]
        self.assertEqual(evidence["exit_code"], 0)
        self.assertTrue(evidence["python_version"])

    def test_network_word_matlab_and_parallel_agents_remain_unknown(self):
        with mock.patch.dict(os.environ, {"MATLAB_INSTALLED": "1", "CODEX_PARALLEL": "1", "WORD_INSTALLED": "1"}):
            report = host.probe(self.root)
        for name in ("network", "word", "matlab", "parallel_agents"):
            self.assertEqual(report["capabilities"][name]["status"], "unknown")
            self.assertTrue(host.require(report, [name]))

    def test_available_without_execution_evidence_does_not_pass(self):
        self.assertTrue(host.require({"word": {"status": "available", "evidence": [{"installed": True}]}}, ["word"]))

    def test_unknown_name_and_unavailable_workspace_block(self):
        report = host.probe(self.root / "missing")
        self.assertTrue(host.require(report, ["execute_python"]))
        self.assertTrue(host.require(report, ["remote_gpu"]))
        self.assertTrue(host.require(report, "execute_python"))

    def test_python_execution_failure_not_hidden_by_working_file_io(self):
        with mock.patch("copilot_host.subprocess.run", side_effect=PermissionError("execution denied")):
            report = host.probe(self.root)
        self.assertEqual(report["capabilities"]["execute_python"]["status"], "unavailable")
        self.assertEqual(host.require(report, ["write_files", "read_files"]), [])
        self.assertTrue(host.require(report, ["execute_python"]))

    def test_python_timeout_is_unavailable(self):
        with mock.patch("copilot_host.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 5)):
            report = host.probe(self.root)
        self.assertEqual(report["capabilities"]["execute_python"]["status"], "unavailable")


class PackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = packs.load_pack("cumcm")

    def snapshots(self, pack=None):
        pack = pack or self.pack
        records = []
        for item in pack["official_sources"]:
            path = self.root / "rules" / (item["id"] + ".txt")
            path.parent.mkdir(exist_ok=True)
            path.write_text("UNIT TEST SNAPSHOT, NOT AN OFFICIAL RULE DOCUMENT\n" + item["url"], encoding="utf-8")
            records.append({"url": item["url"], "path": path.relative_to(self.root).as_posix(),
                            "sha256": sha256_file(path), "verified_at": "2026-10-05"})
        return records

    def lock(self, pack=None, snapshots=None, **kwargs):
        pack = pack or self.pack
        options = dict(problem_year=pack["rules_year"], rules_year=pack["rules_year"],
                       evaluation_mode="formal_contest", reviewer="qa_fixture", workspace=self.root)
        options.update(kwargs)
        return packs.build_rules_lock(pack, source_snapshots=self.snapshots(pack) if snapshots is None else snapshots, **options)

    def custom_pack(self):
        path = self.root / "competition" / "pack.json"
        path.parent.mkdir()
        generic = {k: v for k, v in packs.load_pack("generic").items() if not k.startswith("_")}
        generic.update(id="university", name="Local contest", aliases=[], rules_year=2026,
                       rules_status="baseline", resources={},
                       official_sources=[{"id": "regulations", "url": "https://example.edu/contest/rules-2026",
                                          "origin": "official_rule", "rules_year": 2026,
                                          "required_for_lock": True, "checked_at": "2026-10-05"}])
        path.write_text(json.dumps(generic), encoding="utf-8")
        return packs.load_pack(path)

    def test_original_three_packs_and_generic_validate(self):
        for name in ("cumcm", "mcm", "diangong", "generic"):
            with self.subTest(name=name):
                self.assertEqual(packs.validate_pack(packs.load_pack(name)), [])

    def test_mcm_icm_alias_and_custom_alias(self):
        self.assertEqual(packs.load_pack("mcm-icm")["id"], "mcm")
        self.assertEqual(packs.load_pack("icm")["id"], "mcm")
        self.assertEqual(packs.load_pack("custom")["id"], "generic")

    def test_generic_cannot_claim_verified_rules(self):
        generic = packs.load_pack("generic")
        generic["verified"] = True
        with self.assertRaises(ValueError):
            self.lock(generic, [], problem_year=2026, rules_year=2026)
        self.assertTrue(packs.verify_rules_lock(self.root, {"verified": True}))

    def test_valid_lock_is_sealed_and_checks_actual_files(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        records = self.snapshots()
        populated = sorted(str(p) for p in self.root.rglob("*"))
        lock = self.lock(snapshots=records)
        self.assertEqual(packs.verify_rules_lock(self.root, lock), [])
        self.assertIn("record_hash", lock)
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), populated)
        self.assertNotEqual(before, populated)  # Only the fixture helper wrote files.

    def test_formal_year_mixing_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "matching problem_year"):
            self.lock(problem_year=2018)

    def test_historical_mode_records_distinct_problem_and_rules_years(self):
        lock = self.lock(problem_year=2018, evaluation_mode="historical_benchmark")
        self.assertEqual((lock["problem_year"], lock["rules_year"]), (2018, 2026))
        self.assertEqual(packs.verify_rules_lock(self.root, lock), [])

    def test_pack_year_mismatch_cannot_be_excused_by_benchmark(self):
        with self.assertRaisesRegex(ValueError, "loaded pack baseline"):
            self.lock(rules_year=2025, evaluation_mode="historical_benchmark")

    def test_unknown_mode_and_boolean_year_rejected(self):
        for options in ({"evaluation_mode": "guess"}, {"rules_year": True}, {"problem_year": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.lock(**options)

    def test_missing_required_source_and_empty_snapshots_rejected(self):
        snapshots = self.snapshots()
        for records in ([], snapshots[:1]):
            with self.subTest(count=len(records)), self.assertRaises(ValueError):
                self.lock(snapshots=records)

    def test_fake_hash_and_missing_hash_rejected(self):
        for value in ("0" * 64, None, "verified"):
            records = self.snapshots()
            records[0]["sha256"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.lock(snapshots=records)

    def test_unknown_source_and_duplicate_source_rejected(self):
        records = self.snapshots()
        records[0]["url"] = "https://example.com/fake"
        with self.assertRaises(ValueError):
            self.lock(snapshots=records)
        records = self.snapshots()
        with self.assertRaises(ValueError):
            self.lock(snapshots=records + [records[0]])

    def test_source_year_mismatch_rejected(self):
        records = self.snapshots()
        records[0]["rules_year"] = 2025
        with self.assertRaisesRegex(ValueError, "Snapshot rules_year"):
            self.lock(snapshots=records)

    def test_missing_reviewer_or_future_review_date_rejected(self):
        with self.assertRaises(ValueError):
            self.lock(reviewer=" ")
        records = self.snapshots()
        records[0]["verified_at"] = "2200-01-01"
        with self.assertRaises(ValueError):
            self.lock(snapshots=records)

    def test_parent_traversal_and_absolute_outside_rejected(self):
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(outside.unlink)
        for path in ("../" + outside.name, str(outside)):
            records = self.snapshots()
            records[0].update(path=path, sha256=sha256_file(outside))
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.lock(snapshots=records)

    def test_deleted_and_changed_snapshot_break_lock(self):
        records = self.snapshots()
        lock = self.lock(snapshots=records)
        path = self.root / records[0]["path"]
        path.write_text("changed", encoding="utf-8")
        self.assertTrue(packs.verify_rules_lock(self.root, lock))
        path.unlink()
        self.assertTrue(packs.verify_rules_lock(self.root, lock))

    def test_unsealed_and_resealed_wrong_pack_hash_rejected(self):
        lock = self.lock()
        broken = copy.deepcopy(lock)
        broken["pack_sha256"] = "0" * 64
        self.assertTrue(packs.verify_rules_lock(self.root, broken))
        self.assertTrue(packs.verify_rules_lock(self.root, seal_record(broken)))

    def test_custom_manifest_has_no_core_competition_enum(self):
        custom = self.custom_pack()
        lock = self.lock(custom)
        self.assertEqual(lock["pack_locator"]["kind"], "workspace")
        self.assertEqual(packs.verify_rules_lock(self.root, lock), [])
        Path(custom["_pack_path"]).write_text("{}", encoding="utf-8")
        self.assertTrue(packs.verify_rules_lock(self.root, lock))

    def test_resealed_installed_locator_cannot_smuggle_an_explicit_path(self):
        custom = self.custom_pack()
        lock = self.lock(custom)
        lock["pack_locator"] = {"kind": "installed", "id": custom["_pack_path"]}
        self.assertTrue(packs.verify_rules_lock(self.root, seal_record(lock)))

    def test_changed_pack_resource_invalidates_lock(self):
        custom = self.custom_pack()
        manifest = Path(custom["_pack_path"])
        resource = manifest.parent / "rules.md"
        resource.write_text("original guide", encoding="utf-8")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["resources"] = {"guide": "rules.md"}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        custom = packs.load_pack(manifest)
        lock = self.lock(custom)
        resource.write_text("changed guide", encoding="utf-8")
        self.assertIn("Pack resource files changed", packs.verify_rules_lock(self.root, lock))

    def test_in_memory_pack_edits_cannot_bypass_real_manifest(self):
        self.pack["rules"]["main_text_max_pages"]["value"] = 1000
        with self.assertRaisesRegex(ValueError, "Pack changed"):
            self.lock()

    def test_pack_resource_escape_and_malformed_provenance_rejected(self):
        for update in ({"resources": {"bad": "../secret"}}, {"resources": {"bad": "C:/secret"}},
                       {"rules_status": {}}, {"rules": {"fake": {"value": 25, "origin": "official_rule", "source_ids": []}}}):
            pack = copy.deepcopy(self.pack)
            pack.update(update)
            with self.subTest(update=update):
                self.assertTrue(packs.validate_pack(pack))

    def test_malformed_lock_returns_errors_not_unhandled_exception(self):
        for value in (None, [], {}, {"pack_locator": []}, {"evaluation_mode": {}}):
            with self.subTest(value=value):
                self.assertTrue(packs.verify_rules_lock(self.root, value))


if __name__ == "__main__":
    unittest.main()
