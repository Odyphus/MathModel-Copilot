"""Run the retained 2018B solver using the Runtime's frozen input snapshot."""
from __future__ import annotations
import io
import json
from pathlib import Path
import unittest

CASES = [("Case_1_ result_E.xls", "single", "healthy"),
         ("Case_2_ result_E.xls", "two", "healthy"),
         ("Case_3_ result_1_E.xls", "single", "fault_seed_0"),
         ("Case_3_ result_2_E.xls", "two", "fault_seed_0")]


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def export_workbooks(groups):
    import xlrd
    import xlwt
    target = Path("results/tables")
    target.mkdir(parents=True, exist_ok=True)
    counts = []
    for name, mode, suffix in CASES:
        template = xlrd.open_workbook(str(Path("assets") / name))
        book = xlwt.Workbook(encoding="utf-8")
        for index, sheet in enumerate(template.sheets()):
            group = index // 2 + 1 if suffix != "healthy" else index + 1
            output = book.add_sheet(sheet.name)
            for col, label in enumerate(sheet.row_values(0)):
                output.write(0, col, label)
                output.col(col).width = 22 * 256
            # Smoke mode deliberately keeps unexecuted groups blank and labels
            # its scope; it must never be presented as a complete benchmark.
            if group not in groups:
                counts.append({"file": name, "sheet": sheet.name, "rows": 0, "group": group, "executed": False})
                continue
            trace = json.loads(Path(f"results/trace_group{group}_{mode}_{suffix}.json").read_text(encoding="utf-8"))
            if sheet.name.startswith("Failure"):
                rows = [[f["job"], f["cnc"], f["start"], f["end"], f"discarded; phase {f['phase']}; seed 0"] for f in trace["faults"]]
            else:
                completed = set(trace["completed_jobs"])
                rows = []
                for job in trace["jobs"]:
                    if job["id"] not in completed:
                        continue
                    phases = [job["phases"][key] for key in (["0"] if mode == "single" else ["1", "2"])]
                    row = [job["id"]]
                    for phase in phases:
                        row += [phase["cnc"], phase["load_start"], phase["unload_start"]]
                    row.append(f"delivered {job['delivered']:.3f}s; command-start convention")
                    rows.append(row)
            for row_index, row in enumerate(rows, 1):
                for col, value in enumerate(row):
                    output.write(row_index, col, value)
            counts.append({"file": name, "sheet": sheet.name, "rows": len(rows), "group": group, "executed": True})
        book.save(str(target / name))
    write("results/table_manifest.json", counts)


def main():
    context = json.loads(Path("run_context.json").read_text(encoding="utf-8"))
    question = context["ModelSpec"]["question"]
    values = {x["parameter_id"]: x["current_value"] for x in context["ParameterSet"]["entries"]}
    parameters = json.loads(Path("assets/official_parameters.json").read_text(encoding="utf-8"))["groups"]
    if values["official_table"] != parameters:
        raise ValueError("Frozen parameter table differs from the retained official-source transcription")
    if question == "Q1":
        import test_rgv
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_rgv))
        write("results/kernel_tests.json", {"tests": result.testsRun, "failures": len(result.failures),
              "errors": len(result.errors), "success": result.wasSuccessful(), "log": stream.getvalue()})
        write("results/model_description.json", {"question": "Q1", "policies": ["cyclic", "greedy", "oldest"],
              "single": "one machining phase on any CNC", "two": "fixed tools with ordered transfer",
              "fault": "observed-state event scheduling; failed material discarded before repair",
              "source": "rgv_simulator.py", "limitations": ["restricted heuristics", "no global optimality proof",
              "one intermediate part", "immediate clean and delivery", "fault timing distributions are assumptions"]})
        if not result.wasSuccessful():
            raise SystemExit(1)
    elif question == "Q2":
        import rgv_simulator as simulation
        simulation.ROOT = Path.cwd()
        simulation.PARAMETERS = [p for p in values["official_table"] if p["group"] in values["groups"]]
        simulation.main(int(values["seed_count"]))
        export_workbooks(values["groups"])
    else:
        raise ValueError("The official problem has exactly two tasks")


if __name__ == "__main__":
    main()
