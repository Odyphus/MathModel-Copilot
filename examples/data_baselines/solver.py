"""Original synthetic examples; no dispatch or real predictive-performance claim."""
import csv
import json
from pathlib import Path

context = json.loads(Path("run_context.json").read_text(encoding="utf-8"))
question = context["ModelSpec"]["question"]
parameters = {e["parameter_id"]: e["current_value"] for e in context["ParameterSet"]["entries"]}
path = context["DataContract"]["adapter"]["normalized"]["path"]
with Path(path).open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
if question == "Q1":
    from optimization import solve_linear_program
    energy = sum(float(row["energy"]) for row in rows)
    costs = [parameters["low_cost"], 3, 4]
    solved = solve_linear_program(costs, A_ub=[[-1, -1, -1]], b_ub=[-energy], bounds=[(0, 600)] * 3)
    if solved["status"] != "optimal" or not solved["feasibility_verified"]:
        raise RuntimeError("No checked optimal solution: " + solved["status"])
    result = {"synthetic": True, "question": question, "objective": solved["obj"], "purchases": solved["x_star"].tolist(),
              "energy_total": energy, "backend": solved["solver"], "solver_version": solved["solver_version"],
              "status": solved["status"], "solution_check": solved["solution_check"]}
else:
    from prediction import fit_regression
    count = parameters["train_count"]
    X = [[float(row["x"])] for row in rows]
    y = [float(row["y"]) for row in rows]
    solved = fit_regression(X[:count], y[:count], X[count:], y[count:], scale=True)
    result = {"synthetic": True, "question": question, "predictions": solved["y_pred_test"].tolist(),
              "metrics_test": solved["metrics_test"], "baseline_value": solved["baseline_test"]["value"],
              "baseline_metrics": solved["baseline_test"]["metrics"], "scope": solved["scope"],
              "scaler_mean": solved["model"].named_steps["standardscaler"].mean_.tolist()}
Path("result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
