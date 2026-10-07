# 宿主与赛事适配

能力探针与赛事包接口只返回数据，不直接写 `decision_log.json`，由 Runtime 在同一 Store 事务中登记返回结果。RC4 的可选页面意见入口也复用这个 Store；它不建立第二份项目权威。

## Host Adapter

`copilot_host.probe(workspace)` 创建临时目录，实际写入、读回文件，并用当前 Python 启动一个独立短进程完成另一次写入/读回断言。临时文件随后清理。返回的每项能力有 `available / unavailable / unknown` 及实际执行证据；结果只适用于当前进程身份、路径和时间。

能力 ID 为 `read_files`、`write_files`、`execute_python`、`matlab`、`word`、`network`、`parallel_agents`。后四项没有执行探针，始终保留 unknown；检测到安装目录、CLI 名字或宿主环境变量也不能将它们变为 available。Python 子进程不等于并行 Agent。

`require(report_or_capabilities, required_names)` 返回阻断说明数组。所需能力缺失、unknown、unavailable，或虽声称 available 但没有成功执行证据，均阻断该操作。它不检查账号、付费权限或外部服务；不应把本地读写通过解释为其他宿主工具可用。

### RC4：页面与本机 AI 的可选连接

`copilot_interaction.Interaction` 负责登记意见、排队和保存回执；服务器启动时才可选择 `CodexExecutor`。浏览器不能上传任意执行命令，也不能指定另一工作区或替换执行器。意见与回执保存在原权威文件的 `copilot.feedback`，仍经过 Store 的版本检查、原子提交和历史记录。

Dashboard 默认只读。`dashboard --interactive` 允许保存/撤回意见，未启用执行器时不会启动 AI；同时传入 `--assistant-codex --assistant-timeout 180` 才启用可选的本机 Codex CLI 分析入口。执行器为每次明确的分析请求启动新的有界只读分析，不唤醒或接管现有桌面聊天，也不冒称已向用户原会话发消息。具体用法见 [本地页面交互](LOCAL_INTERACTION.md)。

发现 CLI 只证明找到了命令，不证明登录、额度、宿主权限或执行成功。页面收到请求、后台开始执行、获得有效完成回执必须分别显示；AI 回复不自动成为模型采用记录、真实 Run、数学核验或 submission_ready。依据版本或绑定文件变化后，旧回复只能作为历史材料，不能沿用为当前分析结果。Context 中的共同事实和反馈可用性也必须以对应权威版本为依据。

保存意见、撤回和读取/轮询进度不调用模型；明确点击“请 AI 分析”才可能产生一次执行及对应账户用量。服务中断后保留请求，不自动重放历史未完成任务；重新提交分析是新的执行。默认核心与页面仍使用标准库，使用本机执行器需要调用者另有可用 Codex CLI 环境。

真实接入必须按当前宿主逐一验收：本轮初始试跑遇到运行数据目录权限和启动失败，最终结果及修复后重试记录以候选版随附验收证据为准。合成执行器和子进程测试只能验证相应软件行为，不能替代真实 AI 回复。本入口关闭外部连接器、插件、浏览器及执行工具，仅分析附带的 Skill 和权威 Context；信息不足时交回用户原聊天继续。Windows 通过进程 Job 管理本次后代进程，POSIX 使用独立进程组；不支持安全进程管理时拒绝启动。此能力不等于跨宿主统一适配、云端调度或 GitHub 实时协作。

## Competition Pack

`copilot_packs.load_pack(name_or_path)` 从 `competitions/*/pack.json` 发现赛事名称及别名，也接受自定义包文件/目录。`mcm-icm`、`icm` 映射 MCM，`custom` 映射未核验的 generic 起点；添加新赛事无需修改 Core 的赛事枚举。原三赛事的指南、模板、Critic 权重和经验资料继续保留。

包字段包括 `id`、`version`、`rules_year`、`rules_status`、`official_sources`、`rules`、`required_checks`、`resources`。每条规则保存 `value`、`origin`、`source_ids`；非官方默认还需 `note`。来源分为 `official_rule`、`maintainer_default`、`team_default`、`empirical_observation`。例如 CUMCM 官方上限写 20 MB，工具选择十进制 20,000,000 bytes，字节换算明确标为维护默认。Core 不写死某赛事的页数或文件大小。

`validate_pack(pack)` 返回结构与来源错误数组。包内资源必须是包目录内部文件，不能用 `..`、绝对路径或外跳符号链接。

## 规则锁

```python
pack = load_pack("cumcm")
lock = build_rules_lock(
    pack, problem_year=2018, rules_year=2026,
    evaluation_mode="historical_benchmark",
    source_snapshots=[
        {"url": "与包中官方来源完全一致的URL", "path": "rules/source.html",
         "sha256": "实际文件的64位SHA-256", "verified_at": "2026-10-05"},
        # 每个 required_for_lock 官方来源均需一条实际快照。
    ], reviewer="member_1", workspace=project_root,
)
errors = verify_rules_lock(project_root, lock)
```

builder 缺信息或检查失败时抛 `ValueError`；读取失败可能抛 `OSError`。成功返回复用领域对象 `seal_record` 的记录，包含 `record_hash`、`semantic_hash`、包语义哈希、包文件字节哈希、资源文件哈希和每份官方来源快照哈希。快照必须非空，路径限于项目目录，文件当前哈希必须与输入一致；遗漏官方来源、伪造哈希或 `verified=true` 不能代替这些检查。

项目模式沿用已有工作流：`formal_contest` 要求题目与规则同年；`historical_benchmark`、`open_research` 可以显式跨年。规则年份始终必须匹配包的适用基线和来源年份。generic/custom 默认无年份与来源，无法生成有效规则锁。

`verify_rules_lock(root, lock)` 总是返回错误数组，重新读取当前包、资源和快照，并核对封印、年份、来源和路径。改变文件或重新封印一个伪 pack hash 均不能通过。自定义包必须先保存到项目内，再加载并锁定；仅修改内存中的规则字典不会成为已采用规则。

规则锁证明本地来源文件、声明出处、适用年份、维护版本和审核记录相互一致。它不能自动证明网页快照内容未经来源方修改、人工解读必然正确，或比赛系统已经收到提交；这些仍须对应检查与回执。单次 Host 网络工具访问成功，也不会被登记为此本地 Adapter 的联网能力。

## 本轮规则来源

CUMCM 包采用主集成于 2026-10-05 核对的 [2026 AI 规定](https://www.mcm.edu.cn/html_cn/node/fef94648f2836ab6cc81586f4c38512b.html)，声明位置在参考文献前。MCM/ICM 的 [COMAP 指令](https://www.contest.comap.com/undergraduate/contests/mcm/instructions.php)于 2026-10-05 实际重开核对，当前为 2027 届；25页限制、AI报告附在解答之后且不计该限制、单份英文 PDF 等配置来自该页。电工杯保留上游 2026-07-22 核对记录，本轮未重新访问其官网。

这些维护核对没有为任一真实项目自动生成规则锁。测试中的快照都显式标记为合成测试材料，不作为官方规则证据。
