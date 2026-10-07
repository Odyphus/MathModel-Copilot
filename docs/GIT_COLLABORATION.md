# 可选 Git 协作

v0.2.0 RC 使用 Git 搬运代码与文稿，仍由 `state/decision_log.json` 管理项目权威。Git commit 与 Copilot revision 含义不同；同一 commit 下的未提交文件也可能已经变化。所有运行继续采用原有实际快照和哈希，不能用 commit 代替运行字节。

默认 Local 模式不需要 Git、GitHub 账号或网络。手动文件清单和原有 Task Context 可以继续使用。本模块不创建、切换、拉取、推送或合并仓库，也不运行从 PR 或分支取来的程序。队伍工作区不会因产品准备开源而自动公开。

## 降低三人协作的维护成本

建议只在形成模型决定、完成一轮运行/验收或交接任务时整理一次可审查材料，不为每次聊天、每次页面刷新生成 Git 提交或 AI 总结。这是团队使用方案，尚不是已实现的 GitHub 在线同步服务。

每次交接优先给出简短的 Markdown 说明：这次改变了什么、依据是什么、影响哪些任务、下一位需要做什么；配合现有提案 JSON、实际代码/参数文件、检查日志清单与必要的 Task Context。确实使用 YAML 的配置可以一同传递，但不要求维护一份 YAML、一份 JSON 再加一份 Markdown 来重复记录同一状态。

- 小文件承载决定、提案、变化摘要和输出清单；大数据、完整运行目录、图片与论文只按实际交接需要传递，避免每次复制所有材料。
- 保留完整、可核对的原始 Context 封印；另给人读的简短摘要，不能手动删改 Context 字段后把它冒充新的权威事实。
- 队员收到文件只算接收。接纳对象仍走集成端版本检查；代码需要真实运行与验证，论文需要其来源及交付检查。Git 合并不代表采用、核验或 Ready。
- 页面意见和 AI 回复写入本地 Store。不要将 `state/**` 或 `.copilot/**` 作为 YAML/JSON 协同文档交给 Git 合并；如需让队友看一条意见，导出可审查的交接材料，再由队友按实际动作记录接收/采用/核验。

本地页面可以用 [可选交互入口](LOCAL_INTERACTION.md) 记录意见。保存和轮询不消耗模型调用；让 AI 分析时按相关任务一次性提交明确问题，减少为同步本身反复调用模型。另一位队员的网页不会因此自动收到云端反馈，仍需实际传输材料和在接收端核对当前版本。是否建设远程通知、自动拉取等能力，应在真实接力记录显示其收益后再决定。

## 命令入口

从产品源码目录执行，下列 `PROJECT` 是已有 Copilot 项目。独立入口可直接使用，不需要前端依赖：

```text
python scripts/copilot_git.py --workspace PROJECT status
python scripts/copilot_git.py --workspace PROJECT status --compare origin/integration
python scripts/copilot_git.py --workspace PROJECT diff --compare integration
python scripts/copilot_git.py --workspace PROJECT protect
python scripts/copilot_git.py --workspace PROJECT verify
python scripts/copilot_git.py --workspace PROJECT handoff --role coder --member member-2 --output handoff/coder-context.json
```

`status` 显示仓库根、分支、commit、未提交/未跟踪文件、冲突、detached HEAD 和无 commit 状态。缺少 Git 或不是仓库属于正常降级。指定的比较引用不存在或无共同祖先时返回 `unknown`，不猜测 main/master。`ahead/behind` 仅针对本地保存的引用；输出始终明确 `unknown_not_fetched`，不能解释为 GitHub 远端实时状态。

`diff` 对共同祖先、当前提交和实际工作区进行比较，列出新增/修改/删除文件的真实哈希，再通过已有对象文件绑定与依赖边查找影响。没有登记映射的文件保留为 `unknown_paths`，不是“无影响”。加 `--patch` 才会包含正文差异，每文件最多 2000 行，明确标注截断；二进制仅提供哈希。文件快照目前限项目内普通文件，每文件不超过 4 MiB；超限或不支持的路径会明确拒绝，不声称已检查。

## 在集成端显式启用保护

先保证权威文件和运行历史没有被 Git 跟踪，再执行 `protect`。它只追加当前仓库本地 `info/exclude`、`info/attributes` 规则及项目保护标记，不修改全局配置、已有源码、Git index 或业务状态。项目可以处于仓库子目录，支持中文和空格路径、常规 Git worktree 的 `.git` 文件。

保护范围为项目内 `state/**`、`.copilot/**`。发现这些路径已被跟踪时，安装会失败并保留原内容。先保存可信状态备份，再由维护者审查移出跟踪的具体方案；本工具不会代替维护者执行删除、`ours/theirs` 或重写历史。

`-merge` 属性是辅助防线，并不能独自阻止 fast-forward。启用后，普通 `Store.read` 也会检查 Git index；一旦保护路径被 Git 跟踪，哪怕带入的 JSON 哈希自洽、与旧文件字节一致，也会拒绝读成权威。不能通过重算哈希、改 verified 或补一个 merge commit 解锁。应恢复集成端可信副本，消除被跟踪的保护路径，再由原事务接纳明确提案。

标记位于当前 Git directory 的 `copilot-protect/<project-prefix SHA-256前24位>.json`，内容还会核对完整项目相对目录；标识碰撞会拒绝而非共享策略。短路径避免无必要地增加 Windows 路径长度，但不承诺宿主系统对任意深目录的支持。它仅表示本地读取策略，没有 revision、对象或业务状态副本，因此不是第二份权威。未启用的旧项目不执行 Git 检查，不改变原行为。启用后 Git 不可用则拒绝该保护模式下的读写；可恢复 Git 环境，不应为绕过检查随意删标记。该策略防止正常协作误把 Git 当作状态事务，不能认证一个有权限任意改写文件系统、删除策略标记的恶意操作者身份。

## 提案、接纳与 PR 草稿

每份提案只有一个源对象或生成产物登记动作，重用 `Runtime.register` 校验与 Store 原子事务。Run、Validation、Claim、PaperSection、审计与人工核验继续走专用入口，不能由通用提案创建 verified 结果。

例如已有项目内的 `proposal-action.json`：

```json
{
  "kind": "CodeManifest",
  "key": "code.Q1",
  "payload": {"question": "Q1"},
  "dependencies": ["model.Q1@1"],
  "files": ["solver.py"]
}
```

模型 ID 与文件必须替换为项目内真实当前值。操作顺序：

```text
python scripts/copilot_git.py --workspace PROJECT proposal --compare integration --reason "更新 Q1 求解实现" --action proposal-action.json --output handoff/code-proposal.json
python scripts/copilot_git.py --workspace PROJECT draft --proposal handoff/code-proposal.json --output handoff/pr-draft.md
python scripts/copilot_git.py --workspace INTEGRATOR apply --proposal handoff/code-proposal.json --expected-revision CURRENT_REVISION --actor integrator
python scripts/copilot_git.py --workspace INTEGRATOR verify
```

所有输出路径相对项目，使用新文件且拒绝覆盖。提案记录项目 ID、任务 ID（无任务时明确 null）、基础 revision/state hash、目标与依赖闭包的基础对象版本、来源 commit、dirty、实际 diff、影响、修改原因和明确文件快照清单。摘要哈希仅检查内容完整性，不是身份签名。

在集成端审查后，显式把 `file_snapshots` 清单内的文件和提案送入工作区。模块不下载或复制任意文件。其他 diff 仅列为待确认元数据，不自动成为传输清单；不得默认同步题面、原始数据、AI 日志、私人目录或缓存。接纳时在同一 Store 锁内再次检查项目身份、历史 revision、当前对象版本、实际文件字节，再调用原登记逻辑。期间 revision 改变会拒绝，不自动重试覆盖。同一模型或参数的两份同基线提案冲突；目标与依赖都无冲突的独立提案可以由集成端给出最新 `expected_revision` 依次接纳。

PR 草稿只写本地 Markdown，包含目的、基线、影响、测试及待办，明确“未发送至 GitHub”。适配器不执行测试，默认显示测试未执行。可通过 `--test-receipts` 指定 JSON 数组：`[{"command":["..."],"exit_code":0,"log":"logs/test.log"}]`；必须有实际日志文件并绑定哈希，仍标为调用者提供的外部记录，不能当成本模块重新执行或独立认证。不会按文件名、提交信息或“tests”目录推断通过。

## 接力与合并后的重新检查

`handoff` 包含原有 `build_context` 返回的完整 Context，保留同一 revision 的共同事实、任务对象与累计变化。队员使用原有 `ack` 命令登记接收、采用、核验；读取包装、生成草稿和应用对象提案本身不会伪造这些成员回执。执行 `ack` 时传入包装内 `context` 字段，不能把整个 Git 包装当作 Context。

磁盘文件偏离本 revision 观测时，导出 Context 会明确拒绝。集成端先运行原有显式 `reconcile --expected-revision ...`，记录失效传播，再导出新的 Context。不能重新封口一个过期摘要，使其看起来与当前权威一致。

`verify` 每次读取当前文件与对象依赖，返回旧 Run/Result/Claim/PaperSection 的失效情况、Requirement 完成度和 Ready。它只读，不复用合并前审计，不增加状态事件，不代表数学重算或人工审稿。代码合并或参数新版本使相关旧结果和正文待重检；重新登记、实际运行、独立验证和交付审计仍由原内核完成。分支叫 main 不会自动获得有效或 Ready 状态。

其中 `passed` 仅表示当前采用对象的绑定检查没有发现失效。正常被替换的历史对象仍在 `historical_stale_objects` 和完整 `status.stale_objects` 中保留，不能因为保存历史而永远判当前复验失败。换行符或文件尾换行单独改变时，文本差异明确提示字节差异，不把空的逐行 diff 当成内容未变。

## GitHub 与支持边界

RC 没有真实队伍 GitHub 仓库及读写授权目标，实际远程关联验收为 **blocked**；本地双 clone 证据不能替代它。没有自建 OAuth、GitHub App、自动建仓库、push、创建 PR、merge、审批、改保护或修改可见性。后续如用户授权特定仓库的只读访问，需单独记录授权范围、真实操作和结果。读取授权不能扩展为写入或公开发布授权。

所有 Git 调用采用固定 argv、无 shell、超时及输出上限；关闭可执行的外部 diff/textconv、fsmonitor 和命名 clean/process filters，不运行 hooks，不回显 remote URL 或原始 Git 错误输出。`status` 不递归进入子模块，避免子模块另有的 filter 配置被执行；`uninspected_submodules` 和草稿会明确列出未检查范围。含子模块时，外层文件没有变化不代表子模块干净或已审查。本地测试使用新建临时仓库；测试中为构造两副本比较会明确运行本地文件传输与 merge，这不表示产品适配器会自动执行这些动作。

正式回归入口：

```text
python -m unittest discover -s tests -p test_git_v020.py -v
```

平台实跑结果以本候选交付验收矩阵为准。CI 配置存在、Windows 实跑、Linux 实跑、真实 GitHub 关联分开记账，不能合并为“跨平台协作全部通过”。

设计依据采用 Git 官方文档：[gitattributes](https://git-scm.com/docs/gitattributes)、[status porcelain](https://git-scm.com/docs/git-status)、[rev-parse](https://git-scm.com/docs/git-rev-parse)、[diff](https://git-scm.com/docs/git-diff)。读取日期：2026-10-05；实际测试 Git 版本记录在专项证据中。
