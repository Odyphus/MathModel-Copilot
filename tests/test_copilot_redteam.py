"""Independent adversarial regressions using public runtime entry points.

These tests check externally observable acceptance, not implementation text.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_copilot_runtime import make_project, SOLVER, CHECKER
from copilot_context import build_context, acknowledge
from copilot_runtime import project_status, usable
from copilot_store import digest
import copilot_domain as d


class CopilotRedTeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="copilot-redteam-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root)

    def rev(self):
        return self.rt.read()["copilot"]["revision"]

    def payload(self, name):
        return copy.deepcopy(self.rt.read()["copilot"]["objects"][self.ids[name]]["payload"])

    def execute(self, outputs=None):
        return self.rt.execute(self.rev(), "Q1", ["{python}", "solver.py"],
            outputs or ["result.json"], dependencies=[self.ids[x] for x in
            ("model", "params", "data", "code", "plan")], timeout=10)["result"]

    def validated(self):
        executed = self.execute()
        self.assertEqual("executed", executed["status"], executed)
        run_id = executed["object_id"]
        checked = self.rt.validate_run(self.rev(), run_id, "checker.py",
            ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(checked["passed"], checked)
        return run_id, checked["result_id"]

    def install_solver(self, source):
        payload = self.payload("code")
        (self.root / "solver.py").write_text(source, encoding="utf-8")
        payload["revision_id"] = "redteam-code-v2"
        payload["files"] = [{"path": "solver.py", "sha256": d.sha256_file(self.root / "solver.py")}]
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", payload,
            [self.ids["model"]], ["solver.py"])

    def add_q2(self):
        payload = self.payload("contract")
        payload.update(question="Q2", title="Independent comparison", contract_id="PC-Q2")
        payload["requirements"] = [{"req_id": "REQ-Q2-001", "question": "Q2",
            "source_anchor": "Q2", "requested_action": "compare two methods",
            "outputs": ["comparison"], "units": ["m"], "acceptance_evidence": ["comparison"]}]
        return self.reg("ProblemContract", "problem.Q2", payload)

    def replace_model(self, **updates):
        params, code, plan = (self.payload(x) for x in ("params", "code", "plan"))
        model = self.payload("model")
        model.update(updates)
        self.ids["model"] = self.reg("ModelSpec", "model.Q1", model, [self.ids["contract"]])
        model = self.payload("model")
        params.update(modelspec_semantic_hash=model["semantic_hash"],
                      modelspec_record_hash=model["record_hash"])
        code["modelspec_semantic_hash"] = model["semantic_hash"]
        self.ids["params"] = self.reg("ParameterSet", "params.Q1", params, [self.ids["model"]])
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", code, [self.ids["model"]], ["solver.py"])
        self.ids["plan"] = self.reg("ValidationPlan", "plan.Q1", plan, [self.ids["model"]])

    def claim(self, run_id, result_id, content):
        cp = self.rt.read()["copilot"]
        output = cp["objects"][run_id]["payload"]["outputs"][0]["path"]
        return self.rt.claim(self.rev(), {
            "claim_id": "CLAIM-Q1-001", "claim": content, "paper_anchor": "Q1 result",
            "formal_run_id": run_id, "requirement_ids": ["REQ-Q1-001"],
            "data_sources": [self.ids["data"]], "code_locations": ["solver.py"],
            "tables": [output], "validation_evidence": ["Q1.run.formal"],
            "limitations": ["Only the supplied deterministic length case"]}, [result_id])

    def test_run_context_is_an_immutable_execution_input(self):
        self.install_solver("""import json
from pathlib import Path
p=Path('run_context.json')
context=json.loads(p.read_text(encoding='utf-8'))
context['ParameterSet']['entries'][0]['current_value']=500
p.write_text(json.dumps(context),encoding='utf-8')
Path('result.json').write_text(json.dumps({'value':1000}),encoding='utf-8')
""")
        executed = self.execute()
        self.assertNotEqual("executed", executed["status"],
            "Registered n=5 was replaced by n=500 in run_context, but execution remained valid")

    def test_deleting_a_copied_input_cannot_retain_completed_status(self):
        self.install_solver(SOLVER + "Path('problem.txt').unlink()\n")
        executed = self.execute()
        self.assertNotEqual("executed", executed["status"],
            "Post-run missing input raised an exception but left receipt completed")

    def test_snapshot_drift_after_execution_revokes_run_currentness(self):
        run_id, result_id = self.validated()
        cp = self.rt.read()["copilot"]
        snapshot = self.root / cp["objects"][run_id]["execution"]["directory"] / "solver.py"
        snapshot.write_text("# altered frozen execution source\n", encoding="utf-8")
        status = project_status(self.root, self.rt.read())
        self.assertIn(run_id, status["stale_objects"])
        self.assertIn(result_id, status["stale_objects"])

    def test_q1_result_cannot_close_q2_via_unrelated_data_dependency(self):
        q2 = self.add_q2()
        self.ids["data"] = self.reg("DataContract", "data.Q1", self.payload("data"),
            [self.ids["contract"], q2])
        _, result_id = self.validated()
        with self.assertRaises(ValueError):
            self.rt.cover(self.rev(), "REQ-Q2-001", {"comparison": result_id})

    def test_task_cannot_complete_from_another_requirements_result(self):
        q2 = self.add_q2()
        _, result_id = self.validated()
        self.rt.task(self.rev(), "TASK-Q2", {"title": "Compare the second question",
            "role": "coder", "requirements": ["REQ-Q2-001"], "dependencies": [q2]})
        self.rt.transition(self.rev(), "TASK-Q2", "running")
        with self.assertRaises(ValueError):
            self.rt.transition(self.rev(), "TASK-Q2", "completed", outputs=[result_id])

    def test_model_cannot_claim_other_questions_requirements(self):
        self.add_q2()
        model = self.payload("model")
        model["requirement_ids"] = ["REQ-Q2-001"]
        with self.assertRaises(ValueError):
            self.reg("ModelSpec", "model.Q1", model, [self.ids["contract"]])

    def test_execute_must_produce_frozen_model_required_outputs(self):
        self.replace_model(required_outputs=["result.json", "diagnostic.csv"])
        try:
            executed = self.execute(["result.json"])
        except ValueError:
            return
        self.assertNotEqual("executed", executed["status"],
            "Caller omitted the frozen model's diagnostic.csv and still obtained an executed run")

    def test_validation_plan_cannot_omit_the_frozen_models_checks(self):
        plan = self.payload("plan")
        plan["checks"] = [{"check_id": "unrelated", "method": "file existence",
                           "criterion": "output file exists and can be opened"}]
        with self.assertRaises(ValueError):
            self.reg("ValidationPlan", "plan.Q1", plan, [self.ids["model"]])

    def test_context_resealed_with_forged_object_payload_is_rejected(self):
        context = build_context(self.root, role="coder", member="redteam-coder")
        context["objects"][self.ids["model"]]["payload"]["title"] = "Different model shown to teammate"
        context.pop("context_id")
        context["context_id"] = digest(context)
        with self.assertRaises(ValueError):
            acknowledge(self.root, self.rev(), context, member="redteam-coder", action="received")
            acknowledge(self.root, self.rev(), context, member="redteam-coder", action="adopted",
                        object_ids=[self.ids["model"]])

    def test_valid_evidence_reference_can_be_registered(self):
        run_id, result_id = self.validated()
        result = self.claim(run_id, result_id, "The computed length is 10 m.")
        self.assertIn("claim_id", result["result"])

    def test_false_numeric_claim_does_not_become_verified_by_reference_alone(self):
        run_id, result_id = self.validated()
        try:
            registered = self.claim(run_id, result_id, "The computed length is 999 m.")
        except ValueError:
            return
        claim_id = registered["result"]["claim_id"]
        self.assertNotEqual("verified", self.rt.read()["copilot"]["objects"][claim_id]["status"],
            "A real result value=10 cannot verify an arbitrary contradictory claim value=999")

    def test_code_manifest_file_list_must_match_actual_snapshot_files(self):
        code = self.payload("code")
        code["files"] = [{"path": "checker.py", "sha256": d.sha256_file(self.root / "checker.py")}]
        with self.assertRaises(ValueError):
            self.reg("CodeManifest", "code.Q1", code, [self.ids["model"]], ["solver.py"])

    def test_checker_copy_drift_cannot_replace_predeclared_checker(self):
        self.install_solver("from pathlib import Path\nPath('result.json').write_text('{\"value\":999}',encoding='utf-8')\n")
        executed = self.execute()
        self.assertEqual("executed", executed["status"])
        import copilot_runtime
        real_copy = copilot_runtime.shutil.copy2

        def changed_checker_copy(source, target, *args, **kwargs):
            result = real_copy(source, target, *args, **kwargs)
            target = Path(target)
            if target.name == "checker.py" and "checks" in target.parts:
                target.write_text("""import json,sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps({'checks':[{'check_id':'known','status':'pass','evidence':['result.json']}],'metrics':{'value':999}}),encoding='utf-8')
""", encoding="utf-8")
            return result

        with patch("copilot_runtime.shutil.copy2", side_effect=changed_checker_copy):
            try:
                checked = self.rt.validate_run(self.rev(), executed["object_id"], "checker.py",
                    ["{python}", "{checker}", "{run}", "{report}"])["result"]
            except ValueError:
                return
        self.assertFalse(checked["passed"],
            "Copied checker differed from the plan's SHA, and certified value=999 against expected 10")

    def test_malformed_checker_recheck_withdraws_previous_verified_result(self):
        original_root = self.root
        cases = {
            "missing_status": {"checks": [{"check_id": "known", "evidence": ["result.json"]}]},
            "unhashable_status": {"checks": [{"check_id": "known", "status": [], "evidence": ["result.json"]}]},
            "nonobject_root": [],
            "nonfinite_metrics": {"checks": [{"check_id": "known", "status": "pass",
                "evidence": ["result.json"]}], "metrics": {"value": float("nan")}},
        }
        for name, report in cases.items():
            with self.subTest(report=name):
                self.root = original_root / name
                self.rt, self.ids, self.reg = make_project(self.root)
                # The predeclared checker is stable. A newly added, unbound
                # marker asks the same checker to emit one malformed response.
                branch = ("if (root/'malformed.flag').exists():\n"
                          f"    output.write_text({json.dumps(report)!r},encoding='utf-8')\n"
                          "    sys.exit(0)\n")
                source = CHECKER.replace("ctx=json.loads", branch + "ctx=json.loads", 1)
                (self.root / "checker.py").write_text(source, encoding="utf-8")
                plan = self.payload("plan")
                plan["checker"]["sha256"] = d.sha256_file(self.root / "checker.py")
                self.ids["plan"] = self.reg("ValidationPlan", "plan.Q1", plan, [self.ids["model"]])
                run_id, result_id = self.validated()
                cp = self.rt.read()["copilot"]
                directory = self.root / cp["objects"][run_id]["execution"]["directory"]
                (directory / "malformed.flag").write_text("recheck failure", encoding="utf-8")
                try:
                    self.rt.validate_run(self.rev(), run_id, "checker.py",
                        ["{python}", "{checker}", "{run}", "{report}"])
                except (ValueError, KeyError, AttributeError, TypeError):
                    pass
                self.assertFalse(usable(self.root, self.rt.read()["copilot"], result_id, verified=True),
                    "A failed/malformed recheck must withdraw every old verified consumer")

    def test_numeric_claim_does_not_misparse_fraction_or_unicode_negative(self):
        run_id, result_id = self.validated()
        for literal in (".10", "−10"):
            with self.subTest(literal=literal):
                with self.assertRaises(ValueError):
                    self.claim(run_id, result_id, f"The computed length is {literal} m.")

    def test_store_cannot_rewrite_existing_object_version_even_if_resealed(self):
        before = self.rt.store.path.read_bytes()
        def rewrite(state):
            obj = state["copilot"]["objects"][self.ids["params"]]
            obj["payload"]["entries"][0]["current_value"] = 999
            obj["payload"] = d.seal_record(obj["payload"])
            obj["payload_hash"] = digest(obj["payload"])
        with self.assertRaises(ValueError):
            self.rt.store.transact(self.rev(), "integration", "attempt same-version rewrite", rewrite)
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_store_cannot_delete_committed_journal_history(self):
        before = self.rt.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.rt.store.transact(self.rev(), "integration", "attempt history replacement",
                                  lambda state: state["copilot"]["journal"].clear())
        self.assertEqual(before, self.rt.store.path.read_bytes())

    def test_store_cannot_reactivate_a_superseded_object_version(self):
        previous = self.ids["params"]
        payload = self.payload("params")
        payload["entries"][0]["current_value"] = 7
        self.ids["params"] = self.reg("ParameterSet", "params.Q1", payload, [self.ids["model"]])
        before = self.rt.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.rt.store.transact(self.rev(), "integration", "attempt obsolete version resurrection",
                lambda state: state["copilot"]["objects"][previous].update(status="frozen"))
        self.assertEqual(before, self.rt.store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
