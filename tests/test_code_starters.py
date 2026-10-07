"""针对 code starter 科研正确性边界的回归测试。"""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import warnings

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mathmodel-matplotlib-tests")

import matplotlib.pyplot as plt
import numpy as np
from sklearn.datasets import make_classification
from sklearn.pipeline import Pipeline


ROOT = Path(__file__).resolve().parents[1]
STARTERS = ROOT / "templates" / "shared" / "code_starter"


def load_starter(name):
    spec = importlib.util.spec_from_file_location(
        f"mathmodel_code_starter_{name}", STARTERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classification = load_starter("classification")
evaluation = load_starter("evaluation")
# 本文件只测试不依赖求解器的贪心基线。若环境未安装
# requirements 中的 cvxpy, 用空模块隔离未调用的 LP/MILP 模板。
cvxpy_stubbed = False
try:
    import cvxpy  # noqa: F401
except ModuleNotFoundError:
    sys.modules["cvxpy"] = types.ModuleType("cvxpy")
    cvxpy_stubbed = True
optimization = load_starter("optimization")
if cvxpy_stubbed:
    sys.modules.pop("cvxpy", None)

statsmodels_stubbed = False
try:
    import statsmodels.api  # noqa: F401
except ModuleNotFoundError:
    statsmodels_module = types.ModuleType("statsmodels")
    statsmodels_api = types.ModuleType("statsmodels.api")

    def durbin_watson(residuals):
        residuals = np.asarray(residuals, dtype=float)
        denominator = float(residuals @ residuals)
        return (float(np.diff(residuals) @ np.diff(residuals)) / denominator
                if denominator > 0 else np.nan)

    statsmodels_api.stats = types.SimpleNamespace(durbin_watson=durbin_watson)
    statsmodels_module.api = statsmodels_api
    sys.modules["statsmodels"] = statsmodels_module
    sys.modules["statsmodels.api"] = statsmodels_api
    statsmodels_stubbed = True
prediction = load_starter("prediction")
if statsmodels_stubbed:
    sys.modules.pop("statsmodels.api", None)
    sys.modules.pop("statsmodels", None)


class ClassificationStarterTests(unittest.TestCase):
    def test_scaler_is_fitted_inside_each_cross_validation_fold(self):
        X, y = make_classification(
            n_samples=100,
            n_features=6,
            n_informative=4,
            n_redundant=0,
            random_state=7,
        )
        fit_sizes = []
        original_fit = classification.StandardScaler.fit

        def recording_fit(scaler, X_fold, y_fold=None, **fit_params):
            fit_sizes.append(len(X_fold))
            return original_fit(scaler, X_fold, y_fold, **fit_params)

        with patch.object(classification.StandardScaler, "fit", new=recording_fit):
            results, scaler = classification.compare_models(X, y, test_size=0.2)

        train_size = 80
        self.assertTrue(any(size < train_size for size in fit_sizes))
        self.assertTrue(all(size <= train_size for size in fit_sizes))
        self.assertEqual(scaler.n_samples_seen_, train_size)
        for result in results.values():
            self.assertIsInstance(result["model"], Pipeline)
            self.assertIn("scaler", result["model"].named_steps)


class OptimizationStarterTests(unittest.TestCase):
    def test_f06_near_integer_is_rounded_and_revalidated(self):
        result = optimization.checked_integer_solution([9.999999999], lower=10, upper=10, costs=[1], budget=10)
        np.testing.assert_array_equal(result, [10])
        with self.assertRaisesRegex(ValueError, "预算"):
            optimization.checked_integer_solution([9.999999999], lower=0, costs=[1], budget=9)
        with self.assertRaisesRegex(ValueError, "整数容差"):
            optimization.checked_integer_solution([9.5])

    def test_f06_missing_solution_is_not_converted_or_reported_as_valid(self):
        with self.assertRaisesRegex(ValueError, "未返回"):
            optimization.checked_integer_solution(None)
        checks = optimization.sanity_check({"status": "infeasible", "x_star": None, "obj": None}, expected_range=(0, 10), baseline=0)
        self.assertFalse(any(checks.values()))

    def test_greedy_baseline_shares_one_budget_and_is_feasible(self):
        p = np.array([10.0, 9.0, 4.0])
        c = np.array([6.0, 5.0, 0.0])
        result = optimization.greedy_budget_baseline(p, c, B=10.0, x_max=2)

        self.assertLessEqual(float(c @ result["x_star"]), 10.0 + 1e-10)
        np.testing.assert_array_less(result["x_star"], np.full(3, 3))
        self.assertTrue(np.issubdtype(result["x_star"].dtype, np.integer))
        self.assertEqual(result["x_star"][2], 2)
        self.assertAlmostEqual(result["budget_used"], float(c @ result["x_star"]))

    def test_equal_optimum_passes_baseline_check(self):
        checks = optimization.sanity_check(
            {"status": "optimal", "x_star": np.array([1]), "obj": 3.0},
            baseline=3.0,
        )
        self.assertTrue(checks["beats_baseline"])


class EvaluationStarterTests(unittest.TestCase):
    def test_constant_indicator_gets_zero_entropy_weight(self):
        X = np.array([
            [1.0, 7.0, 3.0],
            [2.0, 7.0, 2.0],
            [4.0, 7.0, 1.0],
        ])
        result = evaluation.entropy_weights(X, ["+", "+", "-"])

        self.assertAlmostEqual(result["weights"][1], 0.0)
        self.assertAlmostEqual(result["entropy"][1], 1.0)
        self.assertTrue(result["constant_mask"][1])
        self.assertTrue(np.all(np.isfinite(result["weights"])))
        self.assertAlmostEqual(result["weights"].sum(), 1.0)

    def test_all_constant_indicators_fall_back_to_uniform_weights(self):
        result = evaluation.entropy_weights(np.full((4, 3), 5.0))
        np.testing.assert_allclose(result["weights"], np.full(3, 1 / 3))
        np.testing.assert_allclose(result["entropy"], np.ones(3))


class PredictionStarterTests(unittest.TestCase):
    def test_gm11_constant_series_uses_zero_a_limit(self):
        result = prediction.gm11(np.full(6, 5.0), predict_steps=3)
        self.assertTrue(np.all(np.isfinite(result["predicted"])))
        self.assertTrue(np.isfinite(result["in_sample_mape"]))

    def test_mape_ignores_undefined_zero_actual_terms(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            metrics, fig = prediction.residual_diagnostics(
                np.array([0.0, 2.0]), np.array([100.0, 1.0]))
        self.addCleanup(plt.close, fig)
        self.assertAlmostEqual(metrics["MAPE"], 50.0)

    def test_all_zero_actuals_report_undefined_mape_without_division(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            metrics, fig = prediction.residual_diagnostics(
                np.zeros(3), np.ones(3))
        self.addCleanup(plt.close, fig)
        self.assertTrue(np.isnan(metrics["MAPE"]))


if __name__ == "__main__":
    unittest.main()
