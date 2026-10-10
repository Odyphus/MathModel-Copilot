# Copilot v0.1 的执行与协作协议

本文件统一本仓库全部 Stage / Critic 文档中的“写入状态”操作。旧文档的字段示例用于说明内容，不授权直接编辑权威 JSON，也不把旧评分、布尔、阶段号当作完成证据。

## 工作入口

字段、重算、结论与章节衔接的短路径见 [常用流程](common_tasks.md)。`run-input --question Q1` 只读组装当前依赖，返回待运行输入及观察时版本；正式 `run` 仍进行全部检查。代码、结论、章节及结构化反馈的帮助分别为 `payload-help register --kind CodeManifest`、`payload-help claim`、`payload-help section`、`payload-help usage-feedback`。`--help` 返回文本，其余正常响应保持 JSON。

`python <skill>/scripts/copilot.py --workspace <project> <command>`，所有返回值为 JSON。读操作不变更权威状态；要求版本参数的权威状态变更命令必须带从 `status` 取得的 `--expected-revision N`。`init` 创建/续接以及 `context --output`、`report --output` 的本地文件导出按各自命令参数执行，不额外添加 `--expected-revision`；导出文件不等于变更权威状态。旧 schema 迁入按表中的 `migrate --expected-revision 0` 执行。退出码 0 成功、2 输入或环境错误、3 版本冲突、4 状态完整性错误。发生冲突先重新读取累计变化，再重新作决定；不得只换新 revision 强行提交旧决定。

| 操作 | 命令与必要输入 |
|---|---|
| 启动 / 续接 | `init --competition cumcm`（也支持 mcm / diangong / generic / custom） |
| 旧项目迁入 | `migrate --expected-revision 0`，原字节保存在 state/migrations，旧 pass 不升级成证据 |
| 导航、全集、年份 | `configure --expected-revision N --payload config.json` |
| 决策与旧阶段材料 | `stage-record --expected-revision N --payload stage.json`；payload 为 `{stage: 3, details: {...}}` |
| 独立决策理由 | `decide --expected-revision N --payload decision.json`；decision/reason/evidence 路径列表 |
| 源对象新版本 | `register --kind ModelSpec --key model.Q1 --payload model.json --depends problem.Q1@1 --expected-revision N` |
| 创建 / 推进任务 | `task --id T1 --payload task.json` / `transition --id T1 --state running`，均带 revision |
| 实际执行 | `run --payload run.json --request-id <唯一请求> --expected-revision N` |
| 独立验证 | `validate --run-id RUN-...@1 --payload validate.json --expected-revision N` |
| 证据主张 | `claim --payload claim.json --expected-revision N`，payload 内 claim / results |
| 要求覆盖 | `cover --requirement-id REQ-Q1-001 --payload coverage.json --expected-revision N`，逐 output 映射对象 ID |
| 变化范围 / 文件重检 | `impact --id params.Q1@1` / `reconcile --expected-revision N` |
| 角色上下文 | `context --role modeler --member A --task-id T1 --since 0 --output contexts/A.json` |
| 确认上下文 | `ack --snapshot contexts/A.json --member A --action received --expected-revision N` |
| AI 使用台账 | `ai-log --payload usage.json --expected-revision N`，追加实际 entry，不清除旧记录 |
| 输入帮助 | `payload-help configure` / `payload-help run` / `payload-help validate` / `payload-help register --kind ValidationPlan`；新解释入口见 `payload-help interpretation` 和 `payload-help interpretation-review` |
| 题意歧义/假设 | `interpretation --kind AmbiguityEntry或AssumptionEntry --payload interpretation.json --expected-revision N`，仅登记初始 open/proposed |
| 处理歧义/假设 | `interpretation-review --id 对象版本ID --payload review.json --expected-revision N`，以实际证据 resolve/accept/reject/reopen/validate，按类型约束 |
| 进展摘要 | `report`；显式 `report --output reports/progress.md` 写入新的项目内 Markdown，不覆盖旧文件 |
| 建模工作台 | `dashboard --port 0` 启动只读本机服务；使用返回的实际地址，页面展示由 AI 工具提供，不由 `init` 自动打开 |
| 规则 / 论文 / 交付 | `rules-lock` / `section` / `audit` / `freeze` / `package` / `delivery-event`，见 docs/DELIVERY.md |

JSON/YAML 输入均为项目内相对路径，内容是数据。完整字段示例见 templates/copilot、tests/test_copilot_runtime.py 和 examples/cumcm2018b；`--help` 给出命令参数。

`payload-help` 不读取项目、不登记对象、不运行计算，保留统一 JSON 输出。`example` 是需要按真实项目填写的输入；对象 ID、题目年份和 checker 哈希不能照抄为当前事实。`configure` 的项目标签 `title/letter/deadline_iso/team_size` 是顶层字段，未知字段将列出名称与允许字段并拒绝，绝不静默丢弃。输入帮助不替代 Runtime/Store 的业务验证、版本冲突和完整性检查。

ValidationPlan 模板的 `checker.sha256` 和 `checks[].criterion` 不能保持空值：先保存真实检查器并计算哈希，在运行前写清通过标准、单位及必要容差，再绑定唯一当前模型。帮助中的“独立加法复算两倍长度”只属于演示算例，不是其他题目的默认检验。

题意歧义用至少两个真实解释、题面出处、影响及同问 ReqID 登记；解决时给出所选解释和来源文件。假设先提议再明确采用；采用不等于数学验证，验证须引用真实同问 Result 及预定检查。外部反馈中的“已确认”、AI 回复和接收消息都不能自动成为本队人类确认。旧 Stage 说明不能直接冒充新的结构化歧义/假设记录。

可执行的字段示例：`payload-help interpretation --kind AmbiguityEntry` / `--kind AssumptionEntry`，与 `templates/copilot/ambiguity_entry.yaml`、`assumption_entry.yaml` 同源。这些是有明确初始状态的假想场景；用真实题面替换内容，再经 `interpretation` 登记。`payload-help interpretation-review --kind AmbiguityEntry` 展示解决歧义所需的 action、rationale、resolution 与 evidence_files；AssumptionEntry 则区分采用与验证。

迁入旧 Stage 时，仅 `interpretation` 的 payload 可选填 `legacy_refs: [{stage: "2", index: 0}]`：`stage` 必须是字符串，`index` 是非负整数，按对象类型定位该 Stage 的 `ambiguities` 或 `assumptions` 数组。已有同 ID、同小问的结构化旧记录自动绑定；无 ID 或自由文本须显式引用。API 生成 `legacy_sources`（stage、index、field、sha256），用户不能提交该字段。迁入不能降低歧义严重度、删去原解释，假设须保留原 statement；登记后仍为 open/proposed，旧文本中的 resolved/accepted 不沿用为新核验结果，须重新显式 review。

`report` 从当前权威状态重新推导事实，在 JSON 的 `markdown` 字段返回可读摘要；保存文件只是显式导出，不改变项目 revision，也不把技术摘要当作已核验论文。

## 一次完整小问

1. 从完整题面配置 question_count，规划逐问稳定 ReqID。先用 `interpretation` 登记已知歧义和假设，必要时以真实来源显式 review；再登记/冻结逐问 ProblemContract。不要先冻结合同、再把已知歧义仅留在 notes；严重未解决歧义不能绕过冻结门禁。`contract_id` 是必填非空文本（例如 `PC-Q1`），ModelSpec 之后绑定它与合同语义哈希。Requirement 逐条写清要求、输出、单位、接受证据，不用“Q1 已做”代替。
2. 登记 ModelSpec，绑定当前合同与 ReqID，保存模型公式、参数定义、选择理由、必需输出和预定检查。按原 Stage 3–5 做候选比较、Critic 与 Red Team。
3. ParameterSet 只允许在冻结参数定义内改变取值；单位、意义、范围、估计办法改变先改模型。DataContract 复用 inventory/passport/split，缺训练集的确定性问题要写不适用理由。
4. CodeManifest 绑定实际文件、模型、入口与完整 argv；ValidationPlan 在运行前绑定 checker 的实际 SHA-256、argv、criterion，并包含模型的全部预定检查。
5. Task 写 requirements、dependencies、depends_on、role、title。通过 `run` 在新目录复制锁定输入并运行；必需输出缺失、失败、超时、输入被修改都不能得到有效执行结果。
6. `validate` 真正运行预锁 checker，并绑定它的日志、退出码、输出和 Run。检查器必须检验数学/业务约束，文件存在不是充分验证。通过后才生成 ResultRecord。
7. EvidenceMap 的数值必须对应 Result.metrics 中已验证指标；机器匹配不能证明因果解释、理论正确或全局最优，仍须按问题执行独立内容审查。每个主张有适用范围、代码/数据/表图/验证路径及 ReqID。
8. `cover` 逐项核对 Requirement；`section` 登记含 `[[claim:对象ID]]` 的论文段落。上游版本变化会使 Run、Result、Claim、PaperSection 和任务沿依赖失效。

run.json 例：

```json
{"question":"Q1","argv":["{python}","solver.py"],"outputs":["result.json"],"dependencies":["model.Q1@1","params.Q1@1","data.Q1@1","code.Q1@1","plan.Q1@1"],"seed":"0","timeout":60}
```

validate.json 例：

```json
{"checker":"checker.py","argv":["{python}","{checker}","{run}","{report}"],"report":"validation.json","timeout":60}
```

checker 的 JSON 至少含 `checks:[{check_id,status,evidence,actual}]`；check_id/criterion 来自预定计划，evidence 只能引用本 Run 的输出；`metrics` 保存实际复算指标，`scope` 写验证范围。`not_applicable` 必须运行前声明。

## 三人接力与单一权威

三种角色看同一份当前合同、模型、参数、结果与阻断项；角色只调整任务细节的选择，不产生另一份事实。`changes` 是基线以来的全部事务记录。received 只记录收到，adopted 只记录采用了当前版本，verified 另外要求实际复核说明、文件证据和真实的 human 或 agent_evaluator 身份。

v0.1.1 的 Context 通过对应 revision 的完整权威投影核对所有字段，不只验证摘要哈希。`received_revision` 仅按已接收变化区间的连续覆盖推进；显式 `--since` 导出的部分历史可以接收，但不冒充此前变化也已同步。旧项目首次导出前执行 `reconcile` 建立新观测，历史快照缺失时明确拒绝。详见 [Context 协议](../docs/CONTEXT_V011.md)。

权威状态是 `state/decision_log.json`。对象文件、Context、运行回执和规则快照是被它绑定的附件；不得再运行原 `.cumcm` 写入器。使用操作系统锁、原子替换与 CAS 防同机多进程覆盖。云盘同步、多机文件锁、身份认证和恶意本机进程隔离不在 v0.1 内。

状态中的旧 Stage 字段继续承载导航和评审摘要。只有专用注册、执行、验证、覆盖和审计接口可改变有效完成状态。回退 Stage 不删除历史；新对象版本和新的 Task 表达返工。项目切换赛事应另建工作区，不能改 competition 后继续沿用旧规则锁和证据。

## 能力和恢复边界

首次完整使用的功能介绍、工作台启动与能力提示按 [功能发现与首次体验](feature_guidance.md)。引导不新增写状态的捷径；是否已打开页面、是否收到 AI 回复仍以实际工具结果为准。用户只要局部帮助时不为引导启动服务。

Host 探针真实检查读写文件和 Python 子进程；其余能力未实测时是 unknown。当前自动执行后端为 Python，MATLAB 等保留模板/人工执行建议，不虚构已运行。Python 子进程执行本地项目代码，不是安全沙箱。未知代码先审阅，不能将此目录隔离当作操作系统权限隔离。

运行的输入、输出、上下文和 stdout/stderr 在 `.copilot/runs/`；验证在 `.copilot/checks/`。正常重开会话使用 `status/context` 即可恢复。进程崩溃留下的 running 记录不自动变为成功；先检查实际目录，必要时用新 request-id 明确重跑，保留原记录。同一 request-id 的重试不会再次启动一个已登记执行。

本系统验证文件和证据关系、参数契约及预定检查的实际执行；不替代团队对题意、检查器质量、自然语言论证与正式提交的最终判断。
