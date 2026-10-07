"""Independent trace replay, search-space accounting, statistics and XLS checks.

The schedule verifier is independent of the solver. Search and Monte Carlo
accounting prove the stated finite experiment, never global optimality.
"""
from __future__ import annotations
import csv
import io
import itertools
import json
import math
from pathlib import Path
import statistics
import sys
import unittest


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_statistics(entry, seeds):
    values = entry["sample_counts"]
    require(len(values) == seeds and all(type(x) is int and x >= 0 for x in values), "invalid Monte Carlo sample ledger")
    metrics = entry.get("selected", entry)
    mean, sd = statistics.mean(values), statistics.stdev(values)
    require(metrics["n"] == seeds and metrics["minimum"] == min(values) and metrics["maximum"] == max(values), "sample size/range mismatch")
    require(abs(metrics["mean"] - mean) < 1e-9 and abs(metrics["sd"] - sd) < 1e-9, "sample statistics mismatch")
    bounds = [mean - 1.96 * sd / math.sqrt(seeds), mean + 1.96 * sd / math.sqrt(seeds)]
    actual = metrics["mean_ci95_normal"]
    require(len(actual) == 2 and all(abs(a - b) < 1e-9 for a, b in zip(bounds, actual)), "Monte Carlo interval mismatch")


def validate_configuration_coverage(summary, groups):
    expected_faults = set(itertools.product(groups, ("single", "two")))
    actual_faults = {(x["group"], x["mode"]) for x in summary["faults"]}
    expected_sensitivity = set(itertools.product(groups, ("single", "two"), (0.005, 0.01, 0.02),
                                                 ((600, 900), (600, 1200), (900, 1200))))
    actual_sensitivity = {(x["group"], x["mode"], x["fault_probability"], tuple(x["repair_range"])) for x in summary["sensitivity"]}
    require(actual_faults == expected_faults and len(summary["faults"]) == len(expected_faults), "missing/duplicate fault configurations")
    require(actual_sensitivity == expected_sensitivity and len(summary["sensitivity"]) == len(expected_sensitivity), "missing/duplicate sensitivity configurations")


def validate_workbooks(root, groups):
    import xlrd
    cases = [("Case_1_ result_E.xls", "single", "healthy"), ("Case_2_ result_E.xls", "two", "healthy"),
             ("Case_3_ result_1_E.xls", "single", "fault_seed_0"), ("Case_3_ result_2_E.xls", "two", "fault_seed_0")]
    sheets, checked_cells = 0, 0
    for name, mode, suffix in cases:
        template = xlrd.open_workbook(str(root / "assets" / name))
        workbook = xlrd.open_workbook(str(root / "results/tables" / name))
        require(template.sheet_names() == workbook.sheet_names(), "official sheet names/order changed")
        for index, sheet in enumerate(workbook.sheets()):
            require(sheet.row_values(0) == template.sheet_by_index(index).row_values(0), "official result columns changed")
            group = index // 2 + 1 if suffix != "healthy" else index + 1
            if group not in groups:
                require(sheet.nrows == 1, "smoke test fabricated unexecuted group")
                continue
            trace = load(root / f"results/trace_group{group}_{mode}_{suffix}.json")
            if sheet.name.startswith("Failure"):
                events = trace["faults"]
                expected = [[f[k] for k in ("job", "cnc", "start", "end")] for f in events]
            else:
                jobs = {j["id"]: j for j in trace["jobs"]}
                expected = []
                for job_id in sorted(trace["completed_jobs"]):
                    row = [job_id]
                    for phase in (["0"] if mode == "single" else ["1", "2"]):
                        record = jobs[job_id]["phases"][phase]
                        row.extend(record[k] for k in ("cnc", "load_start", "unload_start"))
                    expected.append(row)
            require(sheet.nrows == len(expected) + 1, "result table row count differs from replayed trace")
            for row_index, values in enumerate(expected, 1):
                for col, expected_value in enumerate(values):
                    require(abs(sheet.cell_value(row_index, col) - expected_value) < 1e-6, f"table cell differs: {name}/{sheet.name}/{row_index}/{col}")
                    checked_cells += 1
            sheets += 1
    return sheets, checked_cells


def check(root):
    sys.path.insert(0, str(root))
    context = load(root / "run_context.json")
    values = {x["parameter_id"]: x["current_value"] for x in context["ParameterSet"]["entries"]}
    if context["ModelSpec"]["question"] == "Q1":
        import test_rgv
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_rgv))
        reported = load(root / "results/kernel_tests.json")
        require(result.wasSuccessful() and reported["success"] and result.testsRun == reported["tests"], "independent algorithm tests failed")
        description = load(root / "results/model_description.json")
        require(set(description["policies"]) == {"cyclic", "greedy", "oldest"} and description["single"] and description["two"] and description["fault"], "model description missing cases")
        return {"checks": [{"check_id": "algorithm_cases", "status": "pass", "evidence": ["results/kernel_tests.json", "results/model_description.json"]}],
                "metrics": {"algorithm_tests": result.testsRun}, "scope": "Restricted dispatch algorithms pass deterministic, fault and negative kernel cases; not global optimality"}
    from verify_schedule import verify
    groups, seeds = values["groups"], int(values["seed_count"])
    parameters = {p["group"]: p for p in load(root / "assets/official_parameters.json")["groups"]}
    traces, commands, counts = [], 0, {}
    for group, mode, suffix in itertools.product(groups, ("single", "two"), ("healthy", "fault_seed_0")):
        name = f"results/trace_group{group}_{mode}_{suffix}.json"
        trace = load(root / name)
        verified = verify(trace, parameters[group])
        commands += verified["commands_checked"]
        counts[f"g{group}_{mode}_{suffix}"] = verified["products_replayed"]
        traces.append(name)
    summary = load(root / "results/experiment_summary.json")
    with (root / "results/assignment_search.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {(g, policy, "-".join(map(str, assignment))) for g in groups for policy in ("cyclic", "greedy")
                for size in range(1, 8) for assignment in itertools.combinations(range(1, 9), size)}
    actual = {(int(row["group"]), row["policy"], row["first_machines"]) for row in rows}
    require(actual == expected and len(rows) == len(expected), "missing/duplicate tuning candidates")
    for group in groups:
        maximum = max(int(row["count"]) for row in rows if int(row["group"]) == group)
        require(maximum == counts[f"g{group}_two_healthy"], "selected result is not the observed finite-search maximum")
    validate_configuration_coverage(summary, groups)
    for entry in summary["faults"] + summary["sensitivity"]:
        validate_statistics(entry, seeds)
    for entry in summary["faults"]:
        require(entry["seeds"] == list(range(seeds)), "wrong seed ledger")
        require(entry["sample_counts"][0] == counts[f"g{entry['group']}_{entry['mode']}_fault_seed_0"], "seed-zero representative trace mismatch")
        validate_statistics({"sample_counts": entry["baseline_sample_counts"], **entry["baseline"]}, seeds)
        validate_statistics({"sample_counts": entry["sample_counts"][:16], **entry["prefix16"]}, min(seeds, 16))
    feasibility = load(root / "results/all_feasibility_checks.json")
    expected_checks = len(groups) * (3 + 508 + 2 + 4 + seeds * (4 + 18))
    require(len(feasibility) == summary["feasibility_checks_count"] == expected_checks and all(x["status"] == "pass" for x in feasibility), "internal simulation replay failed or omitted runs")
    sheets, cells = validate_workbooks(root, groups)
    return {"checks": [
        {"check_id": "trace_replay", "status": "pass", "evidence": traces, "commands_checked": commands},
        {"check_id": "tuning_accounting", "status": "pass", "evidence": ["results/assignment_search.csv", "results/experiment_summary.json"]},
        {"check_id": "monte_carlo", "status": "pass", "evidence": ["results/experiment_summary.json", "results/all_feasibility_checks.json"]},
        {"check_id": "official_tables", "status": "pass", "evidence": [f"results/tables/{name}" for name, _, _ in cases_for_output()]}],
        "metrics": {"trace_count": len(traces), "commands_checked": commands, "tuning_candidates": len(rows),
                    "workbooks": 4, "sheets_checked": sheets, "numeric_cells_checked": cells, "seed_count": seeds,
                    "feasibility_checks": len(feasibility), "delivered_counts": counts,
                    "fault_means": {f"g{x['group']}_{x['mode']}": x["selected"]["mean"] for x in summary["faults"]},
                    # validate_statistics above independently recomputed every
                    # mean, SD and interval from the actual sample ledger.
                    "fault_statistics": [{key: x[key] for key in ("group", "mode", "selected", "baseline", "prefix16")}
                                         for x in summary["faults"]],
                    "sensitivity_statistics": [{key: x[key] for key in ("group", "mode", "fault_probability", "repair_range",
                                                                        "n", "mean", "sd", "minimum", "maximum", "mean_ci95_normal")}
                                               for x in summary["sensitivity"]]},
        "scope": "Full retained finite search and fixed-configuration Monte Carlo; independent replay of representative traces and all numeric workbook cells; no global optimality or factory-generalization claim"}


def cases_for_output():
    return [("Case_1_ result_E.xls", "single", "healthy"), ("Case_2_ result_E.xls", "two", "healthy"),
            ("Case_3_ result_1_E.xls", "single", "fault_seed_0"), ("Case_3_ result_2_E.xls", "two", "fault_seed_0")]


if __name__ == "__main__":
    destination = Path(sys.argv[2])
    try:
        report = check(Path(sys.argv[1]))
    except Exception as exc:
        destination.write_text(json.dumps({"checks": [], "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
        raise
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
