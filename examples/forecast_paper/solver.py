"""Original delayed-publication synthetic series, not real forecasting evidence."""
import json
from pathlib import Path
from forecasting import rolling_backtest
import csv

context = json.loads(Path("run_context.json").read_text(encoding="utf-8"))
declaration = json.loads(Path("forecast_spec.json").read_text(encoding="utf-8"))
parameters = {e["parameter_id"]: e["current_value"] for e in context["ParameterSet"]["entries"]}
policy = declaration["policy"]
policy["train_window"] = parameters["window"]
with Path("series.csv").open(encoding="utf-8", newline="") as handle:
    rows = [{"time": r["observed_at"], "available_at": r["published_at"], "value": float(r["value"])} for r in csv.DictReader(handle)]
report = rolling_backtest(rows, policy)
report["synthetic"] = True
Path("result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

# Original figure uses the same synthetic source and actual origin predictions.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axes = plt.subplots(figsize=(7.0, 2.7))
axes.plot(range(len(rows)), [r["value"] for r in rows], color="#245a43", label="Synthetic observations")
for horizon, marker in ((1, "o"), (2, "s")):
    forecasts = [r for r in report["forecasts"] if r["horizon"] == horizon]
    positions = [(int(r["target_time"][11:13])+8) % 24 for r in forecasts]
    axes.scatter(positions, [r["prediction"] for r in forecasts], marker=marker, label=f"Direct forecast h={horizon}")
axes.set(xlabel="Hour from synthetic start", ylabel="Value (dimensionless)", title="Declared synthetic rolling forecast")
axes.legend(frameon=False, fontsize=8); axes.grid(axis="y", alpha=.15)
fig.tight_layout(); fig.savefig("forecast.png", dpi=180); plt.close(fig)
