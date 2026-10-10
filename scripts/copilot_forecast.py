"""Explicit local rolling forecast reports; no authority mutation or tuning."""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

from copilot_data import DataError, binding, project_path

STARTER = Path(__file__).resolve().parents[1] / "templates/shared/code_starter/forecasting.py"
spec = importlib.util.spec_from_file_location("_copilot_forecasting", STARTER)
forecasting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forecasting)


def evaluate(root, reference):
    declaration = json.loads(project_path(root, reference).read_text(encoding="utf-8-sig"))
    forecasting.fields(declaration, {"schema_version", "source", "columns", "unit", "policy"}, "回测声明")
    if declaration["schema_version"] != "1.0" or not isinstance(declaration["unit"], str) or not declaration["unit"].strip():
        raise DataError("回测 schema_version 必须为 1.0，并明确目标单位")
    forecasting.fields(declaration["source"], {"path", "encoding"}, "source")
    columns = declaration["columns"]
    forecasting.fields(columns, {"time", "available_at", "value"}, "columns")
    if any(not isinstance(c, str) or not c.strip() for c in columns.values()) or len(set(columns.values())) != 3:
        raise DataError("columns 须声明三个不同的源列名")
    source = project_path(root, declaration["source"]["path"])
    with source.open(encoding=declaration["source"]["encoding"], newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not set(columns.values()) <= set(reader.fieldnames):
            raise DataError("源表列名重复或缺少声明列")
        rows = []
        for row in reader:
            if None in row:
                raise DataError("源表行列数不一致")
            try:
                rows.append({"time": row[columns["time"]], "available_at": row[columns["available_at"]], "value": float(row[columns["value"]])})
            except (TypeError, ValueError) as exc:
                raise DataError("目标值缺失或非数值") from exc
    report = forecasting.rolling_backtest(rows, declaration["policy"])
    report["unit"] = declaration["unit"]
    report["bindings"] = {"source": binding(root, declaration["source"]["path"]), "spec": binding(root, reference),
                          "implementation_sha256": hashlib.sha256(STARTER.read_bytes()).hexdigest().upper()}
    return report


def run(root, reference, output):
    target = project_path(root, output, exists=False)
    if target.exists():
        raise DataError("回测报告已存在；请使用新路径保留旧证据")
    report = evaluate(root, reference)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return {"report": output, "metrics": report["metrics"], "unit": report["unit"], "verified": False,
            "scope": "本地回测产物；尚未登记并通过独立检查"}


def verify(root, reference, output):
    saved = json.loads(project_path(root, output).read_text(encoding="utf-8"))
    if saved != evaluate(root, reference):
        raise DataError("回测报告与当前源数据、策略或实现不一致")
    return {"report": output, "replayed": True, "verified": False,
            "scope": "同实现重放一致；不能代替独立校验或模型有效性判断"}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("run", "replay"):
        command = commands.add_parser(name)
        command.add_argument("--project-root", required=True, type=Path)
        command.add_argument("--spec", required=True, help="项目相对 JSON：source/columns/unit/policy；示例 templates/copilot/forecast_spec.json")
        command.add_argument("--output", required=True, help="项目相对报告 JSON；run 不覆盖旧文件")
    return p


def execute(args):
    function = run if args.command == "run" else verify
    return function(args.project_root, args.spec, args.output)


if __name__ == "__main__":
    print(json.dumps(execute(parser().parse_args()), ensure_ascii=False, indent=2, allow_nan=False))
