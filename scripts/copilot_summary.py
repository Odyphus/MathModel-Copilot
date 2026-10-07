"""Generate a dated factual report from the same live observation as the page.

No chat text, external completion report or directory name grants verification.
The Markdown is a point-in-time projection, never a second state store.
"""
from __future__ import annotations

import copy
import html
import json
import os
from pathlib import Path

from copilot_runtime import safe_path
from copilot_view import snapshot


def _text(value):
    value = str(value).replace("\n", " ").replace("\r", " ")
    for char in "\\`*_[]|#":
        value = value.replace(char, "\\" + char)
    return html.escape(value)


def _untracked(root, bound, *, exclude=None, limit=2000):
    """Observe names only in ordinary output folders; never follow links."""
    found, visited, omitted, errors = [], 0, False, []
    def redirected(path):
        # Junctions are not symlinks on Windows. Resolving to a different
        # absolute path also excludes them on Python versions without is_junction.
        return path.is_symlink() or path.resolve() != path.absolute()
    for folder in ("results", "outputs", "paper_output"):
        base = root / folder
        if not base.is_dir() or redirected(base):
            continue
        def unreadable(error):
            errors.append(folder)
        for directory, dirs, files in os.walk(base, followlinks=False, onerror=unreadable):
            dirs[:] = sorted(d for d in dirs if not redirected(Path(directory) / d))
            for name in sorted(files):
                path = Path(directory) / name
                if path.is_symlink():
                    continue
                visited += 1
                if visited > limit:
                    omitted = True
                    break
                relative = path.relative_to(root).as_posix()
                if relative not in bound and relative != exclude:
                    found.append(relative)
            if omitted:
                break
        if omitted:
            break
    return {"files": found, "truncated": omitted, "unreadable_folders": sorted(set(errors)),
            "scope": "results, outputs, paper_output; filenames only; no links"}


def _lineage(view, oid):
    seen, pending = set(), [oid]
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        obj = view["objects"].get(item)
        if obj:
            pending.extend(obj.get("dependencies", []))
    return [
        {"id": key, "kind": obj["kind"], "status": obj["effective_status"],
         "current": obj["is_current"], "files": copy.deepcopy(obj.get("files", []))}
        for key in sorted(seen) if (obj := view["objects"].get(key))
    ]


def _facts(view, untracked):
    current = set(view["status"]["current_objects"].values())
    results = []
    for oid, obj in view["objects"].items():
        if obj["kind"] != "ResultRecord" or oid not in current or obj["effective_status"] != "verified":
            continue
        payload = obj["payload"]
        results.append({"id": oid, "question": payload.get("question"),
                        "metrics": copy.deepcopy(payload.get("metrics", {})),
                        "metric_details": copy.deepcopy(obj.get("metric_details", {})),
                        "scope": payload.get("scope", ""),
                        "lineage": _lineage(view, oid)})
    return {"identity": copy.deepcopy(view["identity"]),
            "requirements": copy.deepcopy(view["status"]["requirements"]),
            "submission": copy.deepcopy(view["status"]["submission"]),
            "blockers": copy.deepcopy(view["status"]["blockers"]),
            "tasks": [{"id": key, "title": item.get("title", ""),
                       "status": item.get("effective_status", item.get("status", "unknown"))}
                      for key, item in view["tasks"].items()],
            "results": results, "decisions": copy.deepcopy(view["decisions"]),
            "untracked_outputs": untracked}


def _markdown(value):
    facts = value["report_facts"]
    reqs, submission = facts["requirements"], facts["submission"]
    title = facts["identity"].get("title") or facts["identity"]["workspace_name"]
    rows = ["# 项目进展简报", "", f"项目：{_text(title)}",
            f"观察时间：{_text(value['observed_at'])}（UTC）", "",
            "这份简报由当前权威状态和绑定文件检查生成，仅代表本次观察时刻。",
            "", f"- 已核验需求：**{reqs['verified']} / {reqs['total']}**。",
            f"- 已声明小问：**{len(reqs['questions'])}**；未建立需求的小问也计入待完成。",
            f"- 当前可用的已核验结果：**{len(facts['results'])}** 份。",
            "- 提交条件：**" + ("当前检查通过" if submission.get("ready") else "尚未满足") + "**。",
            "", "程序检查通过不代表实际提交、人工终审或科学结论已获外部确认。", "", "## 各问进展", ""]
    if not reqs["questions"]:
        rows.append("尚未声明完整小问范围，不能声称全题完成。")
    for question, status in reqs["questions"].items():
        label = "第" + question[1:] + "问" if question.startswith("Q") and question[1:].isdigit() else question
        rows.append(f"- {_text(label)}：{'已核验' if status == 'verified' else '仍有未完成或待重检的要求'}。")
    rows += ["", "## 当前结果", ""]
    if not facts["results"]:
        rows.append("当前没有可用于完成声明的已核验结果。磁盘上有文件、聊天中有数值或报告自述PASS，都不会改变这一状态。")
    for index, result in enumerate(facts["results"], 1):
        rows += [f"### 结果 {index} · {_text(result['question'])}", "",
                 "适用范围：" + (_text(result["scope"]) if result["scope"] else "尚未在结果中登记；请核对来源模型与参数。"), "",
                 "指标名称与单位来自模型声明，声明本身不等于单位科学核验；未登记的信息不会补猜。", ""]
        items = result["metric_details"].get("items", [])
        for number, item in enumerate(items[:20], 1):
            name = item.get("label") or f"指标{number}（名称尚未登记）"
            unit = item.get("unit") or "单位尚未登记"
            rows.append(f"- {_text(name)}：{_text(item['value'])}；{_text(unit)}。")
        if len(items) > 20 or result["metric_details"].get("truncated"):
            rows.append("此处仅列前20项；请展开查看完整原始指标。")
        rows += ["", "<details><summary>完整原始指标</summary>", "",
                 "<pre>" + html.escape(json.dumps(result["metrics"], ensure_ascii=False, indent=2)) + "</pre>", "", "</details>", ""]
    rows += ["", "## 仍需处理", ""]
    blockers = list(dict.fromkeys(facts["blockers"] + submission.get("blockers", [])))
    # Keep exact originals in report_facts, including unrecognized reasons.
    labels = {
        "No current passing delivery audit": "当前论文和提交材料还没有通过完整检查。",
        "Historical/research checks are not formal submission readiness": "目前完成的是练习或研究检查，还不能据此确认可以正式提交。",
        "Package has not entered awaiting_submission": "提交材料还没有进入待提交状态。",
        "Formal visual review requires a human reviewer": "正式提交前，还需要人工检查论文排版。",
    }
    rows += ["- " + _text(labels.get(item, item)) for item in blockers] if blockers else ["当前机械检查没有列出阻塞项；请按赛事要求完成实际人工审阅与提交。"]
    untracked = facts["untracked_outputs"]
    rows += ["", "## 尚未登记来源的输出", "",
             "这里只列文件名，不读取或采信其中的完成声明。旧版简报也可能在此列出；本次观察的导出目标除外。"]
    rows += ["- " + _text(path) for path in untracked["files"]] if untracked["files"] else ["本次扫描范围内未发现未登记文件。"]
    if untracked["truncated"]:
        rows.append("扫描已到数量上限，列表不完整，不能据此断言其余文件已登记。")
    if untracked["unreadable_folders"]:
        rows.append("部分输出目录未能读取，扫描不完整：" + "、".join(_text(x) for x in untracked["unreadable_folders"]))
    rows += ["", "<details><summary>核查来源与版本（按需展开）</summary>", "",
             "<pre>" + html.escape(json.dumps({key: item for key, item in value.items() if key != "markdown"}, ensure_ascii=False, indent=2)) + "</pre>", "", "</details>", ""]
    return "\n".join(rows)


def _report_target(root, output):
    target = safe_path(root, output, exists=False)
    # Windows strips trailing spaces/dots from ordinary path components. Reject
    # those aliases on every platform so a report never enters an authority
    # directory by using, for example, "state./report.md".
    parts = output.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
    if any(part not in {"", "."} and (
            part != part.rstrip(" .") or part.split(".", 1)[0].upper() in reserved)
           for part in parts):
        raise ValueError("简报路径含不明确的目录或文件别名；请使用普通项目相对路径")
    relative = target.relative_to(root)
    forbidden = {"state", ".copilot", ".git"}
    if target.suffix.lower() != ".md" or not relative.parts or relative.parts[0].casefold() in forbidden:
        raise ValueError("简报必须保存为项目内的新 Markdown 文件，不能写入状态或运行目录")
    return target


def report(workspace, output=None):
    root = Path(workspace).resolve()
    target = None
    if output is not None:
        target = _report_target(root, output)
        if target.exists():
            raise ValueError("简报目标已存在；请选择新文件名，不覆盖历史证据")
    view = snapshot(root)
    value = {"schema": "mathmodel-copilot.factual-report/v1", "project_id": view["project_id"],
             "revision": view["revision"], "observed_at": view["checked_at"],
             "source_snapshot_id": view["snapshot_id"],
             "authority_file_sha256": view["authority_file_sha256"],
             "file_observation_hash": view["file_observation_hash"],
             "report_facts": _facts(view, _untracked(root, set(view["observed_files"]), exclude=output))}
    value["markdown"] = _markdown(value)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after directory creation; do not follow an existing final symlink.
        resolved = _report_target(root, output)
        if resolved != target:
            raise ValueError("简报目标在写入前发生变化")
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value["markdown"])
        value["saved_to"] = output
    return value
