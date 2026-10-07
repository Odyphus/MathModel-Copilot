"""Read-only payload guidance; business validation remains in Runtime/Store."""
from __future__ import annotations

import copy
import inspect

# Runtime.configure deliberately collects these project labels in **metadata.
# This allowlist describes that public interface, never arbitrary extra fields.
CONFIGURE_METADATA = {"title", "letter", "deadline_iso", "team_size"}
TARGETS = ("configure", "run", "validate", "stage-record", "decide", "register",
           "interpretation", "interpretation-review")


def fields_for(function, supplied=(), extra=()):
    parameters = inspect.signature(function).parameters
    allowed = {name for name, p in parameters.items()
               if name not in {"self", *supplied}
               and p.kind not in {p.VAR_KEYWORD, p.VAR_POSITIONAL}}
    required = {name for name in allowed if parameters[name].default is inspect.Parameter.empty}
    return allowed | set(extra), required


def check_keywords(command, payload, function, *, supplied=(), extra=()):
    """Report boundary errors before calling the unchanged transactional API."""
    if not isinstance(payload, dict):
        raise ValueError(command + " payload 必须是 JSON/YAML object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(command + " payload 字段名必须是字符串")
    allowed, required = fields_for(function, supplied, extra)
    unknown = set(payload) - allowed
    missing = required - set(payload)
    if unknown or missing:
        problems = []
        if unknown:
            problems.append("未知字段：" + "、".join(sorted(unknown)))
        if missing:
            problems.append("缺少字段：" + "、".join(sorted(missing)))
        guidance = "payload-help " + command if command in TARGETS else command + " --help 及统一执行协议"
        raise ValueError(command + " payload " + "；".join(problems) +
                         "。允许字段：" + "、".join(sorted(allowed)) +
                         "。字段不会被忽略；请查看 " + guidance)
    return payload


def payload_help(command, kind=None):
    from copilot_runtime import Runtime
    if kind is not None and command not in {"register", "interpretation", "interpretation-review"}:
        raise ValueError("--kind 仅用于 payload-help register / interpretation / interpretation-review")
    if command in {"interpretation", "interpretation-review"}:
        return interpretation_help(command, kind)
    examples = {
        "configure": {"question_count": 3, "evaluation_mode": "historical_benchmark",
                      "problem_year": 2018, "rules_year": 2026, "title": "历史题练习"},
        "run": {"question": "Q1", "argv": ["{python}", "solver.py"], "outputs": ["result.json"],
                "dependencies": ["model.Q1@1", "params.Q1@1", "data.Q1@1", "code.Q1@1", "plan.Q1@1"],
                "seed": "0", "timeout": 60},
        "validate": {"checker": "checker.py", "argv": ["{python}", "{checker}", "{run}", "{report}"],
                     "report": "validation.json", "timeout": 60},
        "stage-record": {"stage": 2, "details": {"notes": "已完成题面初步分析，具体结论见登记的题意合同"}},
        "decide": {"decision": "先验证基线模型", "reason": "先检验关键约束，再比较复杂候选的实际增益", "evidence": []},
    }
    descriptions = {
        "question_count": "从完整真实题面确定的小问总数；正整数，不得猜测或缩小已登记全集",
        "problem_year": "题目年份；示例年份仅为历史练习占位", "rules_year": "实际核对的规则年份",
        "evaluation_mode": "formal_contest / historical_benchmark / open_research；正式比赛题目与规则年份须一致",
        "stage": "导航阶段 0–9，不是完成或核验状态", "mode": "fast / standard / championship",
        "task_type": "已识别的问题类型", "qi_weights": "完整小问 ID 到权重的对象，例如 Q1: 1.0",
        "title": "项目标题（顶层字段）", "letter": "题号（顶层字段）",
        "deadline_iso": "真实截止时间；未知可省略", "team_size": "真实队伍人数",
        "question": "本次运行所属小问，须与绑定模型一致", "argv": "与预先登记的 CodeManifest 或 checker 完全一致的参数数组",
        "outputs": "本次必须实际生成的相对路径，不得覆盖输入", "dependencies": "当前有效的模型、参数、数据、代码、验证计划对象版本 ID",
        "seed": "本次记录的种子；不等于已设置所有外部库的随机性", "timeout": "正数秒；超时不会报告成功",
        "checker": "验证计划在运行前锁定的项目内 Python 文件", "report": "检查器生成的报告相对路径",
        "details": "阶段说明对象；完成度、需求全集、核验等受保护事实须走专用入口",
        "decision": "实际决定的内容，不自动形成用户批准或模型变更", "reason": "决定的依据和取舍",
        "evidence": "已存在的项目内证据文件路径数组；没有证据时保持空数组，不编造",
    }
    methods = {
        "configure": (Runtime.configure, {"revision", "actor"}, CONFIGURE_METADATA),
        "run": (Runtime.execute, {"revision", "actor", "request_id"}, ()),
        "validate": (Runtime.validate_run, {"revision", "run_id", "actor"}, ()),
        "stage-record": (Runtime.record_stage, {"revision", "actor"}, ()),
    }
    notes = ["本命令只解释输入，不读取或修改项目状态。示例不是运行回执。",
             "将 example 保存为项目内 JSON，通过原命令 --payload 引用；写入仍需当前 --expected-revision。"]
    if command in methods:
        allowed, required = fields_for(*methods[command])
    elif command == "decide":
        allowed, required = {"decision", "reason", "evidence"}, {"decision", "reason"}
    elif command == "register":
        if kind != "ValidationPlan":
            raise ValueError("payload-help register 当前支持 --kind ValidationPlan；其他源契约参考 templates/copilot 和统一执行协议")
        example = {"question": "Q1", "checker": {"path": "checker.py", "sha256": "<实际 checker.py 的 SHA-256>",
                   "argv": ["{python}", "{checker}", "{run}", "{report}"]},
                   "checks": [{"check_id": "known", "applicability": "required", "method": "独立加法复算两倍长度",
                              "criterion": "输出 value 必须等于输入长度独立相加所得的精确值", "evidence_target": "result.json"}]}
        return {"command": command, "kind": kind, "required_fields": ["question", "checker", "checks"],
                "fields": {"question": "与依赖的唯一 ModelSpec 小问一致", "checker": "实际文件路径、SHA-256 和执行 argv",
                           "checks": "覆盖模型全部预定 check_id；method 说明如何检查，criterion 给出预先确定的通过标准"},
                "example": example, "notes": notes + [
                    "这是两倍长度演示的最小计划。按真实题目替换 check_id、方法、判据、单位和证据路径，不能原样套用算例标准。",
                    "SHA-256 必须从已保存的真实检查器计算；空值或占位不能注册。命令另需 --kind ValidationPlan --key plan.Q1 --depends 当前模型ID。",
                    "注册计划并不运行检查器，也不会产生 verified Result。"]}
    else:
        raise ValueError("无此 payload 帮助主题：" + str(command))
    if command in {"run", "validate"}:
        notes.append("示例中的文件及对象 ID 必须替换为本项目实际登记值；本命令不会自动登记依赖或补造结果。")
    if command == "configure":
        notes.append("不支持把 title 等字段包进 metadata，也不支持 years/status/ready 等别名；未知字段将被明确拒绝。")
    return {"command": command, "required_fields": sorted(required), "allowed_fields": sorted(allowed),
            "fields": {name: descriptions.get(name, "参见统一执行协议") for name in sorted(allowed)},
            "example": copy.deepcopy(examples[command]), "notes": notes}


def interpretation_help(command, kind):
    from pathlib import Path
    import copilot_domain as domain
    from copilot_interpretation import FIELDS, validate_payload
    from copilot_runtime import Runtime
    notes = ["只读字段帮助，不读取或修改项目；示例描述的是假想题面，请按当前题面替换，不当作已确认事实。",
             "先 configure question_count 并规划同问 ReqID，再登记已知歧义/假设，随后登记或冻结题意合同；不要先冻结合同，再把歧义留在 notes。",
             "全部写入仍经原 Runtime/Store 和 expected revision；received、采用、数学验证与人类身份不是同一件事。"]
    if kind is None:
        # A discoverable overview is more useful than a parser error to a first-time caller.
        return {"command": command, "kinds": sorted(FIELDS), "next_commands": [
                f"payload-help {command} --kind {name}" for name in sorted(FIELDS)], "notes": notes}
    if kind not in FIELDS:
        raise ValueError("interpretation 帮助的 --kind 仅支持 AmbiguityEntry / AssumptionEntry")
    filename = "ambiguity_entry.yaml" if kind == "AmbiguityEntry" else "assumption_entry.yaml"
    example = domain.load_structured(Path(__file__).resolve().parents[1] / "templates/copilot" / filename)
    cls = domain.AmbiguityEntry if kind == "AmbiguityEntry" else domain.AssumptionEntry
    # Exercise the real stateless validator for the maintained example; do not
    # duplicate the transactional record/review acceptance rules here.
    validate_payload(kind, cls(**example).to_dict())
    descriptions = {
        "ambiguity_id": "稳定 ASCII 标识；同一歧义修订沿用此 ID", "assumption_id": "稳定 ASCII 标识；同一假设修订沿用此 ID",
        "question": "已在 question_count 声明的小问，例如 Q1", "source_anchor": "题面具体段落、附件列或公式出处",
        "interpretations": "至少两个真实可区分的解释，不能只写待确认", "severity": "low / medium / high / critical；按真实影响记录",
        "impact": "不同解释或假设影响哪些目标、约束、结果", "owner": "实际负责处理的角色或成员，不虚构身份",
        "requirement_ids": "同问非空 ReqID 数组，例如 REQ-Q1-001；须与随后合同一致",
        "linked_requirement_ids": "同问非空 ReqID 数组；覆盖关联歧义的全部要求",
        "statement": "拟采用的明确假设，不能冒充题目给定条件", "rationale": "当前依据、取舍与局限，不虚构确认",
        "testability": "如何检验假设、何种结果会推翻它", "linked_ambiguity_ids": "同问当前有效歧义的稳定 ambiguity_id；没有则 []",
        "reversible": "布尔值，是否能撤回后重跑", "sensitivity_required": "布尔值，是否需要敏感性分析",
        "validation_plan": "采用前必须给出的验证方法说明", "validation_checks": "采用前必须列明的预定 check_id 数组；验证时匹配真实结果",
        "status": "初次登记或修订只能 open（歧义）/ proposed（假设），可省略以使用默认",
        "evidence_refs": "当前实际存在的项目内来源文件；无则 []，不代表已经审核",
        "legacy_refs": "可选 [{stage: '2', index: 0}]，显式迁入旧 Stage 自由文本；API生成来源哈希，不允许用户写 legacy_sources",
        "action": "歧义：resolve/reopen；假设：accept/reject/reopen/validate，受当前状态约束",
        "evidence_files": "真实项目内来源文件数组；resolve 必须非空，文件不存在则拒绝",
        "resolution": "resolve 时必须与该歧义已登记的一个 interpretations 完全一致",
        "result_ids": "仅 validate 使用：当前已核验、同问且依赖该假设版本的 Result ID，须覆盖全部预定检查",
    }
    if command == "interpretation":
        _, required = fields_for(cls)
        required.add("requirement_ids" if kind == "AmbiguityEntry" else "linked_requirement_ids")
        allowed = FIELDS[kind] | {"legacy_refs"}
        notes += ["示例与 YAML 模板同源；默认没有绑定旧记录。仅实际存在旧 Stage 记录时填写 legacy_refs。",
                  "旧记录原写 resolved/accepted 也不会直接升级；迁入保持候选并显式 review，不能降低原严重度或删去已有解释。"]
    else:
        allowed, required = fields_for(Runtime.review_interpretation, {"revision", "object_id", "actor"})
        example = ({"action": "resolve", "rationale": "根据实际题面补充说明确定区间终点的处理方式",
                    "resolution": example["interpretations"][0], "evidence_files": ["sources/clarification.md"]}
                   if kind == "AmbiguityEntry" else
                   {"action": "accept", "rationale": "将常系数近似作为待验证基线，后续按已登记检查评估误差", "evidence_files": []})
        notes += ["命令另需 --id 当前对象版本 ID；actor 是记录来源，不是身份认证或用户批准证明。",
                  "示例来源文件必须由真实材料提供，不能为使 resolve 通过而编造说明；accept 仅记录采用，不赋予数学 verified。",
                  "validate 还需 result_ids 实际核验结果；不能把不存在的 Result、AI 答复或 '用户已确认' 文本当作验证证据。"]
    return {"command": command, "kind": kind, "required_fields": sorted(required), "allowed_fields": sorted(allowed),
            "fields": {key: descriptions[key] for key in sorted(allowed)}, "example": example,
            "template": "templates/copilot/" + filename if command == "interpretation" else None, "notes": notes}
