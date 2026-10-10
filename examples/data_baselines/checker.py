"""Independent arithmetic checker: no solver, starter or adapter imports."""
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import sys


def close(a, b, tolerance=1e-7):
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def check(root):
    context = json.loads((root / "run_context.json").read_text(encoding="utf-8"))
    params = {e["parameter_id"]: e["current_value"] for e in context["ParameterSet"]["entries"]}
    question = context["ModelSpec"]["question"]
    actual = json.loads((root / "result.json").read_text(encoding="utf-8"))
    with (root / context["DataContract"]["adapter"]["normalized"]["path"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    outcomes = {}
    if question == "Q1":
        start = datetime(2026, 1, 1)
        energy = sum((Decimal(r["energy"]) for r in rows), Decimal(0))
        outcomes["data_slots"] = (len(rows) == 144 and energy == Decimal(1440)
                                   and all(Decimal(r["energy"]) == 10 and r["slot_start"] == (start + timedelta(minutes=10 * n)).isoformat()
                                           and r["slot_end"] == (start + timedelta(minutes=10 * (n + 1))).isoformat() for n, r in enumerate(rows)))
        vector = actual["purchases"]
        costs = [params["low_cost"], 3, 4]
        outcomes["feasibility"] = (len(vector) == 3 and all(math.isfinite(x) and -1e-7 <= x <= 600 + 1e-7 for x in vector)
                                    and sum(vector) >= float(energy) - 1e-7
                                    and close(sum(c * x for c, x in zip(costs, vector)), actual["objective"]))
        # For this one aggregate demand and identical capacities, cheapest-first
        # fills give the analytic lower bound. This is not a general LP oracle.
        remaining = float(energy)
        expected = 0
        for price in sorted(costs):
            amount = min(600, remaining)
            expected += amount * price
            remaining -= amount
        outcomes["known_optimum"] = remaining == 0 and close(actual["objective"], expected)
        metrics = {"objective": actual["objective"], "energy_total": float(energy), "checked_slots": len(rows)}
    else:
        count = params["train_count"]
        test = rows[count:]
        expected = [1 + 2 * float(row["x"]) for row in test]
        outcomes["analytic_predictions"] = (len(actual["predictions"]) == len(expected)
                                             and all(close(a, e) for a, e in zip(actual["predictions"], expected)))
        errors = [abs(float(row["y"]) - prediction) for row, prediction in zip(test, actual["predictions"])]
        mae = sum(errors) / len(test)
        rmse = math.sqrt(sum(v ** 2 for v in errors) / len(test))
        outcomes["metric_recompute"] = close(actual["metrics_test"]["MAE"], mae) and close(actual["metrics_test"]["RMSE"], rmse)
        train_mean = sum(float(r["y"]) for r in rows[:count]) / count
        baseline_mae = sum(abs(float(r["y"]) - train_mean) for r in test) / len(test)
        scaler_mean = sum(float(r["x"]) for r in rows[:count]) / count
        outcomes["train_baseline"] = (close(actual["baseline_value"], train_mean) and close(actual["baseline_metrics"]["MAE"], baseline_mae)
                                       and len(actual["scaler_mean"]) == 1 and close(actual["scaler_mean"][0], scaler_mean))
        metrics = {"test_mae": mae, "test_rmse": rmse, "baseline_mae": baseline_mae, "heldout_rows": len(test)}
    if actual.get("synthetic") is not True or actual.get("question") != question:
        outcomes = {key: False for key in outcomes}
    return {"checks": [{"check_id": key, "status": "pass" if passed else "fail", "evidence": ["result.json"]} for key, passed in outcomes.items()],
            "metrics": metrics, "scope": "Original synthetic known cases; no real contest, field validation or predictive generalization claim"}


if __name__ == "__main__":
    destination = Path(sys.argv[2])
    try:
        report = check(Path(sys.argv[1]))
    except (ValueError, KeyError, TypeError, OSError, ZeroDivisionError) as exc:
        report = {"checks": [], "error": str(exc)}
    destination.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    raise SystemExit(0 if report.get("checks") and all(item["status"] == "pass" for item in report["checks"]) else 1)
