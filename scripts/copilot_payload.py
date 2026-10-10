"""Read-only payload guidance; business validation remains in Runtime/Store."""
from __future__ import annotations

import copy
import inspect

# Runtime.configure deliberately collects these project labels in **metadata.
# This allowlist describes that public interface, never arbitrary extra fields.
CONFIGURE_METADATA = {"title", "letter", "deadline_iso", "team_size"}
TARGETS = ("configure", "run", "validate", "stage-record", "decide", "register",
           "interpretation", "interpretation-review", "claim", "section", "usage-feedback")


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
    if command in {"claim", "section", "usage-feedback"}:
        return workflow_help(command)
    if command == "register" and kind != "ValidationPlan":
        return registration_help(kind)
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
    if command == "run":
        notes.append("已有契约时先运行 run-input --question Q1；它只读列出当前有效依赖并准备输入，有多个候选时要求明确选择。")
    if command == "configure":
        notes.append("不支持把 title 等字段包进 metadata，也不支持 years/status/ready 等别名；未知字段将被明确拒绝。")
    return {"command": command, "required_fields": sorted(required), "allowed_fields": sorted(allowed),
            "fields": {name: descriptions.get(name, "参见统一执行协议") for name in sorted(allowed)},
            "example": copy.deepcopy(examples[command]), "notes": notes}


def registration_help(kind):
    notes = ["字段帮助不读取或修改项目状态；示例不是运行结果。",
             "注册仍需当前 --expected-revision；文件和依赖必须真实存在且有效。"]
    if kind is None:
        return {"command": "register", "kinds": ["CodeManifest", "ValidationPlan"],
                "next_commands": ["payload-help register --kind CodeManifest", "payload-help register --kind ValidationPlan"],
                "other_contracts": "templates/copilot/；此处列出有专门字段帮助的类型，不是可注册类型全集", "notes": notes}
    if kind != "CodeManifest":
        raise ValueError("该类型暂无专门字段帮助；支持 --kind CodeManifest / ValidationPlan，其他源契约见 templates/copilot")
    return {"command": "register", "kind": kind, "required_fields": [],
            "example": {"entrypoint": "solver.py", "argv": ["{python}", "solver.py"]},
            "fields": {"entrypoint": "--files 中实际存在的 Python 入口；唯一 Python 文件时可省略",
                       "argv": "执行参数数组，必须以 {python}、入口文件两个元素开头；默认由入口生成"},
            "command_arguments": {"--kind": "CodeManifest", "--key": "code.Q1", "--files": ["solver.py"],
                                  "--depends": ["<当前同问 ModelSpec ID>"], "--payload": "<保存的 JSON 相对路径>"},
            "generated_fields": ["question", "spec_id", "modelspec_semantic_hash", "files 的 SHA-256", "revision_id"],
            "notes": notes + ["这些字段由实际依赖和文件计算；无需抄写哈希或手填 null。生成代码、登记代码与实际运行是三个步骤。",
                              "需要 UTF-8 时在运行环境设置 PYTHONUTF8=1；不要把 -X 等解释器选项插在入口前。"]}


def workflow_help(command):
    notes = ["只读说明，不修改项目，也不证明示例已运行。示例中的 ID、数值和路径须替换为实际记录。"]
    if command == "usage-feedback":
        from copilot_usage_feedback import reproduction_example
        return {"command": command, "input_mode": "draft/edit --input JSON",
                "required_fields": ["component", "event"],
                "allowed_fields": ["title", "description", "component", "event", "reproduction"],
                "example": {"title": "示例：不清楚如何继续运行", "description": "以下是假想反馈，请替换为实际经历。",
                            "component": "workflow", "event": "hard_to_understand", "reproduction": reproduction_example()},
                "notes": notes + ["reproduction 可省略；缺失上下文会明示，不要求用户补齐才能反馈。",
                                  "source 是信息来源自述，不是已独立复核标志；不会自动读取整个聊天记录。",
                                  "先 export 本地文档或 preview。外发仍需现有授权流程；自由文本不会进入有限自动反馈。"]}
    if command == "section":
        return {"command": command, "input_mode": "cli_arguments", "required_fields": ["--key", "--path", "--claims", "--expected-revision"],
                "example": {"--key": "paper.results", "--path": "paper/results.md", "--claims": ["<当前 Claim 对象 ID>"],
                            "--expected-revision": "<status 中当前 revision>"},
                "paragraph_template": "<逐字保留所引用 Claim 的完整结论> [[claim:<当前 Claim 对象 ID>]]",
                "notes": notes + ["section 使用命令参数，不使用 --payload；--claims 需要版本化对象 ID。",
                                  "完整结论与标记放在同一段；新数字需补相应依据，不能删掉数字或改写结论来绕过检查。",
                                  "数据、模型等输入说明用 source-bindings，公式图表用 structure；详见 docs/SECTION_V012.md。"]}
    return {"command": command, "required_fields": ["claim", "results"],
            "example": {"claim": {"claim_id": "length.result", "claim": "计算长度为 10 m。", "claim_type": "numerical",
                                  "paper_anchor": "results", "formal_run_id": "<真实 Run 对象 ID>",
                                  "requirement_ids": ["REQ-Q1-001"], "data_sources": ["<该 Run 的 data_hash>"],
                                  "code_locations": ["solver.py"], "tables": ["<该 Run.outputs 中真实文件路径>"],
                                  "validation_evidence": ["Q1.run.formal"], "limitations": ["仅限本次假想长度算例"]},
                        "results": ["<当前已核验的 Result 对象 ID>"]},
            "fields": {"claim": "EvidenceMapEntry 内容；把结论文字、来源、正式运行和限制一同登记",
                       "results": "绑定当前已核验结果；不能使用代码登记 ID 或尚未核验的 Run ID"},
            "notes": notes + ["数值必须与已核验 Result.metrics 绑定；需要舍入时使用已有 display_contracts，不改写原值。",
                              "Q1.run.formal 是对应小问的正式运行验证引用，必须绑定实际已核验的 Run/Result；不是任意 check_id 或说明文字。其他验证文件须符合证据协议。",
                              "数值结论至少绑定一个真实表格或图件；文件须是所绑定正式运行的输出，不能事后制造表格冒充原输出。",
                              "若所需表格尚未输出，应修改模型输出声明与求解器，重跑并核验，再登记新 Claim。",
                              "当前解析器禁止数字间逗号；列表使用顿号、分号或表格，十进制数字不使用千位分隔符。"]}


def recovery_hint(command, message):
    """Add narrow, actionable guidance without changing rejection or authority."""
    if command in {"register", "run"} and ("argv" in message or "入口" in message):
        return {"action": "核对入口与已登记执行参数；保持 {python}、入口文件的顺序。",
                "help": "payload-help register --kind CodeManifest"}
    if command == "claim":
        if "千位分隔符" in message:
            return {"action": "保留数值，去除数值内部千位分隔符；多个独立数值改用顿号、分号或表格分隔。", "help": "payload-help claim"}
        if "table" in message or "表格" in message or "图件" in message:
            return {"action": "绑定实际正式运行输出；若缺表格/图件，补充输出声明和求解器后重跑、核验，再登记结论。", "help": "payload-help claim"}
    if command == "section" and ("marker" in message or "referenced claim text" in message):
        return {"action": "在同一段保留被引用 Claim 的完整文字和版本标记；新数字先补证据。", "help": "payload-help section"}
    if "revision" in message.lower() or "版本冲突" in message:
        return {"action": "读取 status，确认期间发生的变更，再按新版本重新准备输入；不要直接改版本号重试旧内容。", "help": "run-input --help"}
    return None


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
