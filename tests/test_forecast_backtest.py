"""Known causal series and adversarial changes, not implementation mirrors."""
import copy
import csv
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_forecast import forecasting as f, run, verify


def case():
    policy = json.loads((ROOT / "templates/copilot/forecast_spec.json").read_text(encoding="utf-8"))["policy"]
    start = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    rows = [{"time": (start + timedelta(hours=i)).isoformat(), "available_at": (start + timedelta(hours=i+1)).isoformat(), "value": 10 + 2*i} for i in range(17)]
    return rows, policy


class ForecastTests(unittest.TestCase):
    def test_known_line_delayed_publication_and_baseline_same_windows(self):
        rows, policy = case()
        result = f.rolling_backtest(rows, policy)
        self.assertEqual(result["metrics"]["forecast_instances"], 6)
        self.assertLess(result["metrics"]["MAE"], 1e-10)
        self.assertEqual(result["metrics"]["baseline_MAE"], 5)
        self.assertEqual(result["by_horizon"]["1"]["baseline_MAE"], 4)
        self.assertEqual(result["by_horizon"]["2"]["baseline_MAE"], 6)
        # Overlapping targets are not deduplicated or silently selected.
        self.assertEqual(len({r["target_time"] for r in result["forecasts"]}), 4)

    def test_future_changes_do_not_change_earlier_predictions_or_fits(self):
        rows, policy = case()
        before = f.rolling_backtest(rows, policy)
        changed = copy.deepcopy(rows)
        for row in changed[11:]:
            row["value"] += 10000
        after = f.rolling_backtest(changed, policy)
        for left, right in zip(before["forecasts"], after["forecasts"]):
            for field in ("prediction", "training", "preprocessing", "current_features", "baseline"):
                self.assertEqual(left[field], right[field])
        self.assertGreater(after["metrics"]["MAE"], 1000)

    def test_scaler_uses_each_origin_training_pairs_only(self):
        rows, policy = case()
        result = f.rolling_backtest(rows, policy)
        full_mean = sum(r["value"] for r in rows) / len(rows)
        for window in result["forecasts"]:
            train_mean = sum(r["features"][0]["value"] for r in window["training"]) / 4
            self.assertEqual(window["preprocessing"]["mean"], [train_mean])
            self.assertNotEqual(train_mean, full_mean)
            self.assertTrue(all(f.timestamp(t["label"]["available_at"]) <= f.timestamp(window["origin"]) for t in window["training"]))
            self.assertTrue(all(f.timestamp(t["features"][0]["available_at"]) <= f.timestamp(t["decision_time"]) for t in window["training"]))

    def test_future_lags_rejected(self):
        rows, policy = case()
        policy["lags"] = [-1]
        with self.assertRaises(f.ForecastError):
            f.rolling_backtest(rows, policy)

    def test_unpublished_current_feature_rejected(self):
        rows, policy = case()
        policy["lags"] = [0]
        with self.assertRaisesRegex(f.ForecastError, "尚未发布"):
            f.rolling_backtest(rows, policy)

    def test_delayed_training_features_not_retroactively_available(self):
        rows, policy = case()
        rows[2]["available_at"] = rows[7]["available_at"]
        result = f.rolling_backtest(rows, policy)
        self.assertTrue(all(pair["features"][0]["time"] != f.iso(f.timestamp(rows[2]["time"])) for window in result["forecasts"] for pair in window["training"]))

    def test_missing_time_slot_fails_instead_of_shorter_report(self):
        rows, policy = case()
        del rows[11]
        with self.assertRaisesRegex(f.ForecastError, "时间轴"):
            f.rolling_backtest(rows, policy)

    def test_missing_or_unpublished_evaluation_truth_fails(self):
        rows, policy = case()
        policy["evaluation_as_of"] = policy["origins"][-1].replace("10:", "11:")
        with self.assertRaisesRegex(f.ForecastError, "评价目标"):
            f.rolling_backtest(rows, policy)

    def test_unknown_policy_fields_not_silently_ignored(self):
        rows, policy = case()
        policy["future_weather"] = [1, 2]
        with self.assertRaises(f.ForecastError):
            f.rolling_backtest(rows, policy)

    def test_duplicated_origins_horizons_and_bad_timezones(self):
        rows, policy = case()
        for field, value in (("origins", [policy["origins"][0]]*2), ("horizons", [1, 1]), ("lags", [True])):
            changed = copy.deepcopy(policy)
            changed[field] = value
            with self.assertRaises(f.ForecastError):
                f.rolling_backtest(rows, changed)
        rows[0]["time"] = "2026-01-01T00:00:00"
        with self.assertRaises(f.ForecastError):
            f.rolling_backtest(rows, policy)

    def test_candidate_can_be_worse_than_baseline(self):
        rows, policy = case()
        policy["model"] = "ridge"
        policy["ridge_alpha"] = 1e8
        result = f.rolling_backtest(rows, policy)
        self.assertLess(result["metrics"]["MAE_improvement"], 0)

    def test_cli_report_create_only_replay_rejects_source_and_policy_drift(self):
        rows, policy = case()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "series.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["time", "available_at", "value"])
                writer.writeheader(); writer.writerows(rows)
            declaration = {"schema_version": "1.0", "source": {"path": "series.csv", "encoding": "utf-8"}, "columns": {key: key for key in rows[0]}, "unit": "kWh", "policy": policy}
            (root / "spec.json").write_text(json.dumps(declaration), encoding="utf-8")
            created = run(root, "spec.json", "reports/first.json")
            self.assertFalse(created["verified"])
            self.assertTrue(verify(root, "spec.json", "reports/first.json")["replayed"])
            with self.assertRaises(ValueError):
                run(root, "spec.json", "reports/first.json")
            declaration["policy"]["model"] = "ridge"
            (root / "spec.json").write_text(json.dumps(declaration), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                verify(root, "spec.json", "reports/first.json")
            declaration["policy"]["model"] = "linear"
            (root / "spec.json").write_text(json.dumps(declaration), encoding="utf-8")
            (root / "series.csv").write_text((root / "series.csv").read_text(encoding="utf-8").replace("42", "400"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                verify(root, "spec.json", "reports/first.json")
