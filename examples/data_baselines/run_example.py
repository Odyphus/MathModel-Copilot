"""Data -> frozen contracts -> actual LP/regression -> independent checks -> rerun.

Run in a new directory. All numbers are synthetic known cases, not a contest
solution. Source and installed runtime layouts resolve their own resources.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_domain as d
from copilot_data import prepare
from copilot_runtime import Runtime, project_status
from copilot_store import Store


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def inputs(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise ValueError("合成演示须使用新建或空目录；不覆盖用户已有项目")
    for name in ("solver.py", "checker.py"):
        shutil.copy2(Path(__file__).parent / name, workspace / name)
    for name in ("optimization.py", "prediction.py"):
        shutil.copy2(ROOT / "templates/shared/code_starter" / name, workspace / name)
    (workspace / "problem.md").write_text("Synthetic Q1: aggregate daily energy procurement from three capped suppliers. No per-slot dispatch.\n"
                                         "Synthetic Q2: fit y=1+2x on rows 0..3 and check rows 4..5; fixed algebra example only.\n", encoding="utf-8")
    with (workspace / "power.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["日期", "时间", "功率"])
        for n in range(1, 145):
            writer.writerow(["2026-01-01" if n == 1 else "", f"{n // 6}:{n % 6 * 10:02}" if n < 144 else "0:00+1", 60])
    with (workspace / "regression.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "x", "y"])
        writer.writerows((i, i, 1 + 2 * i) for i in range(6))
    energy_spec = json.loads((ROOT / "templates/copilot/table_spec.json").read_text(encoding="utf-8"))
    energy_spec["source"] = {"path": "power.csv"}
    energy_spec["columns"][0]["fill"] = "forward"
    write(workspace / "power_spec.json", energy_spec)
    regression_spec = {"schema_version": "1.0", "question": "Q2", "source": {"path": "regression.csv"},
                       "columns": [{"name": "row", "source": "row", "type": "integer", "unit": "1"},
                                   {"name": "x", "source": "x", "type": "number", "unit": "1"},
                                   {"name": "y", "source": "y", "type": "number", "unit": "1"}], "unique_keys": ["row"],
                       "split": {"strategy": "fixed_ordered_holdout", "split_unit": "row", "preprocessing_scope": "train_only",
                                 "leakage_controls": ["fixed first four training rows; heldout rows do not fit scaler or mean"],
                                 "evaluation_target": "synthetic_known_case", "claims_new_entity_generalization": False,
                                 "claims_predictive_performance": False, "train_rows": [0, 1, 2, 3], "test_rows": [4, 5]}}
    write(workspace / "regression_spec.json", regression_spec)
    return {q: prepare(workspace, ref, "normalized/" + q + "/v1") for q, ref in (("Q1", "power_spec.json"), ("Q2", "regression_spec.json"))}


def run_example(workspace):
    workspace = Path(workspace).resolve()
    prepared = inputs(workspace)
    Store(workspace / "state/decision_log.json").create(json.loads((ROOT / "templates/shared/decision_log.json").read_text(encoding="utf-8")))
    rt = Runtime(workspace)
    def revision():
        return rt.read()["copilot"]["revision"]
    rt.configure(revision(), question_count=2, problem_year=2026, rules_year=2026, evaluation_mode="historical_benchmark", title="合成数据与算法基线验收")
    def reg(kind, key, payload, dependencies=(), files=()):
        return rt.register(revision(), kind, key, payload, dependencies=dependencies, files=files)["result"]["object_id"]
    ids = {}
    metrics = {}
    for q in ("Q1", "Q2"):
        optimization = q == "Q1"
        checks = ([{"check_id": "data_slots", "method": "independent slot and Decimal sum", "criterion": "144 exact 10-minute slots; each 10 kWh; total exactly 1440 kWh", "tolerance": 0, "unit": "kWh"},
                   {"check_id": "feasibility", "method": "independent bounds and demand sum", "criterion": "All supplier purchases in [0,600] kWh, total meets demand, cost recalculated", "tolerance": 1e-7, "unit": "kWh and currency; separate arithmetic checks"},
                   {"check_id": "known_optimum", "method": "analytic cheapest-first lower bound", "criterion": "Reported objective equals analytic bound for the declared aggregate supplier case", "tolerance": 1e-7, "unit": "currency"}]
                  if optimization else
                  [{"check_id": "analytic_predictions", "method": "known y=1+2x", "criterion": "Each heldout prediction equals the known analytic line within absolute tolerance", "tolerance": 1e-7, "unit": "1"},
                   {"check_id": "metric_recompute", "method": "independent absolute and squared errors", "criterion": "Reported heldout MAE and RMSE equal independent row arithmetic", "tolerance": 1e-7, "unit": "1"},
                   {"check_id": "train_baseline", "method": "training rows mean", "criterion": "Baseline uses training targets only and scaler mean equals training feature mean", "tolerance": 1e-7, "unit": "1"}])
        contract = reg("ProblemContract", "problem." + q, {"question": q, "contract_id": "PC-BASE-" + q, "title": "Original synthetic " + q,
                        "source_files": [{"path": "problem.md", "sha256": d.sha256_file(workspace / "problem.md"), "source_kind": "provided_synthetic_problem"}],
                        "requirements": [{"req_id": "REQ-" + q + "-001", "question": q, "source_anchor": "problem.md " + q,
                                          "requested_action": "solve and independently check synthetic known case", "outputs": ["objective" if optimization else "test_mae"],
                                          "units": ["currency" if optimization else "1"], "acceptance_evidence": [c["check_id"] for c in checks]}]})
        pc = rt.read()["copilot"]["objects"][contract]["payload"]
        parameter = (d.ParameterEntry(parameter_id="low_cost", symbol="p", meaning="synthetic first supplier price", unit="currency/kWh", category="human_set",
                                      basis="declared synthetic case only", current_value=2, candidate_range=[0, 4]).to_dict()
                     if optimization else d.ParameterEntry(parameter_id="train_count", symbol="n", meaning="fixed number of synthetic training rows", unit="row", category="human_set",
                                                           basis="fixed holdout before fitting; no performance tuning", current_value=4, candidate_range=[4, 4]).to_dict())
        model = reg("ModelSpec", "model." + q, {"question": q, "spec_id": "MS-BASE-" + q, "title": "Aggregate LP" if optimization else "Linear known-case regression",
                    "observation_unit": "aggregate daily energy" if optimization else "synthetic row", "objective": {"formula_id": "F1", "direction": "minimize" if optimization else "fit"},
                    "inputs": [{"name": "normalized attachment"}], "outputs": [{"name": "objective" if optimization else "test_mae", "unit": "currency" if optimization else "1"}],
                    "data_contract": {"scope": "explicit synthetic inputs"}, "solver": {"method": "SciPy HiGHS LP" if optimization else "sklearn linear regression"},
                    "randomness": {"seed_policy": "deterministic known case; fixed 42 if applicable"},
                    "constraints": [{"formula_id": "C1", "expression": "sum purchases>=1440; each in [0,600]" if optimization else "fixed rows 0..3 train; 4..5 heldout; preprocessing train only"}],
                    "formulas": [{"formula_id": "F1", "expression": "J=sum_i p_i*x_i" if optimization else "y=1+2*x"}], "validation_plan": checks,
                    "required_outputs": ["result.json"], "failure_conditions": ["known case differs", "wrong units or failed independent check"],
                    "problem_contract_id": pc["contract_id"], "problem_contract_semantic_hash": pc["semantic_hash"], "requirement_ids": ["REQ-" + q + "-001"],
                    "method_decision": {"selected_route": "known_baseline", "candidates": [{"route": "known_baseline", "decision": "selected", "reason": "minimum original synthetic case with independent analytic verification"}]},
                    "parameters": [parameter]}, [contract])
        spec = rt.read()["copilot"]["objects"][model]["payload"]
        params = reg("ParameterSet", "params." + q, d.ParameterSet(question=q, spec_id=spec["spec_id"], modelspec_semantic_hash=spec["semantic_hash"], modelspec_record_hash=spec["record_hash"],
                      version=1, entries=[d.ParameterEntry.from_dict(parameter)]).to_dict(), [model])
        data = reg("DataContract", "data." + q, json.loads((workspace / prepared[q]["contract"]).read_text(encoding="utf-8")), [contract])
        code = reg("CodeManifest", "code." + q, {"question": q, "entrypoint": "solver.py", "argv": ["{python}", "solver.py"]}, [model], ["solver.py", "optimization.py", "prediction.py"])
        plan = reg("ValidationPlan", "plan." + q, {"question": q, "checker": {"path": "checker.py", "sha256": d.sha256_file(workspace / "checker.py")}, "checks": checks}, [model])
        ids[q] = {"contract": contract, "model": model, "params": params, "data": data, "code": code, "plan": plan}
    def execute(q):
        dependencies = [ids[q][kind] for kind in ("model", "params", "data", "code", "plan")]
        run = rt.execute(revision(), q, ["{python}", "solver.py"], ["result.json"], dependencies=dependencies, timeout=60, seed="42")["result"]
        if run["status"] != "executed":
            raise RuntimeError(run)
        checked = rt.validate_run(revision(), run["object_id"], "checker.py", ["{python}", "{checker}", "{run}", "{report}"], timeout=60)["result"]
        if not checked["passed"]:
            raise RuntimeError(checked)
        rt.cover(revision(), "REQ-" + q + "-001", {"objective" if q == "Q1" else "test_mae": checked["result_id"]})
        ids[q].update(run=run["object_id"], validation=checked["validation_id"], result=checked["result_id"])
        return rt.read()["copilot"]["objects"][checked["result_id"]]["payload"]["metrics"]
    for q in ids:
        metrics[q] = execute(q)
    first_run = ids["Q1"]["run"]
    original_objective = metrics["Q1"]["objective"]
    if not project_status(workspace, rt.read())["requirements"]["complete"]:
        raise RuntimeError("Initial known cases were not covered")
    updated = json.loads(json.dumps(rt.read()["copilot"]["objects"][ids["Q1"]["params"]]["payload"]))
    updated["entries"][0]["current_value"] = 2.5
    updated["version"] = 2
    ids["Q1"]["params"] = reg("ParameterSet", "params.Q1", updated, [ids["Q1"]["model"]])
    invalidation = project_status(workspace, rt.read())
    if invalidation["requirements"]["complete"] or rt.read()["copilot"]["objects"][first_run]["status"] != "stale":
        raise RuntimeError("Parameter update failed to invalidate previous results")
    metrics["Q1"] = execute("Q1")
    final_status = project_status(workspace, rt.read())
    if not final_status["requirements"]["complete"] or final_status["submission"]["ready"]:
        raise RuntimeError("Final coverage/readiness boundary differs")
    report = {"synthetic": True, "prepared": prepared, "objects": ids, "metrics": metrics,
              "parameter_change": {"from": 2, "to": 2.5, "first_run": first_run, "old_result_invalidated": True,
                                   "old_objective": original_objective, "new_objective": metrics["Q1"]["objective"]},
              "status": final_status, "scope": "Data parsing and original known cases only; no contest solution or predictive generalization"}
    write(workspace / "example-report.json", report)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    print(json.dumps(run_example(p.parse_args().workspace), ensure_ascii=False, indent=2, allow_nan=False))
