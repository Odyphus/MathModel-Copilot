from __future__ import annotations
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_store import Store, ConflictError
from copilot_runtime import Runtime, project_status
import copilot_domain as d

SOLVER = """import json
from pathlib import Path
ctx=json.loads(Path('run_context.json').read_text(encoding='utf-8'))
n=ctx['ParameterSet']['entries'][0]['current_value']
Path('result.json').write_text(json.dumps({'value':2*n}),encoding='utf-8')
"""
CHECKER = """import json,sys
from pathlib import Path
root=Path(sys.argv[1]); output=Path(sys.argv[2])
ctx=json.loads((root/'run_context.json').read_text(encoding='utf-8'))
n=ctx['ParameterSet']['entries'][0]['current_value']
actual=json.loads((root/'result.json').read_text(encoding='utf-8'))['value']
ok=actual==sum([n,n])
output.write_text(json.dumps({'checks':[{'check_id':'known','status':'pass' if ok else 'fail','evidence':['result.json'],'actual':actual}], 'metrics':{'value':actual}, 'scope':'known deterministic case'}),encoding='utf-8')
sys.exit(0 if ok else 1)
"""


def make_project(root, count=3, extra_requirement=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    state = json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
    Store(root / "state/decision_log.json").create(state)
    rt = Runtime(root)
    rt.configure(0, question_count=count, problem_year=2018, rules_year=2026, evaluation_mode="historical_benchmark")
    (root / "problem.txt").write_text("Q1 calculate twice a supplied length. Q2 compare. Q3 explain.", encoding="utf-8")
    (root / "solver.py").write_text(SOLVER, encoding="utf-8")
    (root / "checker.py").write_text(CHECKER, encoding="utf-8")
    def reg(kind,key,payload,deps=(),files=()):
        if kind == "ProblemContract" and extra_requirement:
            payload = copy.deepcopy(payload)
            payload["requirements"].append({"req_id":"REQ-Q1-002", "question":"Q1", "source_anchor":"Q1 comparison", "requested_action":"compare methods", "outputs":["comparison"], "units":["m"], "acceptance_evidence":["independent comparison"]})
        return rt.register(rt.read()["copilot"]["revision"],kind,key,payload,dependencies=deps,files=files)["result"]["object_id"]
    contract = reg("ProblemContract", "problem.Q1", {"question":"Q1","title":"Twice a length", "contract_id":"PC-Q1", "source_files":[{"path":"problem.txt","sha256":d.sha256_file(root/"problem.txt"),"source_kind":"provided_problem"}], "requirements":[{"req_id":"REQ-Q1-001","question":"Q1","source_anchor":"Q1","requested_action":"calculate","outputs":["value"],"units":["m"],"acceptance_evidence":["known"]}]})
    c = rt.read()["copilot"]["objects"][contract]["payload"]
    parameter = d.ParameterEntry(parameter_id="n",symbol="n",meaning="supplied length",unit="m",category="external",external_source="problem.txt Q1",current_value=5).to_dict()
    model = reg("ModelSpec", "model.Q1", {"question":"Q1","spec_id":"MS-Q1-1","title":"twice length","observation_unit":"length","objective":{"formula_id":"F1","direction":"compute"}, "inputs":[{"name":"n"}], "outputs":[{"name":"value"}],"data_contract":{"scope":"given constants"}, "solver":{"method":"direct arithmetic"},"randomness":{"seed_policy":"deterministic"},"constraints":[{"formula_id":"C1","expression":"n >= 0"}],"formulas":[{"formula_id":"F1","expression":"y=2n"}],"validation_plan":[{"check_id":"known"}],"required_outputs":["result.json"],"failure_conditions":["value differs from known result"],"problem_contract_id":c["contract_id"],"problem_contract_semantic_hash":c["semantic_hash"],"requirement_ids":["REQ-Q1-001"],"method_decision":{"selected_route":"direct","candidates":[{"route":"direct","decision":"selected","reason":"known deterministic formula"}]},"parameters":[parameter]}, [contract])
    m = rt.read()["copilot"]["objects"][model]["payload"]
    params = reg("ParameterSet", "params.Q1", d.ParameterSet(question="Q1",spec_id=m["spec_id"],modelspec_semantic_hash=m["semantic_hash"],modelspec_record_hash=m["record_hash"],version=1,entries=[d.ParameterEntry.from_dict(parameter)]).to_dict(), [model])
    data = reg("DataContract", "data.Q1", {"question":"Q1","inventory":None,"passport":d.seal_record({"applicability":"not_applicable","not_applicable_reason":"supplied constants with no observational dataset"}),"split":d.seal_record({"applicability":"not_applicable","not_applicable_reason":"deterministic arithmetic needs no train test split"})}, [contract])
    code = reg("CodeManifest", "code.Q1", {"question":"Q1","revision_id":"code-v1"}, [model], ["solver.py"])
    plan = reg("ValidationPlan", "plan.Q1", {"question":"Q1","checker":{"path":"checker.py","sha256":d.sha256_file(root/"checker.py")},"checks":[{"check_id":"known","method":"independent addition","criterion":"computed length equals independently added length"}]}, [model])
    return rt, {"contract":contract,"model":model,"params":params,"data":data,"code":code,"plan":plan}, reg


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.rt,self.ids,self.reg=make_project(self.root)

    def rev(self): return self.rt.read()["copilot"]["revision"]
    def execute(self, argv=None, outputs=None, timeout=10):
        return self.rt.execute(self.rev(),"Q1",argv or ["{python}","solver.py"],outputs or ["result.json"],dependencies=[self.ids[k] for k in ("model","params","data","code","plan")],timeout=timeout)["result"]
    def validated(self):
        run=self.execute()["object_id"]
        checked=self.rt.validate_run(self.rev(),run,"checker.py",["{python}","{checker}","{run}","{report}"])["result"]
        self.assertTrue(checked["passed"], checked)
        return run,checked["result_id"]

    def replace_solver(self, source):
        (self.root / "solver.py").write_text(source, encoding="utf-8")
        self.ids["code"] = self.reg("CodeManifest", "code.Q1", {"question":"Q1"}, [self.ids["model"]], ["solver.py"])

    def test_requirement_matrix_retains_missing_questions(self):
        _,result=self.validated()
        self.rt.cover(self.rev(),"REQ-Q1-001",{"value":result})
        status=project_status(self.root,self.rt.read())
        self.assertEqual(status["requirements"]["questions"],{"Q1":"verified","Q2":"missing","Q3":"missing"})
        self.assertFalse(status["submission"]["ready"])

    def test_code_generated_is_not_execution_or_verification(self):
        obj=self.reg("ArtifactRecord","draft.code",{"path":"solver.py"},[self.ids["model"]])
        self.assertEqual(self.rt.read()["copilot"]["objects"][obj]["status"],"generated")
        with self.assertRaises(ValueError): self.rt.cover(self.rev(),"REQ-Q1-001",{"value":obj})

    def test_exit_success_requires_new_outputs(self):
        (self.root/"result.json").write_text('{"value":10}',encoding="utf-8")
        self.replace_solver("print('no output')")
        run=self.execute()
        self.assertEqual(run["status"],"missing_outputs")
        with self.assertRaises(ValueError): self.rt.validate_run(self.rev(),run["object_id"],"checker.py",[])

    def test_failure_and_timeout_cannot_be_verified(self):
        self.replace_solver("raise SystemExit(3)")
        failed=self.execute()
        self.assertEqual(failed["status"],"failed")
        self.replace_solver("import time; time.sleep(3)")
        timed=self.execute(timeout=0.05)
        self.assertEqual(timed["status"],"timeout")

    def test_unregistered_execution_and_checker_commands_rejected(self):
        with self.assertRaises(ValueError): self.execute(["{python}","-c","print('forged')"])
        run=self.execute()["object_id"]
        with self.assertRaises(ValueError): self.rt.validate_run(self.rev(),run,"checker.py",["{python}","-c","print('fake pass')"])

    def test_parameter_cannot_change_frozen_unit(self):
        params=copy.deepcopy(self.rt.read()["copilot"]["objects"][self.ids["params"]]["payload"])
        params["entries"][0]["unit"]="s"
        with self.assertRaises(ValueError): self.reg("ParameterSet","params.Q1",params,[self.ids["model"]])

    def test_same_question_does_not_cover_an_undeclared_requirement(self):
        rt, ids, _ = make_project(self.root / "two-requirements", count=1, extra_requirement=True)
        rev = lambda: rt.read()["copilot"]["revision"]
        run = rt.execute(rev(),"Q1",["{python}","solver.py"],["result.json"],dependencies=[ids[k] for k in ("model","params","data","code","plan")])["result"]["object_id"]
        result = rt.validate_run(rev(),run,"checker.py",["{python}","{checker}","{run}","{report}"])["result"]["result_id"]
        with self.assertRaises(ValueError): rt.cover(rev(),"REQ-Q1-002",{"comparison":result})
        rt.task(rev(),"T2",{"title":"compare", "role":"coder", "requirements":["REQ-Q1-002"], "dependencies":[ids["contract"]]})
        rt.transition(rev(),"T2","running")
        with self.assertRaises(ValueError): rt.transition(rev(),"T2","completed",outputs=[result])

    def test_another_key_cannot_bypass_version_invalidation(self):
        payload = copy.deepcopy(self.rt.read()["copilot"]["objects"][self.ids["model"]]["payload"])
        before = self.rt.store.path.read_bytes()
        with self.assertRaises(ValueError): self.reg("ModelSpec","another-model-key",payload,[self.ids["contract"]])
        self.assertEqual(before,self.rt.store.path.read_bytes())

    def test_parameter_change_propagates_only_affected_dependents(self):
        run,result=self.validated()
        section=self.reg("ArtifactRecord","paper.Q1",{"path":"problem.txt"},[result])
        unrelated=self.reg("ArtifactRecord","unrelated",{"path":"checker.py"})
        params=copy.deepcopy(self.rt.read()["copilot"]["objects"][self.ids["params"]]["payload"])
        params["entries"][0]["current_value"]=7
        new=self.reg("ParameterSet","params.Q1",params,[self.ids["model"]])
        cp=self.rt.read()["copilot"]
        for x in (run,result,section): self.assertEqual(cp["objects"][x]["status"],"stale")
        self.assertEqual(cp["objects"][unrelated]["status"],"generated")
        self.assertEqual(cp["current"]["params.Q1"],new)

    def test_direct_file_drift_seen_on_read_without_state_mutation(self):
        run,result=self.validated()
        self.rt.cover(self.rev(),"REQ-Q1-001",{"value":result})
        before=self.rt.store.path.read_bytes()
        (self.root/"solver.py").write_text(SOLVER+"# changed\n",encoding="utf-8")
        status=project_status(self.root,self.rt.read())
        self.assertIn(run,status["stale_objects"])
        self.assertEqual(status["requirements"]["verified"],0)
        self.assertEqual(before,self.rt.store.path.read_bytes())

    def test_fabricated_claim_and_direct_run_registration_rejected(self):
        with self.assertRaises(ValueError): self.rt.claim(self.rev(),{"claim_id":"C1","claim":"accuracy improves 23%","paper_anchor":"abstract","limitations":["only this dataset"]},[])
        with self.assertRaises(ValueError): self.rt.register(self.rev(),"RunRecord","fake",{"status":"verified"})

    def test_same_request_does_not_execute_twice(self):
        rev=self.rev(); deps=[self.ids[k] for k in ("model","params","data","code","plan")]
        first=self.rt.execute(rev,"Q1",["{python}","solver.py"],["result.json"],dependencies=deps,request_id="once")
        second=self.rt.execute(rev,"Q1",["{python}","solver.py"],["result.json"],dependencies=deps,request_id="once")
        self.assertEqual(first["result"]["object_id"],second["result"]["object_id"])
        self.assertEqual(len(list((self.root/".copilot/runs").iterdir())),1)

    def test_task_completion_requires_verified_output(self):
        self.rt.task(self.rev(),"T1",{"title":"solve Q1","role":"coder","requirements":["REQ-Q1-001"],"dependencies":[self.ids["model"]]})
        self.rt.transition(self.rev(),"T1","running")
        with self.assertRaises(ValueError): self.rt.transition(self.rev(),"T1","completed",outputs=[self.ids["code"]])
        _,result=self.validated(); self.rt.transition(self.rev(),"T1","completed",outputs=[result])
        self.assertEqual(self.rt.read()["copilot"]["tasks"]["T1"]["status"],"completed")

    def test_fresh_runtime_recovers_current_facts(self):
        _,result=self.validated()
        again=Runtime(self.root)
        self.assertEqual(self.rev(),again.read()["copilot"]["revision"])
        self.assertIn(result,project_status(self.root,again.read())["current_objects"].values())


if __name__=="__main__": unittest.main()
