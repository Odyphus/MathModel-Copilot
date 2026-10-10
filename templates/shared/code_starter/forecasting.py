"""Causal direct lag forecasting on a declared regular, published time series.

No files or random state are changed on import. Publication timestamps are input
claims, not independently authenticated facts. Each origin is a new fit; labels
and lag features must have been available at their respective decision times.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math


class ForecastError(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise ForecastError("时间必须为带时区的 ISO 字符串")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForecastError("无效 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise ForecastError("时间必须显式声明时区")
    return parsed.astimezone(timezone.utc)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ForecastError(label + " 必须为有限数值")
    return float(value)


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ForecastError(label + " 的字段缺失或含未知字段")


def positive(value, label, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ForecastError(label + " 必须是 >= " + str(minimum) + " 的整数")
    return value


def validate_policy(policy):
    fields(policy, {"frequency_minutes", "origins", "horizons", "lags", "train_window", "min_train",
                    "model", "scale", "ridge_alpha", "evaluation_as_of", "evaluation_phase"}, "回测策略")
    positive(policy["frequency_minutes"], "frequency_minutes")
    positive(policy["min_train"], "min_train", 2)
    if policy["train_window"] is not None:
        positive(policy["train_window"], "train_window", policy["min_train"])
    for key, minimum in (("horizons", 1), ("lags", 0)):
        values = policy[key]
        if not isinstance(values, list) or not values or len(values) > 32:
            raise ForecastError(key + " 必须为 1..32 项的整数列表")
        for value in values:
            positive(value, key, minimum)
        if len(set(values)) != len(values):
            raise ForecastError(key + " 含重复项")
    if not isinstance(policy["origins"], list) or not policy["origins"] or len(policy["origins"]) > 10000:
        raise ForecastError("origins 必须显式给出 1..10000 个预测起点")
    origins = [timestamp(t) for t in policy["origins"]]
    if origins != sorted(set(origins)):
        raise ForecastError("origins 必须递增且不重复")
    if policy["model"] not in {"linear", "ridge"} or not isinstance(policy["scale"], bool):
        raise ForecastError("仅支持 linear/ridge 和布尔 scale")
    if finite(policy["ridge_alpha"], "ridge_alpha") <= 0:
        raise ForecastError("ridge_alpha 必须 > 0")
    if policy["evaluation_phase"] not in {"validation", "final_holdout", "synthetic_known_case"}:
        raise ForecastError("须声明验证集、最终留出集或合成已知算例")
    evaluation = timestamp(policy["evaluation_as_of"])
    if evaluation <= origins[-1]:
        raise ForecastError("evaluation_as_of 必须晚于所有预测起点")
    return origins, evaluation


def rolling_backtest(rows, policy):
    """Return every forecast instance, its eligible training trace and baseline.

    Overlapping targets are separate forecasts. No silent missing-window skip,
    preprocessing on the full series, auto tuning or external future features.
    """
    origins, evaluation = validate_policy(policy)
    delta = timedelta(minutes=policy["frequency_minutes"])
    series = {}
    for number, row in enumerate(rows, 1):
        fields(row, {"time", "available_at", "value"}, "观测行 " + str(number))
        observed, available = timestamp(row["time"]), timestamp(row["available_at"])
        if observed in series or available < observed:
            raise ForecastError("观测时间重复或发布时间早于观测时间")
        series[observed] = {"time": iso(observed), "available_at": iso(available),
                            "value": finite(row["value"], "value"), "published": available}
    times = sorted(series)
    if len(times) < 3 or any(b - a != delta for a, b in zip(times, times[1:])):
        raise ForecastError("观测时间轴不完整或与声明频率不一致；不隐式填补缺口")
    if any(origin not in series for origin in origins):
        raise ForecastError("预测起点不在声明的观测时间轴上")
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    def exposed(row):
        return {k: row[k] for k in ("time", "available_at", "value")}
    def features(decision):
        records = [series.get(decision - lag * delta) for lag in policy["lags"]]
        if any(row is None or row["published"] > decision for row in records):
            return None
        return records
    forecasts = []
    for origin in origins:
        current = features(origin)
        if current is None:
            raise ForecastError("预测起点的滞后特征缺失或尚未发布：" + iso(origin))
        known = [series[t] for t in times if t <= origin and series[t]["published"] <= origin]
        if not known:
            raise ForecastError("起点没有已发布观测，无法计算简单基线")
        baseline = known[-1]
        for horizon in policy["horizons"]:
            target = origin + horizon * delta
            truth = series.get(target)
            if truth is None or truth["published"] > evaluation:
                raise ForecastError("评价目标缺失或在 evaluation_as_of 尚未发布：" + iso(target))
            eligible = []
            unavailable_features = 0
            for label_time in times:
                label = series[label_time]
                if label_time > origin or label["published"] > origin:
                    continue
                decision = label_time - horizon * delta
                past = features(decision)
                if past is None:
                    unavailable_features += 1
                    continue
                eligible.append({"decision_time": iso(decision), "label": exposed(label),
                                 "features": [exposed(row) for row in past]})
            selected = eligible[-policy["train_window"]:] if policy["train_window"] else eligible
            if len(selected) < policy["min_train"]:
                raise ForecastError("起点可用训练对不足：" + iso(origin) + ", horizon=" + str(horizon))
            x = np.array([[row["value"] for row in pair["features"]] for pair in selected])
            y = np.array([pair["label"]["value"] for pair in selected])
            estimator = LinearRegression() if policy["model"] == "linear" else Ridge(alpha=policy["ridge_alpha"])
            model = make_pipeline(StandardScaler(), estimator) if policy["scale"] else estimator
            model.fit(x, y)
            prediction = float(model.predict([[row["value"] for row in current]])[0])
            if not math.isfinite(prediction):
                raise ForecastError("预测产生非有限值")
            error, baseline_error = prediction - truth["value"], baseline["value"] - truth["value"]
            forecasts.append({"origin": iso(origin), "horizon": horizon, "target_time": iso(target),
                              "truth": exposed(truth), "prediction": prediction, "baseline": exposed(baseline),
                              "error": error, "baseline_error": baseline_error,
                              "current_features": [exposed(row) for row in current], "training": selected,
                              "excluded_historical_feature_pairs": unavailable_features,
                              "eligible_before_window": len(eligible),
                              "preprocessing": {"scope": "origin_training_only", "scaled": policy["scale"],
                                                "mean": model[0].mean_.tolist() if policy["scale"] else None}})
    def metrics(instances):
        n = len(instances)
        mae = math.fsum(abs(row["error"]) for row in instances) / n
        baseline_mae = math.fsum(abs(row["baseline_error"]) for row in instances) / n
        return {"forecast_instances": n, "MAE": mae, "RMSE": math.sqrt(math.fsum(row["error"] ** 2 for row in instances) / n),
                "baseline_MAE": baseline_mae, "baseline_RMSE": math.sqrt(math.fsum(row["baseline_error"] ** 2 for row in instances) / n),
                "MAE_improvement": baseline_mae - mae}
    return {"schema_version": "1.0", "policy": policy, "forecasts": forecasts, "metrics": metrics(forecasts),
            "by_horizon": {str(h): metrics([r for r in forecasts if r["horizon"] == h]) for h in policy["horizons"]},
            "scope": "Declared publication times; fixed policy, same forecast instances for model and last-published-value baseline. No performance generalization or authenticated publication-time claim."}
