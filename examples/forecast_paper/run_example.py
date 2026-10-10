"""Original synthetic forecast -> real run/check -> sourced chapter -> Word/PDF.

Create-only, local, not a contest paper or predictive-performance claim.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_domain as d
from copilot_data import prepare
from copilot_delivery import Delivery
from copilot_paper_export import export
from copilot_runtime import Runtime, project_status
from copilot_store import Store
from copilot_view import snapshot


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run_example(workspace, *, pdf=False, documents=True):
    root = Path(workspace).resolve(); root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()): raise ValueError("演示须使用新建或空目录，不覆盖已有项目")
    for name in ("solver.py", "checker.py"): shutil.copy2(Path(__file__).parent/name, root/name)
    shutil.copy2(ROOT / "templates/shared/code_starter/forecasting.py", root/"forecasting.py")
    declaration = json.loads((ROOT / "templates/copilot/forecast_spec.json").read_text(encoding="utf-8"))
    write(root/"forecast_spec.json", declaration)
    (root/"problem.md").write_text("Original synthetic Q1: direct rolling forecasts on y=10+2t. Each value is published one hour after observation. Evaluate horizons one and two on three fixed origins, with a last-published-value baseline. No real forecasting claim.\n", encoding="utf-8")
    start = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    with (root/"series.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["observed_at", "published_at", "value"])
        writer.writerows(((start+timedelta(hours=i)).isoformat(), (start+timedelta(hours=i+1)).isoformat(), 10+2*i) for i in range(17))
    table_spec = {"schema_version": "1.0", "question": "Q1", "source": {"path": "series.csv"},
                  "columns": [{"name": "time", "source": "observed_at", "type": "string"}, {"name": "available_at", "source": "published_at", "type": "string"},
                              {"name": "value", "source": "value", "type": "number", "unit": "1"}], "unique_keys": ["time"]}
    write(root/"table_spec.json", table_spec); prepared = prepare(root, "table_spec.json", "normalized/v1")
    Store(root/"state/decision_log.json").create(json.loads((ROOT/"templates/shared/decision_log.json").read_text(encoding="utf-8")))
    rt = Runtime(root)
    def rev(): return rt.read()["copilot"]["revision"]
    def reg(kind, key, payload, dependencies=(), files=()):
        return rt.register(rev(), kind, key, payload, dependencies=dependencies, files=files)["result"]["object_id"]
    rt.configure(rev(), question_count=1, problem_year=2026, rules_year=2026, evaluation_mode="historical_benchmark", title="合成预测与论文导出演示")
    checks = [{"check_id": key, "method": method, "criterion": criterion, "tolerance": tolerance, "unit": unit} for key,method,criterion,tolerance,unit in
              (("known_line", "independent analytic line", "Predictions match original y=10+2t within absolute tolerance; input series and delay exactly match the synthetic case", 1e-10, "1"),
               ("causality", "independent publication timestamps and eligible pairs", "Every train label is published before origin; each feature before its decision; exact declared origin/horizon coverage; scaler uses eligible training pairs only", 0, "timestamp and row count"),
               ("metric_recompute", "independent error arithmetic", "Both candidate and baseline MAE use every same forecast instance; declared display rounding to twelve decimals", 1e-10, "1"))]
    problem = reg("ProblemContract", "problem.Q1", {"question": "Q1", "contract_id": "PC-SYN-FORECAST", "title": "Original delayed synthetic series",
                  "source_files": [{"path": "problem.md", "sha256": d.sha256_file(root/"problem.md"), "source_kind": "provided_synthetic_problem"}],
                  "requirements": [{"req_id": "REQ-Q1-001", "question": "Q1", "source_anchor": "problem.md", "requested_action": "Run and independently check causal known-case forecasts", "outputs": ["candidate_mae", "baseline_mae"], "units": ["1"], "acceptance_evidence": [c["check_id"] for c in checks]}]})
    pc = rt.read()["copilot"]["objects"][problem]["payload"]
    parameter = d.ParameterEntry(parameter_id="window", symbol="W", meaning="fixed synthetic training pair window", unit="row", category="human_set", basis="predeclared known case, not tuned predictive evidence", current_value=4, candidate_range=[3, 5]).to_dict()
    conditions = {"time_grid": "每小时一个观测，发布时间延迟一小时", "information": "仅使用各起点已发布数据", "horizon": "相同的一小时与两小时预测", "boundary": "非储能模型，SOC 边界不适用", "commitments": "离线预测，无购电承诺", "costs": "比较预测 MAE，费用不适用", "split": "三个固定起点，六个预测实例，允许目标时间重叠", "budget": "固定方案，无自动调参；训练窗口由登记参数决定"}
    comparison = {"schema_version": "1.0", "group": "synthetic-mae", "title": "同一批预测窗口的误差",
                  "source_files": [{"path": path, "sha256": d.sha256_file(root/path)} for path in ("series.csv", "forecast_spec.json")],
                  "variants": [{"id": key, "label": label, "method": method, "backend": backend, "metric_path": "/"+key, "direction": "lower", "context": dict(conditions)} for key,label,method,backend in
                               (("candidate_mae", "滞后线性回归", "逐起点重新拟合滞后线性回归", "sklearn LinearRegression"), ("baseline_mae", "最后已发布值基线", "使用起点最后已发布的观测值", "标准库数值运算"))]}
    model = reg("ModelSpec", "model.Q1", {"question": "Q1", "spec_id": "MS-SYN-FORECAST", "title": "Causal direct lag forecast",
                "observation_unit": "hourly published synthetic target", "objective": {"formula_id": "F1", "direction": "minimize heldout MAE"},
                "inputs": [{"name": "explicit synthetic time and publication series"}], "outputs": [{"name": name, "unit": unit, "meaning": meaning} for name,unit,meaning in
                             (("candidate_mae", "1", "候选回归方案 MAE"), ("baseline_mae", "1", "最后已发布值基线 MAE"), ("forecast_instances", "次", "同一批预测实例数量"))],
                "data_contract": {"scope": "synthetic declared publication times only", "comparison": comparison}, "solver": {"method": "direct lag LinearRegression per origin/horizon"},
                "randomness": {"seed_policy": "deterministic fixed known line"}, "constraints": [{"formula_id": "C1", "expression": "feature.available_at<=decision; label.available_at<=origin; per-origin train-only preprocessing"}],
                "formulas": [{"formula_id": "F1", "expression": "MAE=\\frac{E}{N}"}], "validation_plan": checks, "required_outputs": ["result.json", "forecast.png"],
                "failure_conditions": ["future data leakage", "missing window", "known analytic line differs"], "problem_contract_id": pc["contract_id"], "problem_contract_semantic_hash": pc["semantic_hash"],
                "requirement_ids": ["REQ-Q1-001"], "method_decision": {"selected_route": "direct_lag", "candidates": [{"route": "direct_lag", "decision": "selected", "reason": "original known-case fixture; compare with simple last-published-value baseline"}]}, "parameters": [parameter]}, [problem])
    model_payload = rt.read()["copilot"]["objects"][model]["payload"]
    params = reg("ParameterSet", "params.Q1", d.ParameterSet(question="Q1", spec_id=model_payload["spec_id"], modelspec_semantic_hash=model_payload["semantic_hash"], modelspec_record_hash=model_payload["record_hash"], version=1, entries=[d.ParameterEntry.from_dict(parameter)]).to_dict(), [model])
    data = reg("DataContract", "data.Q1", json.loads((root/prepared["contract"]).read_text(encoding="utf-8")), [problem])
    code = reg("CodeManifest", "code.Q1", {"question": "Q1", "entrypoint": "solver.py", "argv": ["{python}", "solver.py"]}, [model], ["solver.py", "forecasting.py", "forecast_spec.json"])
    plan = reg("ValidationPlan", "plan.Q1", {"question": "Q1", "checker": {"path": "checker.py", "sha256": d.sha256_file(root/"checker.py")}, "checks": checks}, [model])
    run = rt.execute(rev(), "Q1", ["{python}", "solver.py"], ["result.json", "forecast.png"], dependencies=[model, params, data, code, plan], timeout=60)["result"]
    if run["status"] != "executed": raise RuntimeError(run)
    checked = rt.validate_run(rev(), run["object_id"], "checker.py", ["{python}", "{checker}", "{run}", "{report}"], timeout=60)["result"]
    if not checked["passed"]: raise RuntimeError(checked)
    result_id = checked["result_id"]; rt.cover(rev(), "REQ-Q1-001", {name: result_id for name in ("candidate_mae", "baseline_mae")})
    result_obj = rt.read()["copilot"]["objects"][result_id]
    figure_path = next(f["path"] for f in result_obj["files"] if f["path"].endswith("forecast.png"))
    (root/"paper").mkdir()
    shutil.copy2(root/figure_path, root/"paper/forecast.png")
    figure_path = "paper/forecast.png"
    figure = reg("ArtifactRecord", "figure.forecast", {"artifact_type": "figure", "path": figure_path}, [result_id], [figure_path])
    validation_path = next(f["path"] for f in rt.read()["copilot"]["objects"][checked["validation_id"]]["files"] if f["path"].endswith("sealed-report.json"))
    claim_text = "候选方案的 MAE 为 0，最后已发布值基线的 MAE 为 5。"
    claim = rt.claim(rev(), {"claim_id": "CLAIM-SYN-MAE", "claim": claim_text, "claim_type": "numerical", "paper_anchor": "results",
                            "formal_run_id": run["object_id"], "data_sources": [data], "code_locations": ["solver.py"],
                            "validation_evidence": [validation_path], "figures": [figure_path],
                            "requirement_ids": ["REQ-Q1-001"], "limitations": ["Only original known synthetic line; twelve decimal MAE display; no real forecasting performance"]}, [result_id])["result"]["claim_id"]
    source = "# 合成预测与论文导出验证\n\n这是自建的已知直线算例，用于检查发布时间、滚动窗口及论文导出链路。下列误差只描述该算例，不能代表真实比赛或预测效果。\n\n## 评价方法\n\nE 表示同一批预测实例的绝对误差之和，N 表示实例数量。\n\n$$MAE=\\frac{E}{N}$$\n\n## 计算结果\n\n| 方案 | MAE | 单位 |\n| --- | --- | --- |\n| 滞后线性回归 | 0 | 无量纲 |\n| 最后已发布值基线 | 5 | 无量纲 |\n"+claim_text+" [[claim:"+claim+"]]\n\n![合成序列与固定预测起点]("+figure_path+")\n\n[[figure:1]] 合成序列与固定预测起点\n\n来源为本例生成的合成数据和本次实际计算。原稿文字保持不变，图像来自已绑定的结果文件。\n\n## 参考资料\n\n滚动评价与训练集预处理的设计参考 scikit learn 官方说明。\nhttps://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html\nhttps://scikit-learn.org/stable/common_pitfalls.html\n"
    source = source.replace("[[figure:1]] 合成序列与固定预测起点", "[[figure:1]]\n\n合成序列与固定预测起点")
    (root/"paper/results.md").write_text(source, encoding="utf-8")
    section = Delivery(root).section(rev(), "paper.results", "paper/results.md", [claim], source_bindings=[], structure=[{"kind": "figure", "number": 1, "artifact_id": figure}])["result"]["section_id"]
    write(root/"paper/source_contract.json", {"version": "0.1", "sections": [section], "supplements": []})
    exported = export(root, "paper/source_contract.json", "paper/预测核验示例.docx", expected_revision=rev(), pdf="paper/预测核验示例.pdf" if pdf else None) if documents else None
    output = {"synthetic": True, "objects": {"contract": problem, "model": model, "params": params, "data": data, "code": code, "plan": plan,
              "run": run["object_id"], "result": result_id, "validation": checked["validation_id"], "section": section}, "export": exported,
              "metrics": result_obj["payload"]["metrics"], "status": project_status(root, rt.read()), "view": snapshot(root)}
    write(root/"example-report.json", output); return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--workspace", type=Path, required=True); p.add_argument("--pdf", action="store_true")
    a=p.parse_args(); report=run_example(a.workspace, pdf=a.pdf)
    print(json.dumps({k: report[k] for k in ("synthetic", "metrics", "export")}, ensure_ascii=False, indent=2))
