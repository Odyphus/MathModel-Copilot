"""Registration must reject an unusable contract identity before committing it."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_domain as domain
from copilot_runtime import Runtime, _put, bind_file, project_status
from copilot_store import Store


class ProblemContractRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pc-rc3-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        state = json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        Store(self.root / "state/decision_log.json").create(state)
        self.runtime = Runtime(self.root)
        self.runtime.configure(0, question_count=1)
        (self.root / "problem.txt").write_text("Q1: calculate twice the given length.", encoding="utf-8")

    def payload(self):
        return {
            "question": "Q1", "title": "Twice a length", "contract_id": "PC-Q1",
            "source_files": [{"path": "problem.txt", "source_kind": "provided_problem",
                              "sha256": domain.sha256_file(self.root / "problem.txt")}],
            "requirements": [{"req_id": "REQ-Q1-001", "question": "Q1", "source_anchor": "Q1",
                              "requested_action": "calculate", "outputs": ["value"], "units": ["m"],
                              "acceptance_evidence": ["independent calculation"]}],
        }

    def rev(self):
        return self.runtime.read()["copilot"]["revision"]

    def authority_bytes(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in (self.root / "state").rglob("*") if path.is_file()}

    def register(self, payload, request_id=None):
        return self.runtime.register(self.rev(), "ProblemContract", "problem.Q1", payload,
                                     request_id=request_id)["result"]["object_id"]

    def assert_rejected_without_commit(self, payload):
        before = self.authority_bytes()
        revision = self.rev()
        request_id = f"invalid-contract-{revision}"
        with self.assertRaisesRegex(ValueError, "题意合同标识 contract_id"):
            self.register(payload, request_id=request_id)
        self.assertEqual(before, self.authority_bytes(), "Rejected registration changed the authority or journal")
        self.assertEqual(revision, self.rev())
        self.assertNotIn(request_id, self.runtime.read()["copilot"]["requests"])

    def test_missing_and_empty_identity_are_rejected_before_commit(self):
        missing = self.payload()
        missing.pop("contract_id")
        self.assert_rejected_without_commit(missing)
        empty = self.payload()
        empty["contract_id"] = ""
        self.assert_rejected_without_commit(empty)

    def test_wrong_types_and_invisible_identities_are_rejected(self):
        invalid = [None, False, True, 0, 7, 1.5, [], ["PC-Q1"], {}, {"id": "PC-Q1"},
                   " ", "\t\n", " PC-Q1", "PC-Q1 ", "PC Q1", "PC\tQ1", "PC\nQ1",
                   "\u3000", "PC\u00a0Q1", "PC\u200bQ1", "PC\u202eQ1", "PC\x00Q1"]
        for identity in invalid:
            with self.subTest(identity=repr(identity)):
                payload = self.payload()
                payload["contract_id"] = identity
                self.assert_rejected_without_commit(payload)

    def model_payload(self, contract):
        return {
            "question": "Q1", "spec_id": "MS-Q1", "title": "twice a length",
            "observation_unit": "length", "objective": {"formula_id": "F1", "direction": "compute"},
            "inputs": [{"name": "n"}], "outputs": [{"name": "value"}],
            "data_contract": {"scope": "given constants"}, "solver": {"method": "direct arithmetic"},
            "randomness": {"seed_policy": "deterministic"},
            "constraints": [{"formula_id": "C1", "expression": "n >= 0"}],
            "formulas": [{"formula_id": "F1", "expression": "y = 2*n"}],
            "validation_plan": [{"check_id": "known"}], "required_outputs": ["result.json"],
            "failure_conditions": ["value differs from independent calculation"],
            "problem_contract_id": contract["contract_id"],
            "problem_contract_semantic_hash": contract["semantic_hash"],
            "requirement_ids": ["REQ-Q1-001"],
            "method_decision": {"selected_route": "direct", "candidates": [
                {"route": "direct", "decision": "selected", "reason": "Known deterministic formula"}]},
        }

    def test_valid_contract_binds_model_and_preserves_exact_identity(self):
        for identity in ["PC-Q1", "题意合同-Q1", "123"]:
            with self.subTest(identity=identity):
                payload = self.payload()
                payload["contract_id"] = identity
                contract_id = self.register(payload)
                contract = self.runtime.read()["copilot"]["objects"][contract_id]["payload"]
                self.assertEqual(identity, contract["contract_id"])
                model = self.runtime.register(self.rev(), "ModelSpec", "model.Q1",
                                              self.model_payload(contract), dependencies=[contract_id])
                registered = self.runtime.read()["copilot"]["objects"][model["result"]["object_id"]]
                self.assertEqual([contract_id], registered["dependencies"])
                self.assertEqual("frozen", registered["status"])

    def test_rejected_update_retains_current_contract_model_and_requirements(self):
        contract_id = self.register(self.payload())
        contract = self.runtime.read()["copilot"]["objects"][contract_id]["payload"]
        model = self.runtime.register(self.rev(), "ModelSpec", "model.Q1",
                                      self.model_payload(contract), dependencies=[contract_id])
        invalid = copy.deepcopy(contract)
        invalid.update(contract_id="", title="Changed title")
        self.assert_rejected_without_commit(invalid)
        state = self.runtime.read()
        self.assertEqual(contract_id, state["copilot"]["current"]["problem.Q1"])
        self.assertEqual("frozen", state["copilot"]["objects"][model["result"]["object_id"]]["status"])
        self.assertEqual(contract_id, state["copilot"]["requirements"]["REQ-Q1-001"]["contract_id"])

    def test_cli_reports_actionable_chinese_error_and_no_commit(self):
        payload = self.payload()
        payload.pop("contract_id")
        (self.root / "invalid.json").write_text(json.dumps(payload), encoding="utf-8")
        before = self.authority_bytes()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/copilot.py"), "--workspace", str(self.root),
                                 "register", "--kind", "ProblemContract", "--key", "problem.Q1",
                                 "--payload", "invalid.json", "--expected-revision", str(self.rev())],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("题意合同标识 contract_id", result.stdout + result.stderr)
        self.assertIn("PC-Q1", result.stdout + result.stderr)
        self.assertEqual(before, self.authority_bytes())

    def test_legacy_record_reads_and_versioned_repair_preserve_history(self):
        payload = self.payload()
        payload.pop("contract_id")
        legacy_draft = domain.ProblemContract.from_dict(payload)
        self.assertEqual("", legacy_draft.contract_id)
        self.assertEqual("draft", legacy_draft.status)
        legacy_draft.status = "frozen"
        legacy_payload = legacy_draft.to_dict()

        # Reproduce a persisted pre-RC3 record in an isolated test fixture.
        # Store still owns the transaction, immutable history, and state hash.
        def legacy_fixture(state):
            oid = _put(state, "ProblemContract", "problem.Q1", legacy_payload,
                       files=[bind_file(self.root, "problem.txt")], status="frozen")
            entry = legacy_payload["requirements"][0]
            state["copilot"]["requirements"][entry["req_id"]] = {
                "question": "Q1", "definition": entry, "contract_id": oid, "coverage": {}, "active": True}
            return oid

        old_id = self.runtime.store.transact(self.rev(), "test_fixture", "Load a historical RC2 fixture",
                                             legacy_fixture)["result"]
        before = self.authority_bytes()
        state = self.runtime.read()
        self.assertEqual("", state["copilot"]["objects"][old_id]["payload"]["contract_id"])
        project_status(self.root, state)
        self.assertEqual(before, self.authority_bytes())
        new_id = self.register(self.payload())
        repaired = self.runtime.read()["copilot"]
        self.assertEqual(legacy_payload, repaired["objects"][old_id]["payload"])
        self.assertEqual("stale", repaired["objects"][old_id]["status"])
        self.assertEqual(new_id, repaired["current"]["problem.Q1"])
        self.assertEqual("PC-Q1", repaired["objects"][new_id]["payload"]["contract_id"])


if __name__ == "__main__":
    unittest.main()
