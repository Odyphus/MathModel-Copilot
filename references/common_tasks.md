# 常用流程：从当前记录继续工作

入口为 `python <skill>/scripts/copilot.py --workspace <project> <命令>`。下方只展示命令部分；占位符要从当前项目读取，不能照抄。

## 找到功能与输入要求

`data`、`forecast`、`git`、`experience`、`usage-feedback` 不带子命令或带 `--help`，都会展示真实入口。继续用 `forecast run --help` 等查询下一层参数。`payload-help <命令>` 返回 JSON 字段说明与示例；`--help` 返回人可读文本。

## 准备运行或参数修改后的重算

1. 用 `status` 核对当前版本、各问要求与失效记录。第一次建模仍需登记题意、模型、参数、数据、代码与运行前检查计划。
2. 代码已保存时，先看 `payload-help register --kind CodeManifest`。注册时用 `--files` 绑定真实文件、`--depends` 绑定当前模型；系统计算文件哈希和依赖字段，不手填占位或 `null`。验证计划示例见 `payload-help register --kind ValidationPlan`。
3. 执行 `run-input --question Q1`。这是只读准备步骤；`ready_to_run` 仅表示本次观察能组装运行输入，不表示运行或核验已经通过。缺少/失效依赖时看 `blockers`；遇到多个候选时，用返回的真实 ID 明确选择，不按旧数字或文件日期猜。
4. 将响应的 `result.payload` **单独**保存为项目内的新 JSON 文件，用返回的 revision 执行 `run --payload 新输入.json --expected-revision N`。不要把整个响应保存成 run 输入。正式执行仍检查版本、文件、输出与依赖。
5. 用 `validate --run-id <本次真实 Run ID>` 执行预定检查；字段见 `payload-help validate`。通过后再登记结论和要求覆盖。版本冲突时先读变化并重新准备，不能只改 revision 重发旧输入。

改参数时在原 ParameterSet 的稳定 key 上登记新版本，再从步骤 3 继续；改模型定义或代码时先处理对应的新版本及受影响依赖。旧结果、结论和论文继续留存，不能当成当前有效内容。

## 把实际结果写进论文

`payload-help claim` 给出外层 `claim/results` 与结论所需来源的示例。数值绑定当前核验结果；所需表格或图件应由正式运行实际输出。若缺输出，先补声明和求解器，重新运行并检查，不能事后补一张表冒充原运行产物。

`payload-help section` 解释章节参数和段落标记。完整 Claim 文字与其版本标记放在同一段；新增数字需新增依据。数字列表用顿号、分号或表格，十进制数值不要使用千位分隔符。更复杂的输入说明、公式、表格、图件引用见 [章节协议](../docs/SECTION_V012.md)，原生 Word 导出见 [章节导出](paper_export.md)。

## 看懂重检和缺少的指标说明

工作台详情页按当前依赖与实际文件观察展示能定位的变化，链接旧依据、新依据与后续使用者；没有定位到的原因保留原始诊断，不推测根因。长结论在列表里使用简短标签，完整内容仍在详情中。

“数字来源与检查依据”中的“指标说明不完整，如何补充？”可复制请求给当前 AI 对话。先核对含义、单位和范围，再修订模型输出声明并处理影响；复制不会唤醒会话或直接改模型。

## 留下能用于排查的使用反馈

查 `payload-help usage-feedback`。简短反馈仍可只填原有字段；需要上下文时加可选 `reproduction`。分别填目标、步骤、预期、实际、尝试的处理和当前结果，每段注明 `user_report` 或 `agent_summary`。来源标签是说明，不是身份认证或已复现证明。未知就省略，并列出缺口，不能编造对话。

`usage-feedback preview --id <反馈ID>` 即使没有配置 GitHub，也会返回完整脱敏本地正文；`export` 可保存 Markdown。敏感语义仍需人工检查；上传按已有审阅和授权流程执行。自由文本上下文不进入有限自动反馈，也不自动读取完整会话。个人记录仍保存在不参与 Git 的个人目录。
