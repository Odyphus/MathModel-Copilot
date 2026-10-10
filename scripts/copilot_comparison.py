"""Declared comparison context, checked numeric sources and explicit limits."""
from __future__ import annotations
import re

CONTEXT = {"time_grid", "information", "horizon", "boundary", "commitments", "costs", "split", "budget"}


def validate_declaration(value, outputs):
    if not isinstance(value, dict) or set(value) != {"schema_version", "group", "title", "source_files", "variants"} or value["schema_version"] != "1.0":
        raise ValueError("比较声明须使用完整的 1.0 字段")
    for key in ("group", "title"):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 200:
            raise ValueError("比较 group/title 必须为非空短文本")
    sources = value["source_files"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("比较必须绑定实际源文件")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"path", "sha256"} or not isinstance(source["path"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", str(source["sha256"])):
            raise ValueError("比较源文件须声明 path/sha256")
    if len({s["path"] for s in sources}) != len(sources):
        raise ValueError("比较源文件重复")
    variants = value["variants"]
    if not isinstance(variants, list) or not 2 <= len(variants) <= 16:
        raise ValueError("比较须声明 2..16 个方案")
    output_paths = {}
    for output in outputs:
        path = output.get("metric_path", "/" + str(output.get("name", "")).replace("~", "~0").replace("/", "~1"))
        output_paths.setdefault(path, []).append(output)
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) != {"id", "label", "method", "backend", "metric_path", "direction", "context"}:
            raise ValueError("比较方案缺少字段或含未知字段")
        for key in ("id", "label", "method", "backend"):
            if not isinstance(variant[key], str) or not variant[key].strip() or len(variant[key]) > 500:
                raise ValueError("比较方案标识/解释必须为非空短文本")
        if variant["direction"] not in {"lower", "higher"}:
            raise ValueError("比较方向须为 lower/higher")
        matched = output_paths.get(variant["metric_path"], [])
        if len(matched) != 1 or not isinstance(matched[0].get("unit"), str) or not matched[0]["unit"].strip():
            raise ValueError("比较指标须对应唯一、有明确单位的模型输出")
        context = variant["context"]
        if not isinstance(context, dict) or set(context) != CONTEXT or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in context.values()):
            raise ValueError("比较必须明确时间网格、信息、时域、边界、承诺、费用、划分及预算；不适用须说明")
    if len({v["id"] for v in variants}) != len(variants):
        raise ValueError("比较方案 id 重复")


def _models(cp, obj):
    todo, seen, result = list(obj.get("dependencies", [])), set(), []
    while todo:
        key = todo.pop()
        if key in seen:
            continue
        seen.add(key)
        item = cp["objects"].get(key, {})
        if item.get("kind") == "ModelSpec":
            result.append((key, item))
        todo.extend(item.get("dependencies", []))
    return result


def comparison_view(cp, objects):
    """Derived only from the current live observation; never writes rankings."""
    groups = {}
    for oid, result in objects.items():
        if result.get("kind") != "ResultRecord":
            continue
        models = _models(cp, result)
        for model_id, model in models:
            declaration = model.get("payload", {}).get("data_contract", {}).get("comparison")
            if declaration is None:
                continue
            metadata = declaration if isinstance(declaration, dict) else {}
            raw_group = metadata.get("group")
            label = raw_group if isinstance(raw_group, str) else "invalid-comparison"
            key = (model.get("payload", {}).get("question"), label)
            group = groups.setdefault(key, {"question": key[0], "group": key[1], "title": metadata.get("title") if isinstance(metadata.get("title"), str) else "比较声明需修正", "rows": []})
            try:
                validate_declaration(declaration, model["payload"].get("outputs", []))
            except (ValueError, KeyError, TypeError) as exc:
                group.setdefault("errors", []).append(str(exc))
                continue
            details = result.get("metric_details", {}).get("items", [])
            for variant in declaration["variants"]:
                metrics = [m for m in details if m["metric_path"] == variant["metric_path"]]
                metric = metrics[0] if len(metrics) == 1 else None
                current = result.get("is_current") and not result.get("current_errors") and result.get("effective_status") == "verified"
                checked = bool(current and metric and metric.get("declaration_status") == "declared")
                group["rows"].append({**variant, "result_id": oid, "model_id": model_id,
                                      "source_files": declaration["source_files"], "value": metric["value"] if metric else None,
                                      "unit": metric.get("unit") if metric else None, "checked": checked,
                                      "status": "verified" if checked else "stale" if result.get("effective_status") == "stale" or result.get("current_errors") else "pending"})
    for group in groups.values():
        candidates = [r for r in group["rows"] if r["checked"]]
        reasons = []
        if len(candidates) < 2:
            reasons.append("缺少至少两项当前已核验的指标")
        if candidates:
            first = candidates[0]
            for label in CONTEXT:
                if len({r["context"][label] for r in candidates}) > 1:
                    reasons.append("比较条件不同：" + label)
            for label in ("source_files", "unit", "direction"):
                if any(r[label] != first[label] for r in candidates[1:]):
                    reasons.append("比较来源、单位或方向不同：" + label)
        reasons.extend(group.get("errors", []))
        group["comparable"] = not reasons
        group["reasons"] = reasons
        # No "winner": an equal context is a declared scope, not model validity.
        group["scope"] = "在登记条件与具体检查范围内比较；策略与后端差异单独展示，不推导算法速度或普遍优劣。"
    return list(groups.values())
