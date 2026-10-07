"""Rebuild the historical 2018B benchmark through the Copilot Runtime.

Creates a new workspace only. Full: three official parameter groups, 32 seeds,
1,524 two-process candidates and 12 representative traces. --smoke uses one
group and two seeds, and is explicitly not a full historical benchmark.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

EXAMPLE = Path(__file__).resolve().parent
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_domain as domain
from copilot_store import Store
from copilot_runtime import Runtime, project_status
from copilot_delivery import Delivery

CHECKER_ARGV = ["{python}", "{checker}", "{run}", "{report}"]
DRIVER_ARGV = ["{python}", "driver.py"]
CODE_FILES = ["driver.py", "rgv_simulator.py", "verify_schedule.py", "test_rgv.py"]
CASE_FILES = ["Case_1_ result_E.xls", "Case_2_ result_E.xls", "Case_3_ result_1_E.xls", "Case_3_ result_2_E.xls"]
LIMITATIONS = ["Limited dispatch policies and fixed-tool assignments; no global optimality proof",
              "Fault probability interpreted per machining start, with assumed uniform failure and repair timing",
              "At most one intermediate part; immediate clean/delivery; full service time charged for unload-only",
              "Fixed healthy-selected configuration in fault sensitivity, not scenario-wise reoptimization",
              "Monte Carlo mean intervals describe simulation sampling error, not factory generalization",
              "Historical benchmark; no human final review, current rules lock, formal submission or receipt"]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def required_outputs(question, groups):
    if question == "Q1":
        return ["results/model_description.json", "results/kernel_tests.json"]
    return ["results/experiment_summary.json", "results/all_feasibility_checks.json", "results/healthy_comparison.csv",
            "results/assignment_search.csv", "results/table_manifest.json", "support_materials/official_parameters.json"] + [
            f"results/trace_group{g}_{mode}_{suffix}.json" for g in groups for mode in ("single", "two")
            for suffix in ("healthy", "fault_seed_0")] + [f"results/tables/{name}" for name in CASE_FILES]


def requirement_rows(question, groups):
    rows = []
    if question == "Q1":
        targets = [("single", "建立单工序调度模型及算法", ["single_algorithm"]),
                   ("two", "建立固定刀具双工序模型及算法", ["two_algorithm"]),
                   ("fault", "建立含故障与维修的因果调度算法", ["fault_algorithm"])]
        for key, action, outputs in targets:
            rows.append({"req_id": f"REQ-Q1-{key}", "question": question, "source_anchor": "Problem B page 1 Task one, situations (1)–(3)",
                         "requested_action": action, "outputs": outputs, "units": ["s", "piece"], "acceptance_evidence": ["algorithm_cases"]})
    else:
        for group in groups:
            for case in ("single", "two", "fault"):
                outputs = [f"group{group}_{case}_schedule"] if case != "fault" else [f"group{group}_fault_single", f"group{group}_fault_two"]
                rows.append({"req_id": f"REQ-Q2-G{group}-{case}", "question": question,
                             "source_anchor": f"Problem B Task two, Table 1 parameter group {group}; situation {case}",
                             "requested_action": "用题给参数复算调度轨迹及已清洗交付件数", "outputs": outputs,
                             "units": ["s", "piece"], "acceptance_evidence": ["trace_replay"]})
        rows += [{"req_id": "REQ-Q2-efficiency", "question": question, "source_anchor": "Problem B Task two: operation efficiency",
                  "requested_action": "比较有限候选、基线及故障情景效率", "outputs": ["efficiency_comparison"], "units": ["piece/shift"],
                  "acceptance_evidence": ["tuning_accounting", "monte_carlo"]},
                 {"req_id": "REQ-Q2-tables", "question": question, "source_anchor": "Problem B page 2 Appendix 2",
                  "requested_action": "填写官方结果表并逐个数字单元格回读核验", "outputs": ["official_result_tables"], "units": ["s", "piece"],
                  "acceptance_evidence": ["official_tables"]}]
    for index, row in enumerate(rows, 1):
        row["req_id"] = f"REQ-{question}-{index:03d}"
    return rows


def parameters(groups, seed_count):
    table = json.loads((EXAMPLE / "assets/official_parameters.json").read_text(encoding="utf-8"))["groups"]
    return [domain.ParameterEntry(parameter_id="official_table", symbol="T", meaning="Official Table 1 timing parameters",
                unit="s", category="external", external_source="assets/CUMCM-2018-Problem-B-English.pdf page 2 Table 1", current_value=table).to_dict(),
            domain.ParameterEntry(parameter_id="groups", symbol="G", meaning="Parameter groups executed in this profile", unit="index", category="human_set",
                basis="Full benchmark executes all three groups; smoke covers one group only", candidate_range=[1, 3], current_value=groups,
                affects_core_conclusion=False).to_dict(),
            domain.ParameterEntry(parameter_id="seed_count", symbol="N", meaning="Monte Carlo repetitions per configuration", unit="repetitions", category="human_set",
                basis="Retain the earlier 32-seed protocol; smoke is only a runtime integration test", candidate_range=[2, 32], current_value=seed_count,
                sensitivity_required=True, sensitivity_plan="Compare prefix16 with full32 and report normal-approximation mean intervals").to_dict()]


def make_sources(runtime, question, groups, seeds, previous_result=None):
    root = runtime.root
    def reg(kind, key, payload, dependencies=(), files=()):
        return runtime.register(runtime.read()["copilot"]["revision"], kind, key, payload, dependencies=dependencies, files=files)["result"]["object_id"]
    source = "assets/CUMCM-2018-Problem-B-English.pdf"
    rows = requirement_rows(question, groups)
    contract = reg("ProblemContract", f"problem.{question}", {"question": question, "title": "2018B Task " + question[-1], "contract_id": f"PC-2018B-{question}",
        "source_files": [{"path": source, "sha256": domain.sha256_file(root / source), "source_kind": "provided_problem"},
                         {"path": "assets/CUMCM-2018-Problem-B-English-Appendix-1.pdf", "sha256": domain.sha256_file(root / "assets/CUMCM-2018-Problem-B-English-Appendix-1.pdf"), "source_kind": "provided_attachment"}],
        "requirements": rows})
    c = runtime.read()["copilot"]["objects"][contract]["payload"]
    planned = ([{"check_id": "algorithm_cases", "method": "Independent execution of deterministic, causal-dispatch and negative kernel tests",
                 "criterion": "All retained algorithm tests pass with both processing modes and all official groups"}] if question == "Q1" else [
        {"check_id": "trace_replay", "method": "Independent command replay", "criterion": "All representative schedules obey official times, machine tools, paw capacity, causality, clean/delivery and shift-return conditions"},
        {"check_id": "tuning_accounting", "method": "Enumerated-space and selected maximum check", "criterion": "All fixed-tool assignments and both declared policies occur exactly once; selected trace equals observed finite-search maximum"},
        {"check_id": "monte_carlo", "method": "Recompute sample statistics and inspect complete seed/scenario ledgers", "criterion": "All fault and sensitivity configurations have declared samples, consistent means, deviations and intervals"},
        {"check_id": "official_tables", "method": "Read official-format XLS cells independently", "criterion": "Official sheet names, headers, row counts and every numeric cell agree with independently replayed traces"}])
    entries = parameters(groups, seeds)
    outputs = required_outputs(question, groups)
    model = reg("ModelSpec", f"model.{question}", {"question": question, "spec_id": f"MS-2018B-{question}", "title": "Retained causal discrete-event heuristic",
        "observation_unit": "CNC event and exclusive RGV command", "objective": {"formula_id": "F-delivered", "direction": "maximize"},
        "inputs": [{"name": "official timing table"}], "outputs": [{"name": item} for item in outputs],
        "data_contract": {"scope": "official constants and original blank result workbooks"}, "solver": {"method": "event simulation with finite policy/configuration enumeration"},
        "randomness": {"seed_policy": "separate failure and timing RNG streams; fixed seed range"},
        "constraints": [{"formula_id": "C-exclusive", "expression": "RGV executes one non-overlapping command"},
                        {"formula_id": "C-tool", "expression": "fixed machine tools and ordered two-phase transfer"},
                        {"formula_id": "C-shift", "expression": "return to position zero by 28800 seconds"}],
        "formulas": [{"formula_id": "F-delivered", "expression": "count of non-discarded products cleaned and delivered by shift end"}],
        "validation_plan": planned, "required_outputs": outputs, "failure_conditions": ["failed replay", "missing official case", "input hash drift"],
        "problem_contract_id": c["contract_id"], "problem_contract_semantic_hash": c["semantic_hash"], "requirement_ids": [row["req_id"] for row in rows],
        "method_decision": {"selected_route": "retained_finite_heuristics", "candidates": [{"route": "retained_finite_heuristics", "decision": "selected", "reason": "reproduce the existing tested implementation without claiming a new optimal solver"}]},
        "parameters": entries}, [contract] + ([previous_result] if previous_result else []))
    m = runtime.read()["copilot"]["objects"][model]["payload"]
    params = reg("ParameterSet", f"params.{question}", domain.ParameterSet(question=question, spec_id=m["spec_id"],
        modelspec_semantic_hash=m["semantic_hash"], modelspec_record_hash=m["record_hash"], version=1,
        entries=[domain.ParameterEntry.from_dict(value) for value in entries]).to_dict(), [model])
    inventory = [{"path": path.relative_to(root).as_posix(), "sha256": domain.sha256_file(path)} for path in sorted((root / "assets").iterdir()) if path.is_file()]
    data = reg("DataContract", f"data.{question}", {"question": question,
        "inventory": domain.seal_record({"entries": inventory}),
        "passport": domain.seal_record({"fields": ["group", "move", "single", "first", "second", "odd", "even", "clean"],
            "observation_unit": "official timing parameter group", "missing_policy": "reject absent constants", "outlier_policy": "preserve official constants; no silent clipping"}),
        "split": domain.seal_record({"applicability": "not_applicable", "not_applicable_reason": "Known deterministic constants and prescribed scenario simulation, not a learned predictor",
            "evaluation_target": "deterministic_computation", "claims_new_entity_generalization": False, "claims_predictive_performance": False})}, [contract])
    code = reg("CodeManifest", f"code.{question}", {"question": question, "entrypoint": "driver.py", "argv": DRIVER_ARGV}, [model], CODE_FILES)
    plan = reg("ValidationPlan", f"plan.{question}", {"question": question, "checker": {"path": "checker.py", "sha256": domain.sha256_file(root / "checker.py"), "argv": CHECKER_ARGV}, "checks": planned}, [model], ["verify_schedule.py", "test_rgv.py"])
    return {"contract": contract, "model": model, "params": params, "data": data, "code": code, "plan": plan}, rows


def run_benchmark(workspace, smoke=False):
    began = time.perf_counter()
    workspace = Path(workspace).resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError("Benchmark workspace must be new or empty; existing artifacts will not be overwritten")
    workspace.mkdir(parents=True, exist_ok=True)
    groups, seeds = ([1], 2) if smoke else ([1, 2, 3], 32)
    for name in CODE_FILES + ["checker.py"]:
        shutil.copy2(EXAMPLE / name, workspace / name)
    shutil.copytree(EXAMPLE / "assets", workspace / "assets")
    write(workspace / "source_manifest.json", {"algorithm_origin": "User's retained 2018B reproduction implementation, reused byte-for-byte",
        "official_page": "https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html",
        "source_files": [{"path": path.relative_to(workspace).as_posix(), "sha256": domain.sha256_file(path)}
                         for path in sorted(workspace.rglob("*")) if path.is_file()], "old_results_reused": False})
    state = json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8"))
    Store(workspace / "state/decision_log.json").create(state)
    runtime = Runtime(workspace)
    revision = lambda: runtime.read()["copilot"]["revision"]
    runtime.configure(revision(), question_count=2, problem_year=2018, rules_year=2026, evaluation_mode="historical_benchmark", stage=2, letter="B", title="2018B retained-solver historical benchmark")
    delivered, previous = {}, None
    for question in ("Q1", "Q2"):
        print(f"{question}: freezing source contracts", flush=True)
        ids, requirements = make_sources(runtime, question, groups, seeds, previous)
        task_id = f"T-{question}"
        runtime.task(revision(), task_id, {"title": f"Execute and independently validate {question}", "role": "coder", "requirements": [x["req_id"] for x in requirements],
                     "dependencies": [ids["model"]], "depends_on": ["T-Q1"] if question == "Q2" else []})
        runtime.transition(revision(), task_id, "running")
        runtime.configure(revision(), stage=5)
        execution = runtime.execute(revision(), question, DRIVER_ARGV, required_outputs(question, groups),
                    dependencies=[ids[key] for key in ("model", "params", "data", "code", "plan")], timeout=600)["result"]
        if execution["status"] != "executed":
            raise RuntimeError(f"{question} execution failed: {execution}; inspect its receipt and stderr")
        run_id = execution["object_id"]
        checked = runtime.validate_run(revision(), run_id, "checker.py", CHECKER_ARGV, timeout=600)["result"]
        if not checked["passed"]:
            raise RuntimeError(f"{question} independent validation failed: {checked}")
        result_id, previous = checked["result_id"], checked["result_id"]
        for requirement in requirements:
            runtime.cover(revision(), requirement["req_id"], {output: result_id for output in requirement["outputs"]})
        runtime.transition(revision(), task_id, "completed", outputs=[result_id])
        cp = runtime.read()["copilot"]
        run = cp["objects"][run_id]
        result = cp["objects"][result_id]["payload"]
        validation = next(x["path"] for x in cp["objects"][checked["validation_id"]]["files"] if x["path"].endswith("sealed-report.json"))
        if question == "Q1":
            claim_text = (f"在限定的离散事件调度策略下，本次 {result['metrics']['algorithm_tests']} 项算法边界测试通过，"
                          "覆盖单工序、双工序与故障事件处理；该结论不构成全局最优性证明。")
            claim_type, tables = "method", []
        else:
            metrics = result["metrics"]
            claim_text = (f"本次独立回放 {metrics['trace_count']} 条代表轨迹，核对 {metrics['workbooks']} 份结果表的 {metrics['sheets_checked']} 个工作表；"
                          f"有限枚举记录 {metrics['tuning_candidates']} 个双工序候选，每种故障或敏感性配置使用 {metrics['seed_count']} 个种子。")
            claim_type = "numerical"
            tables = [x["path"] for x in run["payload"]["outputs"] if x["path"].endswith("healthy_comparison.csv")]
        claim = runtime.claim(revision(), {"claim_id": f"CLAIM-{question}", "claim": claim_text, "claim_type": claim_type,
            "paper_anchor": f"paper_workspace/{question}.md", "formal_run_id": run_id, "requirement_ids": [x["req_id"] for x in requirements],
            "limitations": LIMITATIONS, "data_sources": [run["payload"]["data_version"]], "code_locations": ["rgv_simulator.py"],
            "validation_evidence": [validation], "tables": tables}, [result_id])["result"]["claim_id"]
        paper = workspace / "paper_workspace" / f"{question}.md"
        paper.parent.mkdir(exist_ok=True)
        paper.write_text(f"# {question} 可追溯结果片段\n\n{claim_text} [[claim:{claim}]]\n\n本片段用于历史回归。实际分布、清洗机械动作和候选策略范围仍有建模限制，未完成团队人工终审。\n", encoding="utf-8")
        section = Delivery(workspace).section(revision(), f"paper.{question}", paper.relative_to(workspace).as_posix(), [claim])["result"]["section_id"]
        delivered[question] = {**ids, "run": run_id, "validation": checked["validation_id"], "result": result_id, "claim": claim,
                               "section": section, "metrics": result["metrics"], "directory": run["execution"]["directory"]}
        # Readable copies are explicit projections; original immutable run paths
        # remain the source of every Claim and validation binding.
        projection = workspace / "results" / question
        shutil.copytree(workspace / run["execution"]["directory"] / "results", projection)
        runtime.register(revision(), "ArtifactRecord", f"projection.{question}", {"path": (projection / ("model_description.json" if question == "Q1" else "experiment_summary.json")).relative_to(workspace).as_posix(),
            "artifact_type": "readable_projection", "source_result": result_id}, dependencies=[result_id],
            files=[path.relative_to(workspace).as_posix() for path in projection.rglob("*") if path.is_file()])
        print(f"{question}: executed, independently verified, requirements covered, paper section bound", flush=True)
    runtime.configure(revision(), stage=9)
    facts = project_status(workspace, runtime.read())
    report = {"profile": "smoke" if smoke else "full", "problem_year": 2018, "rules_year": 2026, "evaluation_mode": "historical_benchmark",
        "question_count": 2, "groups": groups, "seed_count": seeds, "old_results_reused": False, "elapsed_seconds": time.perf_counter() - began,
        "objects": delivered, "facts": facts, "limitations": LIMITATIONS}
    write(workspace / "benchmark_report.json", report)
    lines = ["# 2018B 历史旧题端到端重跑", "", "本次从源代码真实重跑，没有复制旧结果。原题为两个任务，三种情形被拆入需求矩阵，未把工况伪造成子问。", "",
             f"模式：{'低成本 smoke，仅第一组参数；不能代替全例验收' if smoke else '完整历史基准：三组官方参数'}。用时 {report['elapsed_seconds']:.3f} 秒。",
             f"需求核验 {facts['requirements']['verified']}/{facts['requirements']['total']}；子问状态 {facts['requirements']['questions']}。", "",
             "数据链：ProblemContract → ModelSpec → ParameterSet → DataContract → CodeManifest → 预声明 ValidationPlan → 真实 Run → 独立 Validation → Result → Claim → PaperSection。",
             "算法原文件、独立重放验证器和原测试保留；驱动器将冻结参数快照交给原仿真器。CodeManifest 与 checker 的路径、哈希和 argv 在运行前锁定。", "",
             "## 本次可核验结果", "", "```json", json.dumps(delivered["Q2"]["metrics"], ensure_ascii=False, indent=2), "```", "",
             "正常工况枚举两种派工策略及全部固定刀具配置；故障与敏感性固定正常工况选定配置，每次都重新模拟，没有重优化。内部每次仿真均进行可行性重放，外部验证器再独立回放代表轨迹、核算候选全集、重算统计量并回读全部数字表格单元格。",
             "各查询输入、stdout/stderr、运行回执、输出哈希及密封验证报告保存在 `.copilot/runs/` 和 `.copilot/checks/`。`results/Q1/`、`results/Q2/` 是方便查看的投影，权威来源仍是状态中绑定的原始运行目录。", "",
             "## 提交状态", "", f"`submission.ready={facts['submission']['ready']}`；状态 `{facts['submission']['state']}`。", "",
             "未完成当届规则锁定、人工终审、正式论文/支撑包验收与实际提交；本演示没有将运行通过解释为可正式提交。", "",
             "## 限制", ""] + [f"- {item}" for item in LIMITATIONS]
    (workspace / "benchmark_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="New or empty output directory")
    parser.add_argument("--smoke", action="store_true", help="Only group one and two seeds; not full acceptance")
    args = parser.parse_args(argv)
    report = run_benchmark(args.workspace, args.smoke)
    print(json.dumps({"profile": report["profile"], "elapsed_seconds": report["elapsed_seconds"], "requirements": report["facts"]["requirements"],
                      "submission": report["facts"]["submission"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
