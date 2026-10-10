import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from copilot_comparison import validate_declaration, comparison_view, CONTEXT


def declaration():
    context = {name: "same declared synthetic condition" for name in CONTEXT}
    return {"schema_version": "1.0", "group": "forecast-mae", "title": "预测误差比较",
            "source_files": [{"path": "series.csv", "sha256": "A"*64}],
            "variants": [{"id": name, "label": name, "method": name, "backend": "known case",
                          "metric_path": "/" + name, "direction": "lower", "context": dict(context)} for name in ("model", "baseline")]}


def observed():
    meta = declaration()
    model = {"kind": "ModelSpec", "payload": {"question": "Q1", "data_contract": {"comparison": meta},
             "outputs": [{"name": name, "unit": "kWh"} for name in ("model", "baseline")]}, "dependencies": []}
    result = {"kind": "ResultRecord", "dependencies": ["MODEL"], "is_current": True, "current_errors": [], "effective_status": "verified",
              "metric_details": {"items": [{"metric_path": "/"+name, "value": value, "unit": "kWh", "declaration_status": "declared"} for name, value in (("model", 1), ("baseline", 5))]}}
    return {"objects": {"MODEL": model, "RESULT": result}}


class ComparisonTests(unittest.TestCase):
    def test_same_conditions_compare_actual_verified_metrics(self):
        cp = observed()
        group = comparison_view(cp, cp["objects"])[0]
        self.assertTrue(group["comparable"])
        self.assertEqual([r["value"] for r in group["rows"]], [1, 5])

    def test_different_context_never_ranks(self):
        for name in CONTEXT:
            cp = observed()
            cp["objects"]["MODEL"]["payload"]["data_contract"]["comparison"]["variants"][1]["context"][name] = "different"
            group = comparison_view(cp, cp["objects"])[0]
            self.assertFalse(group["comparable"])
            self.assertIn("比较条件不同：" + name, group["reasons"])

    def test_stale_or_missing_metric_does_not_look_checked(self):
        for status in ("stale", "generated"):
            cp = observed(); cp["objects"]["RESULT"]["effective_status"] = status
            group = comparison_view(cp, cp["objects"])[0]
            self.assertFalse(group["comparable"])
            self.assertFalse(any(r["checked"] for r in group["rows"]))
        cp = observed(); cp["objects"]["RESULT"]["metric_details"]["items"].pop()
        self.assertFalse(comparison_view(cp, cp["objects"])[0]["comparable"])

    def test_unit_difference_blocks_comparison(self):
        cp = observed(); cp["objects"]["RESULT"]["metric_details"]["items"][1]["unit"] = "kW"
        self.assertFalse(comparison_view(cp, cp["objects"])[0]["comparable"])

    def test_unknown_fields_or_undeclared_metric_rejected(self):
        value = declaration(); outputs = [{"name": name, "unit": "1"} for name in ("model", "baseline")]
        validate_declaration(value, outputs)
        value["variants"][0]["context"]["future"] = "ignored?"
        with self.assertRaises(ValueError): validate_declaration(value, outputs)
        value = declaration(); value["variants"][0]["metric_path"] = "/missing"
        with self.assertRaises(ValueError): validate_declaration(value, outputs)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bridge_optimization", ROOT / "templates/shared/code_starter/optimization.py")
        cls.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.module)

    def case(self):
        context = {key: "aligned" for key in ("data", "time_grid", "information", "horizon", "boundary", "commitments", "costs", "objective_unit")}
        problem = {"c": [1, 1], "A_eq": [[1, 1]], "b_eq": [4]}
        a = {"x_star": [4, 0], "obj": 4., "status": "optimal", "optimality_proven": True}
        b = {"x_star": [0, 4], "obj": 4., "status": "optimal", "optimality_proven": True}
        return problem, a, b, context

    def test_multiple_optima_different_vectors_are_allowed(self):
        p, a, b, c = self.case()
        self.assertTrue(self.module.check_equivalence_bridge(p, p, a, b, left_context=c, right_context=c)["passed"])

    def test_cost_horizon_commitment_and_boundaries_must_align(self):
        p, a, b, c = self.case()
        for key in ("costs", "horizon", "boundary", "commitments", "information"):
            other = dict(c); other[key] = "different"
            self.assertEqual(self.module.check_equivalence_bridge(p, p, a, b, left_context=c, right_context=other)["status"], "not_comparable")
        q = {**p, "c": [2, 1]}
        self.assertEqual(self.module.check_equivalence_bridge(p, q, a, b, left_context=c, right_context=c)["status"], "not_comparable")

    def test_reported_success_cannot_hide_invalid_solution(self):
        p, a, b, c = self.case(); b["x_star"] = [0, 8]
        self.assertEqual(self.module.check_equivalence_bridge(p, p, a, b, left_context=c, right_context=c)["status"], "failed")

    def test_feasible_not_proven_is_pending(self):
        p, a, b, c = self.case(); b["optimality_proven"] = False
        self.assertEqual(self.module.check_equivalence_bridge(p, p, a, b, left_context=c, right_context=c)["status"], "pending_optimality")

    def test_invalid_gap_cannot_claim_optimality(self):
        p, a, b, c = self.case()
        for gap in (float('nan'), float('inf'), -1, True, "0"):
            b["relative_gap"] = gap
            self.assertEqual(self.module.check_equivalence_bridge(p, p, a, b, left_context=c, right_context=c)["status"], "pending_optimality")
