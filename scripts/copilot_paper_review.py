"""Read-only preflight of declared writing/plot inputs; never a paper approval.

Existing Claim, PaperSection and DOCX source gates remain authoritative. This
adds CSV shape/finite/range checks and exact question/run-parameter provenance
for the actual files an author declares for tables or plots. It does not inspect
rendered pixels or infer the truth of prose, units or supplied range criteria.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
from pathlib import Path

from copilot_runtime import bind_file, object_errors, safe_path
from copilot_store import Store, digest

NONFINITE = re.compile(r"(?<![A-Za-z0-9_])(?:[+-]?(?:nan|inf(?:inity)?|∞))(?![A-Za-z0-9_])", re.I)


def _strings(value, name):
    if (not isinstance(value, list) or not value or
            any(not isinstance(x, str) or not x.strip() for x in value) or len(set(value)) != len(value)):
        raise ValueError(name + " 必须是非空、无重复的文本数组")
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_table(item):
    required = {"id", "question", "source_id", "result_id", "parameter_object_id", "path",
                "required_columns", "numeric_columns"}
    if not isinstance(item, dict) or set(item) != required:
        raise ValueError("表/绘图输入必须使用完整且无额外字段的材料合同")
    for key in required - {"required_columns", "numeric_columns"}:
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError(key + " 必须是非空文本")
    columns = _strings(item["required_columns"], "required_columns")
    numeric = item["numeric_columns"]
    if not isinstance(numeric, dict) or not numeric or not set(numeric) <= set(columns):
        raise ValueError("numeric_columns 必须为 required_columns 中至少一个列的合同")
    for column, rule in numeric.items():
        if (not isinstance(rule, dict) or not {"unit", "basis"} <= set(rule) or
                set(rule) - {"unit", "basis", "min", "max", "missing"} or
                any(not isinstance(rule[k], str) or not rule[k].strip() for k in ("unit", "basis"))):
            raise ValueError(column + " 需明确单位与检查依据；不能凭空设置物理范围")
        for key in ("min", "max"):
            if key in rule and not _finite(rule[key]):
                raise ValueError(column + " 范围须为有限数值")
        if rule.get("min", -math.inf) > rule.get("max", math.inf):
            raise ValueError(column + " 范围上下界颠倒")
        missing = rule.get("missing", {})
        if (not isinstance(missing, dict) or any(not isinstance(k, str) or not k.strip() or
                NONFINITE.search(k) or not isinstance(v, str) or not v.strip() for k, v in missing.items())):
            raise ValueError(column + " 缺失值须使用可读标记并附原因，不能用 nan/inf")


def _table_errors(raw, item):
    errors = []
    rows = list(csv.reader(io.StringIO(raw), strict=True))
    if not rows:
        return ["表为空"]
    header = rows[0]
    if not header or any(not h.strip() for h in header) or len(set(header)) != len(header):
        return ["表头为空或含重复列"]
    missing = set(item["required_columns"]) - set(header)
    if missing:
        errors.append("缺少题目/论文要求的列：" + ", ".join(sorted(missing)))
    if len(rows) < 2:
        errors.append("表没有数据行")
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(header):
            errors.append(f"第 {number} 行列数与表头不一致")
            continue
        for column, text in zip(header, row):
            text = text.strip()
            if NONFINITE.fullmatch(text):
                errors.append(f"第 {number} 行 {column} 暴露非有限数值 {text}")
                continue
            rule = item["numeric_columns"].get(column)
            if rule is None or text in rule.get("missing", {}):
                continue
            try:
                value = float(text)
            except ValueError:
                errors.append(f"第 {number} 行 {column} 不是数值或已解释的缺失标记")
                continue
            if not math.isfinite(value):
                errors.append(f"第 {number} 行 {column} 不是有限数值")
            elif not rule.get("min", -math.inf) <= value <= rule.get("max", math.inf):
                errors.append(f"第 {number} 行 {column} 超出声明范围；检查是否混入时间列/单位或字段映射错误")
    return errors


def review_materials(root, contract):
    """Return a mechanical screening report against one validated authority.

    The supplied contract describes the intended use, not verified scientific
    truth. Reading state and files again on every call detects same-revision
    drift. Nothing writes authority, marks a section verified, or sets Ready.
    """
    root = Path(root).resolve()
    if (not isinstance(contract, dict) or set(contract) != {"version", "tables", "manuscripts"}
            or contract["version"] != "0.1" or not isinstance(contract["tables"], list)
            or not isinstance(contract["manuscripts"], list)
            or not (contract["tables"] or contract["manuscripts"])):
        raise ValueError("使用 version=0.1、tables、manuscripts；不能以空检查声明通过")
    ids = []
    for item in contract["tables"]:
        _validate_table(item)
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("材料 id 重复")
    if contract["manuscripts"]:
        _strings(contract["manuscripts"], "manuscripts")
    store = Store(root / "state/decision_log.json")
    state = store.read()
    cp = state["copilot"]
    findings, files, sources = [], [], []

    for item in contract["tables"]:
        errors = []
        try:
            for oid in (item["source_id"], item["result_id"], item["parameter_object_id"]):
                errors.extend(object_errors(root, cp, oid))
            if errors:
                raise ValueError("；".join(dict.fromkeys(errors)))
            source = cp["objects"][item["source_id"]]
            result = cp["objects"][item["result_id"]]
            parameter = cp["objects"][item["parameter_object_id"]]
            if result["kind"] != "ResultRecord" or result["status"] != "verified":
                raise ValueError("结果须来自当前已实际验证的 ResultRecord")
            if source["kind"] not in {"ArtifactRecord", "ResultRecord"}:
                raise ValueError("材料来源须为 ResultRecord 或依赖该结果的 ArtifactRecord")
            if source["id"] != result["id"] and result["id"] not in source["dependencies"]:
                raise ValueError("派生材料必须直接绑定所用的 ResultRecord")
            if source["kind"] == "ArtifactRecord" and {oid for oid in source["dependencies"]
                    if cp["objects"][oid]["kind"] == "ResultRecord"} != {result["id"]}:
                raise ValueError("单张材料合同只能对应一个结果工况；多结果比较须分开声明或由比较检查器生成结果")
            run_id = result["payload"]["run_id"]
            run = cp["objects"][run_id]
            if run["kind"] != "RunRecord" or run["payload"]["question"] != item["question"]:
                raise ValueError("材料所属小问与实际运行不一致，不能借用另一问的相同数字")
            if (parameter["kind"] != "ParameterSet" or parameter["id"] not in run["dependencies"] or
                    parameter["payload"]["parameter_set_id"] != run["payload"]["parameter_set_id"]):
                raise ValueError("工况/参数版本与实际运行不一致")
            bound = [f for f in source["files"] if f["path"] == item["path"]]
            if len(bound) != 1 or Path(item["path"]).suffix.lower() != ".csv":
                raise ValueError("当前检查器只读取来源对象明确绑定的 CSV；Excel 请先导出并登记派生表")
            target = safe_path(root, item["path"])
            errors.extend(_table_errors(target.read_text(encoding="utf-8-sig"), item))
            # Recheck after reading, so a file changed during this review does
            # not get reported as a successfully screened current input.
            errors.extend(object_errors(root, cp, item["source_id"]))
            files.append(bind_file(root, item["path"]))
            sources.append({"id": item["id"], "question": run["payload"]["question"],
                            "run_id": run_id, "parameter_object_id": parameter["id"]})
        except (ValueError, OSError, UnicodeError, KeyError, csv.Error) as exc:
            errors.append(str(exc))
        findings.extend({"material": item["id"], "message": error} for error in dict.fromkeys(errors))

    for reference in contract["manuscripts"]:
        try:
            path = safe_path(root, reference)
            if path.suffix.lower() not in {".md", ".txt"}:
                raise ValueError("正文筛查只支持 UTF-8 Markdown/TXT；DOCX 来源和 PDF 排版须用既有检查")
            before = bind_file(root, reference)
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if NONFINITE.search(line):
                    findings.append({"material": reference, "message": f"第 {number} 行含 nan/inf 等程序值；解释缺失原因或核对正文是否为技术说明"})
            if before != bind_file(root, reference):
                raise ValueError("正文在读取期间发生变化，请重试")
            files.append(before)
        except (ValueError, OSError, UnicodeError) as exc:
            findings.append({"material": reference, "message": str(exc)})
    if store.read()["copilot"]["state_hash"] != cp["state_hash"]:
        findings.append({"material": "authority", "message": "检查期间权威版本已变化，请按新版本重试"})
    return {"passed": not findings, "scope": "declared_materials_mechanical_preflight",
            "revision": cp["revision"], "authority_sha256": cp["state_hash"],
            "contract_sha256": digest(contract), "findings": findings, "files": files, "sources": sources,
            "not_verified": ["物理模型与数值计算正确性", "正文语义与因果归因", "范围与单位合同的科学依据",
                             "未声明材料的完整性", "实际图片数据映射、字体和 PDF 页面", "作者确认和正式交付就绪"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查论文/绘图 CSV 输入和正文非有限值，不改变核验或交付状态")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--contract", required=True, help="项目内材料合同 JSON 相对路径")
    args = parser.parse_args(argv)
    try:
        contract = json.loads(safe_path(args.workspace, args.contract).read_text(encoding="utf-8-sig"))
        result = review_materials(args.workspace, contract)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"passed": False, "input_error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
