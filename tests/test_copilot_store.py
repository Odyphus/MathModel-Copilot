import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_store import Store, ConflictError, IntegrityError


def writer(path, value, barrier, queue):
    barrier.wait()
    try:
        Store(path).transact(0, value, "concurrency test", lambda s: s.update(task_type=value))
        queue.put("committed")
    except ConflictError:
        queue.put("conflict")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state" / "decision_log.json"
        self.store = Store(self.path)
        self.template = json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        self.store.create(self.template)

    def test_cas_rejects_stale_without_losing_first_write(self):
        self.store.transact(0, "modeler", "first", lambda s: s.update(task_type="accepted"))
        before = self.path.read_bytes()
        with self.assertRaises(ConflictError):
            self.store.transact(0, "coder", "second", lambda s: s.update(task_type="lost"))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.store.read()["task_type"], "accepted")

    def test_two_real_processes_only_one_commits(self):
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=writer, args=(str(self.path), x, barrier, queue)) for x in ("modeler", "coder")]
        for p in processes:
            p.start()
        for p in processes:
            p.join(15)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(sorted([queue.get(timeout=2), queue.get(timeout=2)]), ["committed", "conflict"])
        self.assertEqual(self.store.read()["copilot"]["revision"], 1)
        queue.close()

    def test_failed_callback_and_bad_nested_state_are_atomic(self):
        before = self.path.read_bytes()
        for fn in (lambda s: s["stages"]["5"].update(qi_count=-1),
                   lambda s: s["compliance"].update(ai_usage="pass"),
                   lambda s: s["problem_meta"].update(team_size="3")):
            with self.assertRaises(ValueError):
                self.store.transact(0, "qa", "invalid", fn)
            self.assertEqual(before, self.path.read_bytes())

    def test_idempotency_and_read_only(self):
        fn = lambda s: s.update(task_type="repeat")
        one = self.store.transact(0, "qa", "retry", fn, "req-1", "payload-1")
        before = self.path.read_bytes()
        self.assertEqual(one, self.store.transact(0, "qa", "retry", fn, "req-1", "payload-1"))
        self.store.read()
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(ConflictError):
            self.store.transact(1, "qa", "retry", fn, "req-1", "different")

    def test_direct_state_edit_is_detected(self):
        state = self.store.read()
        state["current_stage"] = 9
        self.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(IntegrityError):
            self.store.read()

    def test_legacy_migration_preserves_records(self):
        self.path.write_text(json.dumps(self.template), encoding="utf-8")
        self.store.transact(0, "qa", "migrate", lambda s: {"migrated": True})
        migrated = self.store.read()
        self.assertEqual(migrated["scores"], self.template["scores"])
        self.assertFalse(migrated["stages"]["9"]["submission_ready"])
        self.assertEqual(migrated["copilot"]["revision"], 1)


if __name__ == "__main__":
    unittest.main()
