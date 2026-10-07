"""Behavioral tests at the actual Store/Runtime boundary, using synthetic inputs."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_copilot_runtime import make_project
from copilot_runtime import Runtime, requirement_status, project_status, usable, _put
from copilot_context import build_context, acknowledge
from copilot_store import ConflictError, IntegrityError, Store, digest


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="preview-interpretation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root, count=2)
        self.base = {kind: copy.deepcopy(self.rt.read()["copilot"]["objects"][oid]["payload"])
                     for kind, oid in self.ids.items()}

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    @staticmethod
    def replace_current(state, original, kind, data):
        # Deliberately bypass Runtime._put to exercise the public Store boundary.
        cp = state["copilot"]
        new = copy.deepcopy(original)
        new.update(id=original["key"] + "@2", version=2, kind=kind,
                   payload=data, payload_hash=digest(data))
        cp["objects"][new["id"]] = new
        cp["current"][original["key"]] = new["id"]

    def ambiguity(self, severity="high", **changes):
        return dict({"ambiguity_id": "AMB-Q1-1", "question": "Q1", "source_anchor": "problem.txt Q1",
                     "interpretations": ["length measured in metres", "length measured in centimetres"],
                     "severity": severity, "impact": "changes length scale", "owner": "modeler",
                     "requirement_ids": ["REQ-Q1-001"]}, **changes)

    def assumption(self, **changes):
        return dict({"assumption_id": "ASM-Q1-1", "question": "Q1", "statement": "use metres",
                     "rationale": "explicit provisional interpretation", "impact": "length scale",
                     "testability": "check independent sum", "linked_requirement_ids": ["REQ-Q1-001"],
                     "linked_ambiguity_ids": ["AMB-Q1-1"], "reversible": True,
                     "sensitivity_required": True, "validation_plan": "independent known solution",
                     "validation_checks": ["known"]}, **changes)

    def record(self, kind, payload):
        return self.rt.record_interpretation(self.rev(), kind, payload)["result"]["object_id"]

    def review(self, oid, action, **kwargs):
        return self.rt.review_interpretation(self.rev(), oid, action=action,
                    rationale="explicit decision recorded for this synthetic fixture", **kwargs)["result"]["object_id"]

    def contract(self):
        return self.reg("ProblemContract", "problem.Q1", copy.deepcopy(self.base["contract"]))

    def rebuild(self):
        ids = {"contract": self.contract()}
        cp = self.rt.read()["copilot"]
        c = cp["objects"][ids["contract"]]["payload"]
        model = copy.deepcopy(self.base["model"])
        model.update(problem_contract_id=c["contract_id"], problem_contract_semantic_hash=c["semantic_hash"])
        ids["model"] = self.reg("ModelSpec", "model.Q1", model, [ids["contract"]])
        m = self.rt.read()["copilot"]["objects"][ids["model"]]["payload"]
        params = copy.deepcopy(self.base["params"])
        params.update(modelspec_semantic_hash=m["semantic_hash"], modelspec_record_hash=m["record_hash"])
        ids["params"] = self.reg("ParameterSet", "params.Q1", params, [ids["model"]])
        ids["data"] = self.reg("DataContract", "data.Q1", copy.deepcopy(self.base["data"]), [ids["contract"]])
        code = {"question": "Q1", "revision_id": "code-v1"}
        ids["code"] = self.reg("CodeManifest", "code.Q1", code, [ids["model"]], ["solver.py"])
        ids["plan"] = self.reg("ValidationPlan", "plan.Q1", copy.deepcopy(self.base["plan"]), [ids["model"]])
        return ids

    def execute_checked(self, ids):
        run = self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
                    dependencies=[ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        checked = self.rt.validate_run(self.rev(), run, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"], checked)
        return checked["result_id"]

    def test_old_project_without_registers_remains_usable(self):
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], self.ids["model"]))
        self.assertNotIn("interpretations", build_context(self.root, role="modeler")["common"])

    def test_new_high_invalidates_contract_and_blocks_refreeze(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        cp = self.rt.read()["copilot"]
        self.assertEqual(cp["objects"][self.ids["model"]]["status"], "stale")
        with self.assertRaisesRegex(ValueError, "高影响"):
            self.contract()
        common = build_context(self.root, role="modeler")["common"]
        self.assertEqual(common["interpretations"][0]["object_id"], oid)
        self.assertFalse(common["submission"]["ready"])

    def test_stage_free_text_cannot_create_or_resolve_authoritative_decisions(self):
        for status in ("open", "resolved"):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "interpretation"):
                self.rt.record_stage(self.rev(), 2, {"ambiguities": [self.ambiguity(status=status)]})

    def test_explicit_resolution_binds_file_then_allows_freeze(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        with self.assertRaisesRegex(ValueError, "来源"):
            self.review(oid, "resolve", resolution="length measured in metres")
        resolved = self.review(oid, "resolve", resolution="length measured in metres", evidence_files=["problem.txt"])
        contract = self.contract()
        self.assertIn(resolved, self.rt.read()["copilot"]["objects"][contract]["dependencies"])
        (self.root / "problem.txt").write_text("changed source", encoding="utf-8")
        self.assertFalse(usable(self.root, self.rt.read()["copilot"], contract))

    def test_record_cannot_supply_accepted_resolved_or_fake_review(self):
        for kind, payload in (("AmbiguityEntry", self.ambiguity(status="resolved")),
                              ("AssumptionEntry", self.assumption(status="accepted")),
                              ("AmbiguityEntry", self.ambiguity(review={"action": "resolve"}))):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.record(kind, payload)

    def test_unknown_severity_and_cross_question_requirement_rejected(self):
        for payload in (self.ambiguity(severity="HIGH"), self.ambiguity(severity="unknown"),
                        self.ambiguity(requirement_ids=["REQ-Q2-001"]), self.ambiguity(question="Q9", requirement_ids=["REQ-Q9-001"])):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.record("AmbiguityEntry", payload)

    def test_severity_downgrade_cannot_bypass_block(self):
        self.record("AmbiguityEntry", self.ambiguity())
        with self.assertRaisesRegex(ValueError, "降低"):
            self.record("AmbiguityEntry", self.ambiguity("low"))

    def test_medium_requires_accepted_reversible_testable_assumption(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        with self.assertRaisesRegex(ValueError, "假设"):
            self.contract()
        assumption = self.record("AssumptionEntry", self.assumption())
        with self.assertRaisesRegex(ValueError, "假设"):
            self.contract()
        accepted = self.review(assumption, "accept")
        contract = self.contract()
        cp = self.rt.read()["copilot"]
        self.assertIn(accepted, cp["objects"][contract]["dependencies"])
        self.assertIn(accepted, requirement_status(self.root, self.rt.read())["pending_assumption_validation"])
        self.assertEqual(cp["objects"][accepted]["payload"]["status"], "accepted")

    def test_validation_is_real_downstream_receipt_not_source_rewrite(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        ids = self.rebuild()
        result = self.execute_checked(ids)
        receipt = self.review(accepted, "validate", result_ids=[result])
        cp = self.rt.read()["copilot"]
        self.assertEqual(cp["objects"][receipt]["kind"], "AssumptionValidation")
        self.assertTrue(usable(self.root, cp, result, verified=True))
        self.assertEqual(cp["objects"][accepted]["payload"]["status"], "accepted")
        self.assertNotIn("pending_assumption_validation", requirement_status(self.root, self.rt.read()))
        common = build_context(self.root, role="writer")["common"]
        row = next(x for x in common["interpretations"] if x["object_id"] == accepted)
        self.assertEqual(row["mathematical_validation"], "validated_checks")
        self.review(accepted, "reopen")
        self.assertFalse(usable(self.root, self.rt.read()["copilot"], result))

    def test_high_remains_blocked_even_with_accepted_assumption(self):
        self.record("AmbiguityEntry", self.ambiguity())
        self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        with self.assertRaisesRegex(ValueError, "高影响"):
            self.contract()

    def test_irreversible_medium_assumption_cannot_enable_freeze(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        self.review(self.record("AssumptionEntry", self.assumption(reversible=False)), "accept")
        with self.assertRaisesRegex(ValueError, "可逆"):
            self.contract()

    def test_accept_requires_predeclared_validation_not_only_free_text(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        oid = self.record("AssumptionEntry", self.assumption(validation_plan="", validation_checks=[]))
        before = self.rt.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "validation_plan"):
            self.review(oid, "accept")
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_assumption_cannot_link_unknown_or_other_question_ambiguity(self):
        self.record("AmbiguityEntry", self.ambiguity(question="Q2", requirement_ids=["REQ-Q2-001"]))
        with self.assertRaisesRegex(ValueError, "同问"):
            self.record("AssumptionEntry", self.assumption())

    def test_assumption_must_cover_ambiguity_requirement_scope(self):
        self.record("AmbiguityEntry", self.ambiguity("medium", requirement_ids=["REQ-Q1-001", "REQ-Q1-002"]))
        with self.assertRaisesRegex(ValueError, "全部 Requirement"):
            self.record("AssumptionEntry", self.assumption())

    def test_stable_id_cannot_move_to_other_question(self):
        self.record("AmbiguityEntry", self.ambiguity())
        with self.assertRaisesRegex(ValueError, "不可改绑"):
            self.record("AmbiguityEntry", self.ambiguity(question="Q2", requirement_ids=["REQ-Q2-001"]))

    def test_revision_conflict_and_obsolete_object_cannot_be_reviewed(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        revision = self.rev()
        self.record("AmbiguityEntry", self.ambiguity(impact="revised impact evidence"))
        with self.assertRaises(ConflictError):
            self.rt.review_interpretation(revision, oid, action="resolve", rationale="old decision", resolution="length measured in metres", evidence_files=["problem.txt"])
        with self.assertRaisesRegex(ValueError, "当前"):
            self.review(oid, "resolve", resolution="length measured in metres", evidence_files=["problem.txt"])

    def test_other_question_does_not_invalidate_q1_contract(self):
        self.record("AmbiguityEntry", self.ambiguity(question="Q2", requirement_ids=["REQ-Q2-001"]))
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], self.ids["contract"]))
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], self.ids["model"]))

    def test_context_cannot_reseal_resolution_but_historical_receipt_survives_review(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        context = build_context(self.root, role="modeler", member="member_1")
        forged = copy.deepcopy(context)
        forged["common"]["interpretations"][0]["status"] = "resolved"
        forged["common_hash"] = digest(forged["common"])
        forged.pop("context_id")
        forged["context_id"] = digest(forged)
        with self.assertRaisesRegex(ValueError, "投影"):
            acknowledge(self.root, self.rev(), forged, member="member_1", action="received")
        self.review(oid, "resolve", resolution="length measured in metres", evidence_files=["problem.txt"])
        acknowledge(self.root, self.rev(), context, member="member_1", action="received")
        self.assertEqual(context["common"]["interpretations"][0]["status"], "open")

    def test_store_cannot_delete_interpretation_to_bypass_freeze(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        key = self.rt.read()["copilot"]["objects"][oid]["key"]
        with self.assertRaises(IntegrityError):
            self.rt.store.transact(self.rev(), "redteam", "try hide ambiguity", lambda s: s["copilot"]["current"].pop(key))
        with self.assertRaisesRegex(ValueError, "高影响"):
            self.contract()

    def test_legacy_stage_resolved_is_not_automatically_authoritative(self):
        root = self.root / "old-project"
        product = Path(__file__).resolve().parents[1]
        state = json.loads((product / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        state["stages"]["2"]["ambiguities"] = [self.ambiguity(status="resolved")]
        Store(root / "state/decision_log.json").create(state)
        rt = Runtime(root)
        rt.configure(0, question_count=1)
        (root / "problem.txt").write_bytes((self.root / "problem.txt").read_bytes())
        with self.assertRaisesRegex(ValueError, "显式迁入"):
            rt.register(1, "ProblemContract", "problem.Q1", self.base["contract"])
        open_id = rt.record_interpretation(1, "AmbiguityEntry", self.ambiguity())["result"]["object_id"]
        with self.assertRaisesRegex(ValueError, "高影响"):
            rt.register(2, "ProblemContract", "problem.Q1", self.base["contract"])
        rt.review_interpretation(2, open_id, action="resolve", rationale="verified source interpretation", resolution="length measured in metres", evidence_files=["problem.txt"])
        frozen = rt.register(3, "ProblemContract", "problem.Q1", self.base["contract"])
        self.assertEqual(frozen["result"]["status"], "frozen")

    def test_store_cannot_hide_ambiguity_by_swapping_current_identity(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        original = self.rt.read()["copilot"]["objects"][oid]
        before = self.rt.store.path.read_bytes()
        mutations = [("ArtifactRecord", {"path": "problem.txt"}),
                     ("AmbiguityEntry", dict(original["payload"], ambiguity_id="another")),
                     ("AmbiguityEntry", dict(original["payload"], question="Q2", requirement_ids=["REQ-Q2-001"])),
                     ("AmbiguityEntry", dict(original["payload"], severity="low"))]
        for kind, data in mutations:
            with self.subTest(kind=kind, data=data), self.assertRaises(IntegrityError):
                self.rt.store.transact(self.rev(), "redteam", "swap source identity",
                    lambda state: self.replace_current(state, original, kind, data))
            self.assertEqual(before, self.rt.store.path.read_bytes())
        with self.assertRaisesRegex(ValueError, "高影响"):
            self.contract()

    def test_store_cannot_hide_assumption_by_swapping_current_identity(self):
        oid = self.record("AssumptionEntry", self.assumption(linked_ambiguity_ids=[]))
        original = self.rt.read()["copilot"]["objects"][oid]
        before = self.rt.store.path.read_bytes()
        for kind, data in [("ArtifactRecord", {"path": "problem.txt"}),
                           ("AssumptionEntry", dict(original["payload"], assumption_id="another")),
                           ("AssumptionEntry", dict(original["payload"], question="Q2", linked_requirement_ids=["REQ-Q2-001"]))]:
            with self.subTest(kind=kind, data=data), self.assertRaises(IntegrityError):
                self.rt.store.transact(self.rev(), "redteam", "swap source identity",
                    lambda state: self.replace_current(state, original, kind, data))
            self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_validation_cannot_borrow_previous_result_or_nonexistent_result(self):
        old_result = self.execute_checked(self.ids)
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        for rid in (old_result, "invented@1"):
            with self.subTest(rid=rid), self.assertRaises(ValueError):
                self.review(accepted, "validate", result_ids=[rid])

    def test_validation_requires_the_predeclared_assumption_checks(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption(validation_checks=["missing_test"])), "accept")
        result = self.execute_checked(self.rebuild())
        with self.assertRaisesRegex(ValueError, "missing_test"):
            self.review(accepted, "validate", result_ids=[result])

    def test_review_requires_actual_source_file_and_named_interpretation(self):
        oid = self.record("AmbiguityEntry", self.ambiguity())
        for kwargs in ({"resolution": "unlisted alternative", "evidence_files": ["problem.txt"]},
                       {"resolution": "length measured in metres", "evidence_files": ["missing.txt"]},
                       {"resolution": "length measured in metres", "evidence_files": ["../outside.txt"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.review(oid, "resolve", **kwargs)

    def test_legacy_high_cannot_be_masked_by_same_id_low_record(self):
        root = self.root / "legacy-high"
        product = Path(__file__).resolve().parents[1]
        state = json.loads((product / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        state["stages"]["2"]["ambiguities"] = [self.ambiguity(status="open")]
        Store(root / "state/decision_log.json").create(state)
        rt = Runtime(root)
        rt.configure(0, question_count=1)
        with self.assertRaisesRegex(ValueError, "不得降低"):
            rt.record_interpretation(1, "AmbiguityEntry", self.ambiguity("low"))
        with self.assertRaisesRegex(ValueError, "interpretations"):
            rt.record_interpretation(1, "AmbiguityEntry", self.ambiguity(interpretations=["unrelated one", "unrelated two"]))
        self.assertEqual(rt.read()["copilot"]["revision"], 1)

    def test_legacy_text_migration_retains_hash_without_auto_acceptance(self):
        root = self.root / "legacy-text"
        product = Path(__file__).resolve().parents[1]
        state = json.loads((product / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
        state["stages"]["2"]["assumptions"] = ["length units were assumed to be metres"]
        Store(root / "state/decision_log.json").create(state)
        rt = Runtime(root)
        rt.configure(0, question_count=1)
        payload = self.assumption(linked_ambiguity_ids=[], legacy_refs=[{"stage": "2", "index": 0}])
        oid = rt.record_interpretation(1, "AssumptionEntry", payload)["result"]["object_id"]
        data = rt.read()["copilot"]["objects"][oid]["payload"]
        self.assertEqual(data["status"], "proposed")
        self.assertEqual(data["legacy_sources"][0]["sha256"], digest(state["stages"]["2"]["assumptions"][0]))

    def test_generic_store_cannot_forge_assumption_validation_receipt(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        before = self.rt.store.path.read_bytes()
        with self.assertRaises(IntegrityError):
            self.rt.store.transact(self.rev(), "redteam", "inject synthetic receipt", lambda state: _put(
                state, "AssumptionValidation", "interpretation.validation.ASM-Q1-1",
                {"question": "Q1", "assumption_object_id": accepted, "checks": ["known"],
                 "result_ids": ["no-real-result"], "review": {"actor": "redteam", "action": "validate"}},
                [accepted], [], "verified"))
        self.assertEqual(before, self.rt.store.path.read_bytes())
        self.assertIn(accepted, requirement_status(self.root, self.rt.read())["pending_assumption_validation"])

    def test_generic_store_new_source_invalidates_old_contract_and_result_at_consumption(self):
        result = self.execute_checked(self.ids)
        self.assertTrue(usable(self.root, self.rt.read()["copilot"], result, verified=True))
        data = dict(self.ambiguity(), status="open")
        self.rt.store.transact(self.rev(), "redteam", "source added without eager invalidator",
            lambda state: _put(state, "AmbiguityEntry", "interpretation.ambiguity.AMB-Q1-1", data, [], [], "recorded"))
        state = self.rt.read()
        self.assertFalse(usable(self.root, state["copilot"], self.ids["contract"]))
        self.assertFalse(usable(self.root, state["copilot"], result, verified=True))
        before = self.rt.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "运行依赖失效"):
            self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"], ["result.json"],
                dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_receipt_cannot_lie_about_the_predeclared_check_set(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        result = self.execute_checked(self.rebuild())
        with self.assertRaises(IntegrityError):
            self.rt.store.transact(self.rev(), "redteam", "invent a check", lambda state: _put(
                state, "AssumptionValidation", "interpretation.validation.ASM-Q1-1",
                {"question": "Q1", "assumption_object_id": accepted, "checks": ["not-known"],
                 "result_ids": [result], "review": {"actor": "redteam", "action": "validate", "rationale": "claimed", "at": "now"}},
                [accepted, result], [], "verified"))

    def test_receipt_file_drift_restores_pending_even_without_revision_change(self):
        self.record("AmbiguityEntry", self.ambiguity("medium"))
        accepted = self.review(self.record("AssumptionEntry", self.assumption()), "accept")
        result = self.execute_checked(self.rebuild())
        receipt = self.review(accepted, "validate", result_ids=[result])
        revision = self.rev()
        (self.root / "checker.py").write_text("print('changed')\n", encoding="utf-8")
        state = self.rt.read()
        self.assertEqual(state["copilot"]["revision"], revision)
        self.assertFalse(usable(self.root, state["copilot"], receipt, verified=True))
        self.assertIn(accepted, requirement_status(self.root, state)["pending_assumption_validation"])


if __name__ == "__main__":
    unittest.main()
