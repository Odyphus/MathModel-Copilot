"""Fresh per-observation dependency checks, with real bound file reads.

These are synthetic dependency graphs for validator safety/performance. They
are never represented as completed modeling runs or historical benchmarks.
"""
from __future__ import annotations

from collections import Counter
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get("MATHMODEL_TEST_REPO", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_domain as domain
from copilot_runtime import bind_file, object_errors, project_status
from copilot_store import digest


class ObservationV012Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "first"
        self.root.mkdir()
        self.cp = {"objects": {}, "current": {}, "requirements": {}, "tasks": {}, "revision": 0, "delivery": {}}
        for number in range(8):
            key, ident = "node" + str(number), "node" + str(number) + "@1"
            path = key + ".txt"
            (self.root / path).write_text("fixed input " + str(number), encoding="utf-8")
            payload = {"path": path}
            self.cp["objects"][ident] = {"id": ident, "key": key, "kind": "ArtifactRecord", "status": "generated",
                "payload": payload, "payload_hash": digest(payload), "files": [bind_file(self.root, path)],
                "dependencies": ["node" + str(parent) + "@1" for parent in (number - 1, number - 2) if parent >= 0]}
            self.cp["current"][key] = ident
        self.log = {"copilot": self.cp, "stages": {"5": {"qi_count": 1}},
                    "problem_meta": {"evaluation_mode": "historical_benchmark"}}
        self.top = "node7@1"

    def count_reads(self, callback):
        reads = Counter()
        original = domain.sha256_file
        def counted(path):
            reads[Path(path).resolve()] += 1
            return original(path)
        with patch.object(domain, "sha256_file", counted):
            result = callback()
        return result, reads

    def test_shared_ancestor_dag_checks_each_actual_file_once(self):
        errors, reads = self.count_reads(lambda: object_errors(self.root, self.cp, self.top))
        self.assertEqual(errors, [])
        self.assertEqual(len(reads), len(self.cp["objects"]))
        self.assertEqual(set(reads.values()), {1}, reads)

    def test_project_status_shares_one_scope_across_object_roots(self):
        result, reads = self.count_reads(lambda: project_status(self.root, self.log))
        self.assertEqual(result["stale_objects"], {})
        self.assertEqual(len(reads), len(self.cp["objects"]))
        self.assertEqual(set(reads.values()), {1}, reads)

    def test_next_public_call_rechecks_file_even_with_identical_cp_and_revision(self):
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        (self.root / "node0.txt").write_text("changed bytes", encoding="utf-8")
        errors, reads = self.count_reads(lambda: object_errors(self.root, self.cp, self.top))
        self.assertTrue(any("node0.txt" in error for error in errors), errors)
        self.assertGreater(reads[self.root / "node0.txt"], 0)
        self.assertEqual(self.cp["revision"], 0)

    def test_next_public_call_rechecks_current_pointer(self):
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        self.cp["current"]["node0"] = "node0@2"
        self.assertTrue(any("node0@1" in error for error in object_errors(self.root, self.cp, self.top)))
        self.cp["current"]["node0"] = "node0@1"
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])

    def test_next_public_call_rechecks_payload_hash_and_does_not_cache_failure(self):
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        leaf = self.cp["objects"]["node0@1"]
        leaf["payload"]["changed"] = True
        self.assertTrue(any("内容哈希" in error for error in object_errors(self.root, self.cp, self.top)))
        leaf["payload_hash"] = digest(leaf["payload"])
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])

    def test_cycle_is_rejected_without_recursion_overflow_or_scope_leak(self):
        self.cp["objects"]["node0@1"]["dependencies"] = [self.top]
        for root_id in (self.top, "node3@1"):
            errors = object_errors(self.root, self.cp, root_id)
            self.assertTrue(any("依赖循环" in error for error in errors), errors)
        self.cp["objects"]["node0@1"]["dependencies"] = []
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])

    def test_repeated_dependency_does_not_repeat_actual_file_read(self):
        # The normal Store already rejects duplicate declared IDs; a defensive
        # reader must still terminate and deduplicate a malformed in-memory list.
        self.cp["objects"][self.top]["dependencies"] *= 2
        errors, reads = self.count_reads(lambda: object_errors(self.root, self.cp, self.top))
        self.assertEqual(errors, [])
        self.assertEqual(set(reads.values()), {1}, reads)

    def test_nested_other_root_isolated_even_with_same_cp_identity_and_ids(self):
        other = Path(self.temp.name) / "second"
        other.mkdir()
        for path in self.root.glob("*.txt"):
            (other / path.name).write_bytes(path.read_bytes())
        original = domain.sha256_file
        observed = {}
        def checked(path):
            if "inner" not in observed:
                observed["inner"] = None
                observed["inner"] = object_errors(other, self.cp, self.top)
            return original(path)
        with patch.object(domain, "sha256_file", checked):
            self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        self.assertEqual(observed["inner"], [])

    def test_nested_other_cp_isolated_even_with_same_root_and_object_ids(self):
        other_cp = copy.deepcopy(self.cp)
        other_cp["objects"]["node0@1"]["payload"]["changed"] = True
        original = domain.sha256_file
        observed = {}
        def checked(path):
            if "inner" not in observed:
                observed["inner"] = None
                observed["inner"] = object_errors(self.root, other_cp, self.top)
            return original(path)
        with patch.object(domain, "sha256_file", checked):
            self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        self.assertTrue(any("内容哈希" in error for error in observed["inner"]), observed)
        self.assertFalse(any("依赖循环" in error for error in observed["inner"]), observed)

    def test_unexpected_exception_cleans_scope_before_next_check(self):
        with patch.object(domain, "sha256_file", side_effect=RuntimeError("deliberate hash probe failure")):
            with self.assertRaisesRegex(RuntimeError, "deliberate hash probe failure"):
                object_errors(self.root, self.cp, self.top)
        self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        (self.root / "node0.txt").write_text("changed after failure", encoding="utf-8")
        self.assertTrue(object_errors(self.root, self.cp, self.top))

    def test_project_status_does_not_reuse_previous_observation_after_drift(self):
        before = project_status(self.root, self.log)
        self.assertEqual(before["stale_objects"], {})
        (self.root / "node0.txt").write_text("changed between observations", encoding="utf-8")
        after = project_status(self.root, self.log)
        self.assertIn("node0@1", after["stale_objects"])
        self.assertIn(self.top, after["stale_objects"])
        self.assertNotIn("node7", after["current_objects"])

    def test_returned_error_list_cannot_poison_completed_memo(self):
        original = domain.sha256_file
        observed = {}
        def checked(path):
            if "inner" not in observed:
                observed["inner"] = None
                errors = object_errors(self.root, self.cp, "node0@1")
                errors.append("caller-injected false failure")
                observed["inner"] = errors
            return original(path)
        with patch.object(domain, "sha256_file", checked):
            self.assertEqual(object_errors(self.root, self.cp, self.top), [])
        self.assertEqual(observed["inner"], ["caller-injected false failure"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
