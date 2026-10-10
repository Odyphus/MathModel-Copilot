"""Known solutions, enumeration and holdout arithmetic independent of starters."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
STARTERS = ROOT / "templates/shared/code_starter"


def load(name):
    spec = importlib.util.spec_from_file_location("checked_" + name, STARTERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


optimization = load("optimization")
prediction = load("prediction")


class LinearBaselineTests(unittest.TestCase):
    def test_lp_minimize_known_solution_with_inequality(self):
        result = optimization.solve_linear_program([1, 2], A_ub=[[-1, -1]], b_ub=[-4])
        self.assertEqual(result["status"], "optimal")
        self.assertAlmostEqual(result["obj"], 4)
        self.assertGreaterEqual(sum(result["x_star"]), 4 - 1e-7)
        self.assertTrue(result["feasibility_verified"])
        self.assertTrue(result["optimality_proven"])

    def test_lp_maximize_and_equal_optima_compare_objective(self):
        result = optimization.solve_linear_program([1, 2], A_eq=[[1, 1]], b_eq=[4], maximize=True)
        self.assertAlmostEqual(result["obj"], 8)
        equal = optimization.solve_linear_program([1, 1], A_eq=[[1, 1]], b_eq=[4])
        self.assertAlmostEqual(equal["obj"], 4)
        # Both independent alternatives satisfy the same optimum; vector identity is irrelevant.
        for vector in ([4, 0], [0, 4]):
            checked = optimization.check_linear_solution(vector, [1, 1], A_eq=[[1, 1]], b_eq=[4])
            self.assertTrue(checked["feasible"])
            self.assertEqual(checked["objective"], equal["obj"])

    def test_milp_matches_complete_small_enumeration(self):
        profit, cost = [4, 4, 4], [6, 5, 1]
        candidates = [sum(p * v for p, v in zip(profit, vector)) for vector in itertools.product(range(3), repeat=3)
                      if sum(c * v for c, v in zip(cost, vector)) <= 10]
        result = optimization.solve_linear_program(profit, A_ub=[cost], b_ub=[10], bounds=[(0, 2)] * 3, integer=[1] * 3, maximize=True)
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["obj"], max(candidates))
        self.assertLessEqual(sum(c * v for c, v in zip(cost, result["x_star"])), 10)
        self.assertTrue(all(v == round(v) for v in result["x_star"]))

    def test_infeasible_and_unbounded_do_not_return_valid_results(self):
        cases = [(dict(c=[1], A_ub=[[1]], b_ub=[-1]), "infeasible"),
                 (dict(c=[-1]), "unbounded")]
        for arguments, expected in cases:
            with self.subTest(status=expected):
                result = optimization.solve_linear_program(**arguments)
                self.assertEqual(result["status"], expected)
                self.assertIsNone(result["obj"])
                self.assertIsNone(result["x_star"])
                self.assertFalse(result["feasibility_verified"])
                self.assertFalse(result["optimality_proven"])

    def test_time_limit_incumbent_is_only_feasible_not_proven(self):
        native = types.SimpleNamespace(status=1, message="time limit", x=np.array([1.0]), mip_gap=0.25)
        with patch("scipy.optimize.milp", return_value=native):
            result = optimization.solve_linear_program([1], bounds=[(0, 2)], integer=[1])
        self.assertEqual(result["status"], "feasible_not_proven")
        self.assertTrue(result["feasibility_verified"])
        self.assertFalse(result["optimality_proven"])

    def test_accepted_gap_is_not_promoted_to_exact_optimum(self):
        native = types.SimpleNamespace(status=0, message="gap accepted", x=np.array([1.0]), mip_gap=0.1)
        with patch("scipy.optimize.milp", return_value=native):
            result = optimization.solve_linear_program([1], bounds=[(0, 2)], integer=[1], options={"mip_rel_gap": 0.1})
        self.assertEqual(result["status"], "feasible_not_proven")
        self.assertFalse(result["optimality_proven"])

    def test_rounding_rechecks_actual_constraints(self):
        native = types.SimpleNamespace(status=0, message="near integer", x=np.array([0.999999991]), mip_gap=0.0)
        with patch("scipy.optimize.milp", return_value=native):
            result = optimization.solve_linear_program([1], A_ub=[[2e8]], b_ub=[199999998.2], bounds=[(0, 1)], integer=[1])
        self.assertEqual(result["status"], "invalid_solution")
        self.assertFalse(result["feasibility_verified"])
        self.assertIsNone(result["x_star"])

    def test_independent_checker_rejects_bad_equality_bounds_and_integers(self):
        for x in ([0, 0], [5, -1], [1.5, 2.5]):
            with self.subTest(x=x):
                self.assertFalse(optimization.check_linear_solution(x, [1, 2], A_eq=[[1, 1]], b_eq=[4], bounds=[(0, 4)] * 2, integer=[1, 1])["feasible"])

    def test_invalid_dimensions_nonfinite_and_integrality_rejected(self):
        cases = [dict(c=[np.nan]), dict(c=[1], A_ub=[[1, 2]], b_ub=[1]),
                 dict(c=[1], integer=[2]), dict(c=[1], bounds=[(2, 1)])]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                optimization.solve_linear_program(**arguments)

    def test_budget_template_works_without_cvxpy(self):
        with patch.object(optimization, "cp", None):
            result = optimization.solve_milp_template([10, 9, 4], [6, 5, 0], 10, x_max=2)
            unavailable = optimization.solve_milp_template([10], [6], 10, solver="CBC")
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["obj"], 16)
        self.assertEqual(unavailable["status"], "solver_unavailable")


class RegressionBaselineTests(unittest.TestCase):
    def test_linear_holdout_matches_analytic_line_and_baseline(self):
        result = prediction.fit_regression([[0], [1], [2], [3]], [1, 3, 5, 7], [[4], [5]], [9, 11])
        np.testing.assert_allclose(result["y_pred_test"], [9, 11], atol=1e-10)
        self.assertAlmostEqual(result["metrics_test"]["MAE"], 0)
        self.assertEqual(result["baseline_test"]["value"], 4)
        self.assertEqual(result["baseline_test"]["metrics"]["MAE"], 6)
        self.assertAlmostEqual(result["mae_improvement_over_baseline"], 6)

    def test_holdout_outlier_does_not_change_scaler_or_train_mean(self):
        result = prediction.fit_regression([[0], [1], [2]], [1, 3, 5], [[1000]], [2001], scale=True)
        self.assertIsInstance(result["model"], Pipeline)
        np.testing.assert_array_equal(result["model"].named_steps["standardscaler"].mean_, [1])
        self.assertEqual(result["baseline_test"]["value"], 3)
        self.assertAlmostEqual(result["y_pred_test"][0], 2001)

    def test_baseline_comparison_can_show_model_losing(self):
        result = prediction.fit_regression([[0], [1], [2]], [1, 3, 5], [[3]], [3])
        self.assertLess(result["mae_improvement_over_baseline"], 0)
        self.assertEqual(result["baseline_test"]["metrics"]["MAE"], 0)

    def test_singleton_or_constant_r2_explicitly_undefined_and_json_safe(self):
        result = prediction.fit_regression([[0], [1], [2]], [3, 3, 3], [[3], [4]], [3, 3])
        self.assertIsNone(result["metrics_test"]["R2"])
        self.assertIn("constant", result["metrics_test"]["R2_reason"])
        json.dumps(result["metrics_test"], allow_nan=False)

    def test_bad_shapes_empty_missing_values_rejected(self):
        cases = [([[0], [1]], [1, 2], [], []), ([[0], [1]], [1], [[2]], [3]),
                 ([[0], [np.nan]], [1, 2], [[2]], [3]), ([[0], [1]], [1, 2], [[2, 3]], [3])]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                prediction.fit_regression(*arguments)

    def test_imports_do_not_write_folders_or_reset_rng(self):
        code = "import importlib.util, numpy as n; from pathlib import Path; n.random.seed(7); before=n.random.get_state(); "
        code += "; ".join(f"s=importlib.util.spec_from_file_location('{name}',{str(STARTERS / (name + '.py'))!r}); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)" for name in ("optimization", "prediction"))
        code += "; after=n.random.get_state(); assert n.array_equal(before[1],after[1]); assert before[2:]==after[2:]; assert not Path('results').exists(); assert not Path('figures').exists()"
        with tempfile.TemporaryDirectory() as work:
            process = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=work, env=dict(os.environ, MPLBACKEND="Agg"), capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
