"""Fresh historical MCM case using the unchanged canonical Runtime contracts."""
from __future__ import annotations
import argparse,json,shutil,sys
from pathlib import Path
EXAMPLE=Path(__file__).resolve().parent
ROOT=EXAMPLE.parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import copilot_domain as d
from copilot_store import Store
from copilot_runtime import Runtime,project_status
from copilot_delivery import Delivery

LIMITATIONS=["Synthetic uncalibrated demands; no empirical traffic-prediction claim",
    "Divisible fluid, fixed exit fraction, no lane geometry or spillback storage limit",
    "Only the declared finite policy grid is compared; no global optimality",
    "Historical example; no human final review or formal submission"]

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

def run_example(workspace,horizon=600):
    if type(horizon) is not int or not 12<=horizon<=3600:raise ValueError('horizon must be an integer in [12, 3600] seconds')
    workspace=Path(workspace).resolve()
    if workspace.exists() and any(workspace.iterdir()):raise FileExistsError("Workspace must be new or empty")
    workspace.mkdir(parents=True,exist_ok=True)
    for name in ("driver.py","traffic_model.py","checker.py","problem.md"):
        shutil.copy2(EXAMPLE/name,workspace/name)
    state=json.loads((ROOT/"templates/shared/decision_log.json").read_text(encoding="utf-8"))
    # Initial template selection is before authority creation, not a mutation.
    state["competition"]="mcm"
    Store(workspace/"state/decision_log.json").create(state)
    rt=Runtime(workspace);rev=lambda:rt.read()["copilot"]["revision"]
    rt.configure(rev(),question_count=1,problem_year=2009,rules_year=2027,evaluation_mode="historical_benchmark",stage=2,letter="A",title="MCM 2009 A 环岛交通控制：合成数据演示")
    def reg(kind,key,payload,deps=(),files=()):
        return rt.register(rev(),kind,key,payload,dependencies=deps,files=files)["result"]["object_id"]
    reqs=[{"req_id":f"REQ-Q1-{i:03d}","question":"Q1","source_anchor":"Official 2009 MCM A; locally paraphrased problem.md",
        "requested_action":action,"outputs":[output],"units":["vehicle","s"],"acceptance_evidence":[check]} for i,(action,output,check) in enumerate([
        ("明确并比较交通控制目标","control_objective","conservation"),
        ("比较环岛内车辆优先与入环车辆优先两类控制规则","control_comparison","capacity_and_policy"),
        ("评估满足约束的信号绿灯时长分配","signal_timing","capacity_and_policy"),
        ("比较合成交通场景并分析交通需求变化的影响","scenario_sensitivity","selection_and_sensitivity"),
        ("形成面向工程人员的技术摘要","technical_summary","technical_summary")],1)]
    contract=reg("ProblemContract","problem.Q1",{"question":"Q1","title":"第一问：环岛交通控制与信号配时","contract_id":"PC-MCM-A",
        "source_files":[{"path":"problem.md","sha256":d.sha256_file(workspace/"problem.md"),"source_kind":"provided_problem"}],"requirements":reqs})
    c=rt.read()["copilot"]["objects"][contract]["payload"]
    entries=[d.ParameterEntry(parameter_id="horizon",symbol="T",meaning="合成交通实验的模拟时长",unit="s",category="human_set",basis="bounded demonstration; transient behavior is retained",candidate_range=[12,3600],current_value=horizon).to_dict(),
        d.ParameterEntry(parameter_id="capacity",symbol="c",meaning="假定的路口通行能力",unit="vehicle/s",category="human_set",basis="synthetic junction capacity, not calibrated",current_value=0.8,
            candidate_range=[0.1,2.0],sensitivity_required=True,sensitivity_plan="Demand factor grid changes demand-to-capacity ratio").to_dict()]
    checks=[{"check_id":key,"method":method,"criterion":criterion} for key,method,criterion in (
        ("conservation","Independent ledger accounting","Nonnegative queues and exact flow conservation within numeric tolerance"),
        ("capacity_and_policy","Independent junction and signal checks","All time steps respect declared service priority and green phases"),
        ("selection_and_sensitivity","Grid completeness and metric recomputation","All demand cases/controllers occur once and finite-grid selected score is minimal"),
        ("technical_summary","Read generated compact summary","Compact engineer-facing description retains synthetic, signal and safety limitations; pagination is separately audited"))]
    model=reg("ModelSpec","model.Q1",{"question":"Q1","spec_id":"MS-MCM-A","title":"流体排队模型 + 有限策略枚举","observation_unit":"junction and time step",
        "objective":{"formula_id":"F-score","direction":"minimize"},"inputs":[{"name":"synthetic demand and service capacity"}],"outputs":[{"name":"comparison and green plan"}],
        "data_contract":{"scope":"explicit synthetic scenario grid"},"solver":{"method":"deterministic fluid steps with finite policy enumeration"},"randomness":{"seed_policy":"deterministic; no sampling"},
        "constraints":[{"formula_id":"C-flow","expression":"arrived=departed+queued+circulating"}],
        "formulas":[{"formula_id":"F-score","expression":"J=(A+P*R)/D","latex":r"J=\frac{A+PR}{D}"}],
        "validation_plan":checks,"required_outputs":["results/traffic.json","results/comparison.csv","results/technical_summary.md"],"failure_conditions":["negative queues","flow loss","invalid control allocation"],
        "problem_contract_id":c["contract_id"],"problem_contract_semantic_hash":c["semantic_hash"],"requirement_ids":[r["req_id"] for r in reqs],
        "method_decision":{"selected_route":"fluid_grid","candidates":[{"route":"fluid_grid","decision":"selected","reason":"采用流体排队模型描述环岛和入口队列，通过流量守恒检查计算，并枚举预先声明的有限控制策略；用于合成数据教学演示，不表示已完成现场验证"}]},"parameters":entries},[contract])
    m=rt.read()["copilot"]["objects"][model]["payload"]
    params=reg("ParameterSet","params.Q1",d.ParameterSet(question="Q1",spec_id=m["spec_id"],modelspec_semantic_hash=m["semantic_hash"],modelspec_record_hash=m["record_hash"],version=1,entries=[d.ParameterEntry.from_dict(x) for x in entries]).to_dict(),[model])
    data=reg("DataContract","data.Q1",{"question":"Q1","inventory":d.seal_record({"entries":[{"path":"problem.md","sha256":d.sha256_file(workspace/"problem.md") }]}),
        "passport":d.seal_record({"fields":["scenario","rate","capacity"],"observation_unit":"synthetic junction","missing_policy":"reject","outlier_policy":"keep overload scenarios"}),
        "split":d.seal_record({"applicability":"not_applicable","not_applicable_reason":"Deterministic synthetic illustration, not fitted or held-out empirical data","evaluation_target":"deterministic_computation","claims_new_entity_generalization":False,"claims_predictive_performance":False})},[contract])
    code=reg("CodeManifest","code.Q1",{"question":"Q1","entrypoint":"driver.py","argv":["{python}","driver.py"]},[model],["driver.py","traffic_model.py"])
    plan=reg("ValidationPlan","plan.Q1",{"question":"Q1","checker":{"path":"checker.py","sha256":d.sha256_file(workspace/"checker.py"),"argv":["{python}","{checker}","{run}","{report}"]},"checks":checks},[model])
    rt.task(rev(),"T-MCM-model",{"title":"运行有限控制策略并独立核验流量收支","role":"coder","requirements":[r["req_id"] for r in reqs],"dependencies":[model]})
    rt.transition(rev(),"T-MCM-model","running")
    run=rt.execute(rev(),"Q1",["{python}","driver.py"],["results/traffic.json","results/comparison.csv","results/technical_summary.md"],dependencies=[model,params,data,code,plan],timeout=180)["result"]
    if run["status"]!="executed":raise RuntimeError(run)
    validated=rt.validate_run(rev(),run["object_id"],"checker.py",["{python}","{checker}","{run}","{report}"],timeout=180)["result"]
    if not validated["passed"]:raise RuntimeError(validated)
    for req in reqs:rt.cover(rev(),req["req_id"],{req["outputs"][0]:validated["result_id"]})
    rt.transition(rev(),"T-MCM-model","completed",outputs=[validated["result_id"]])
    cp=rt.read()["copilot"];record=cp["objects"][run["object_id"]];result=cp["objects"][validated["result_id"]]["payload"]
    validation_path=next(f["path"] for f in cp["objects"][validated["validation_id"]]["files"] if f["path"].endswith("sealed-report.json"))
    claim_text=f"The synthetic experiment compared {result['metrics']['candidate_count']} controller cases in {result['metrics']['scenario_count']} demand scenarios and independently checked {result['metrics']['checked_steps']} time steps."
    claim=rt.claim(rev(),{"claim_id":"CLAIM-MCM","claim":claim_text,"claim_type":"numerical","paper_anchor":"paper_workspace/mcm.md","formal_run_id":run["object_id"],"requirement_ids":[r["req_id"] for r in reqs],
        "limitations":LIMITATIONS,"data_sources":[record["payload"]["data_version"]],"code_locations":["traffic_model.py"],"validation_evidence":[validation_path],
        "tables":[next(f["path"] for f in record["payload"]["outputs"] if f["path"].endswith("comparison.csv"))]},[validated["result_id"]])["result"]["claim_id"]
    paper=workspace/"paper_workspace/mcm.md";paper.parent.mkdir()
    paper.write_text("# Traffic circle experiment\n\n"+claim_text+" [[claim:"+claim+"]]\n\nSynthetic fluid illustration only. No field calibration or formal contest readiness.\n",encoding="utf-8")
    section=Delivery(workspace).section(rev(),"paper.Q1","paper_workspace/mcm.md",[claim])["result"]["section_id"]
    rt.task(rev(),"T-MCM-technical-summary",{"title":"复核模型适用边界并撰写面向工程人员的技术摘要","role":"writer","dependencies":[validated["result_id"]],"requirements":[reqs[-1]["req_id"]]})
    rt.configure(rev(),stage=7)
    report={"case":"MCM 2009 A","synthetic":True,"old_results_reused":False,"objects":{"contract":contract,"model":model,"params":params,"data":data,"code":code,"plan":plan,"run":run["object_id"],"validation":validated["validation_id"],"result":validated["result_id"],"claim":claim,"section":section},"metrics":result["metrics"],"status":project_status(workspace,rt.read())}
    write(workspace/"example-report.json",report)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--workspace",type=Path,required=True);p.add_argument("--horizon",type=int,default=600)
    args=p.parse_args();print(json.dumps(run_example(args.workspace,args.horizon),ensure_ascii=False,indent=2))
