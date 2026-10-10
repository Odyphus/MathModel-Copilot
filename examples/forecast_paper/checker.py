"""Independent known-line, publication eligibility and arithmetic checks.

Does not import the solver, forecasting module, sklearn or its preprocessing.
"""
import csv
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import sys


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check(root):
    report = json.loads((root / "result.json").read_text(encoding="utf-8"))
    declared = json.loads((root / "forecast_spec.json").read_text(encoding="utf-8"))["policy"]
    context = json.loads((root / "run_context.json").read_text(encoding="utf-8"))
    declared["train_window"] = next(p["current_value"] for p in context["ParameterSet"]["entries"] if p["parameter_id"] == "window")
    with (root / "series.csv").open(encoding="utf-8", newline="") as handle:
        rows = [{"time": dt(r["observed_at"]), "published": dt(r["published_at"]), "value": float(r["value"])} for r in csv.DictReader(handle)]
    start = rows[0]["time"]; delta = timedelta(minutes=declared["frequency_minutes"])
    lookup = {r["time"]: r for r in rows}
    outcomes = {key: True for key in ("known_line", "causality", "metric_recompute")}
    outcomes["known_line"] = report.get("synthetic") is True and len(rows) == 17 and all(r["time"] == start+i*delta and r["published"] == r["time"]+delta and r["value"] == 10+2*i for i,r in enumerate(rows))
    expected_pairs = [(dt(origin), h) for origin in declared["origins"] for h in declared["horizons"]]
    windows = report["forecasts"]
    outcomes["causality"] = report["policy"] == declared and [(dt(r["origin"]), r["horizon"]) for r in windows] == expected_pairs
    errors, baseline_errors = [], []
    def same(saved, original):
        return dt(saved["time"]) == original["time"] and dt(saved["available_at"]) == original["published"] and saved["value"] == original["value"]
    for row in windows:
        origin, h = dt(row["origin"]), row["horizon"]
        truth = lookup[origin+h*delta]
        known = [r for r in rows if r["time"] <= origin and r["published"] <= origin]
        outcomes["causality"] &= same(row["truth"], truth) and truth["published"] <= dt(declared["evaluation_as_of"]) and same(row["baseline"], known[-1])
        outcomes["known_line"] &= abs(row["prediction"]-truth["value"]) <= 1e-10
        eligible = []
        for label in known:
            decision = label["time"]-h*delta
            features = [lookup.get(decision-lag*delta) for lag in declared["lags"]]
            if all(f is not None and f["published"] <= decision for f in features): eligible.append((label, decision, features))
        eligible = eligible[-declared["train_window"]:]
        outcomes["causality"] &= len(row["training"]) == len(eligible)
        for pair, (label, decision, features) in zip(row["training"], eligible):
            outcomes["causality"] &= same(pair["label"], label) and dt(pair["decision_time"]) == decision and all(same(a,b) for a,b in zip(pair["features"], features)) and len(pair["features"]) == len(features)
        current = [lookup[origin-lag*delta] for lag in declared["lags"]]
        outcomes["causality"] &= len(row["current_features"]) == len(current) and all(same(a,b) and b["published"] <= origin for a,b in zip(row["current_features"], current))
        means = [sum(pair[2][j]["value"] for pair in eligible)/len(eligible) for j in range(len(declared["lags"]))]
        outcomes["causality"] &= row["preprocessing"]["mean"] == means and row["preprocessing"]["scope"] == "origin_training_only"
        error = row["prediction"] - truth["value"]; baseline_error = known[-1]["value"]-truth["value"]
        outcomes["metric_recompute"] &= abs(error-row["error"]) <= 1e-10 and abs(baseline_error-row["baseline_error"]) <= 1e-10
        errors.append(error); baseline_errors.append(baseline_error)
    mae = sum(abs(e) for e in errors)/len(errors); baseline_mae = sum(abs(e) for e in baseline_errors)/len(errors)
    outcomes["metric_recompute"] &= abs(mae-report["metrics"]["MAE"]) <= 1e-10 and abs(baseline_mae-report["metrics"]["baseline_MAE"]) <= 1e-10 and report["metrics"]["forecast_instances"] == len(errors)
    metrics = {"candidate_mae": round(mae, 12), "baseline_mae": baseline_mae, "forecast_instances": len(errors)}
    return {"checks": [{"check_id": key, "status": "pass" if value else "fail", "evidence": ["result.json"]} for key,value in outcomes.items()],
            "metrics": metrics, "scope": "合成已知直线与声明的一小时发布时间延迟；MAE 显示到十二位小数；不代表真实预测精度"}


if __name__ == "__main__":
    try: report = check(Path(sys.argv[1]))
    except (OSError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as exc: report = {"checks": [], "error": str(exc)}
    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    raise SystemExit(0 if report["checks"] and all(c["status"] == "pass" for c in report["checks"]) else 1)
