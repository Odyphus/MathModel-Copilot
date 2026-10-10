# Changelog

## 0.3.0-preview.3.dev4（公开 Preview 增量，2026-10-10）

- 公开同步 dev1 至 dev4 的数据契约、方法基线、滚动预测、方案比较、原生 Word 导出和使用引导。
- 增加运行输入整理和字段帮助，改善工作台长文字及来源变更说明。
- 使用反馈补充有来源的复现信息、本地预览和导出，继续保留脱敏与授权边界。
- README 原文和宣传素材保持不变；固定 latest 下载入口更新，旧版本安装包保留。
- 实测范围和未验证项见 docs/ACCEPTANCE_PREVIEW_DEV4.md；开发期间“未发布”条目为当时历史记录。

## 0.3.0-preview.3.dev3（本地整体体验候选）

- 安装验收区分可选 PyYAML 缺失与实际资源损坏，保留未验证项并继续检查拒绝覆盖。
- Skill 入口从发行元数据读取版本，反馈仓库可见性以实际预检为准。
- 教学目录补充表格解释、滚动预测、方案比较与原生 Word/PDF 导出的使用时机。
- Word 表格按内容分配列宽，保留长小数原文；无法在可读字号内容纳时明确拒绝导出。
- 扩大本机工作台连接等待队列，修复刷新时并行资源加载可能丢失教学脚本的问题。
- 完整试用与验证证据另见本批交付记录；未声称公开发布或跨宿主真人验收。

## v0.3.0-preview.3.dev2 — 未发布开发增量

- 增加按观测/发布时间构造的滚动预测、训练内预处理与同窗口简单基线；记录每个预测实例并拒绝缺槽、未来特征和来源漂移。
- 增加有前提的 LP 一致性桥梁，比较目标与可行性，明确不适用条件和未证明最优状态。
- 从当前核验章节装配原生 DOCX，保存后核对文字、表格、公式及图片；可选本机 PDF 转换，成果保持参数/结果变更后的失效关系。
- 工作台展示声明条件一致的指标、策略、后端与来源，以及论文导出/读回状态；不自动排名或宣称论文已定稿。
- 保持 schema 4.0 与现有 README/公众号文字；未公开发布、未覆盖已有安装。复杂公式、跨平台转换、真实反馈发送和完整新用户体验仍分别验收。

## v0.3.0-preview.3.dev1 — 未发布开发增量

- 数据入口明确 CSV/XLSX 列、单位、区间平均功率和时标，保留原位置、写后读回，并通过现有 DataContract 绑定原始与归一化文件。权威 schema 4.0 保持兼容。
- 现有优化 starter 增加 SciPy LP/MILP 与可行/最优状态区分；回归增加训练均值基线和可选训练内标准化，非必要后端按需加载。
- 增加原创合成数据→运行→独立检查→参数失效/重算示例及简明方法卡；Windows 公共 JSON 统一 UTF-8。
- 未公开发布、未覆盖现有安装；README 文案与视觉素材不变，外部流程验收不因本增量扩大。

## v0.3.0-preview.2 — 工作台修复与公开下载同步

- 修复内部编号隐藏误伤真实小数、整数和科学计数法的问题，同时继续隐藏明确标记的哈希与对象编号。
- 总览只合并语义和当前状态一致的跨问共同事项，保留各问对象详情；不同选择、来源或核验状态不合并。
- 待解决问题保留真实假设内容和每项阻塞理由，不用内部编号推测事实。
- 增加可选私有队伍仓库引导：GitHub 登录预检、创建空私有仓库、按用户名发送写入邀请和回读状态；不自动上传资料，不将邀请视为已接受。
- 同步已确认的 README、公开仓库信息及运行包安装路径；沿用单入口、拒绝覆盖及 schema 4.0。
- 重新打包、保留旧下载包并核对下载包与发布源码的逐文件一致性；实测和未验收范围见 docs/ACCEPTANCE_V032.md。

## v0.3.0-preview.1 — 教学、复盘续接与使用反馈

- 保留 0.2 Preview 内核、Store schema 4.0 和四个工作台入口，不迁移比赛状态。
- 功能目录与完整/单项教学共用一份数据；随时可进、可跳过、可退出，教学不执行演示或改变进度。
- 独立个人目录保存明确的设置、必要过程及有来源片段；本段收尾生成并回读本地 Markdown，重复收尾幂等。
- 再次进入重读权威与实际文件；按授权读取偏好及少量有条件经验，来源失效和撤回时排除。
- 新增使用反馈草稿、脱敏预览、精确授权、GitHub CLI 发送与回读；结果未知先核对，同一反馈不盲目重发。
- 有限自动分享只允许程序观察字段，不发送自由文本、题目、结果或原始交互；与本地记录授权分别管理。
- 独立反例检查修复标准 Authorization 凭据脱敏遗漏并扩大格式回归。
- 程序测试、实际浏览器、自然对话宿主、真人首次体验和真实远端送达分别列明，不用离线模拟代表外部验收。
- 本候选未公开发布，未覆盖原安装，来源许可和接收仓库等发布边界继续保留。

## v0.2.0-preview.2 — 工作台连续阅读

- 保留现有本地服务、四个主入口及原状态内核，新增独立纯展示模块；不要求前端构建。
- 新增本浏览器上次已读以来的变化摘要；新增、失效、撤销及同 revision 文件漂移均可提示。阅读标记不改变接收、采用、核验或完成状态。
- 从已有题意歧义和假设投影生成待判断事项，显示真实候选解释、影响与已登记依据；可复制讨论提纲，不替用户选择，不把复制当作已发给 AI。
- 可见页面定时读取本机状态，隐藏时暂停。相同内容刷新保留 DOM；更新时保持筛选、展开及阅读位置，并重建详情中的当前版本与后退关系。
- 读取失败撤下旧事实；修复加载中导航丢失、详情后退错改顺序及旧文件请求回填等竞态。
- 权威状态仍为 schema 4.0，无需迁移项目；展示版本 preview.2 对应 Python 分发 0.2.0rc6。保留公开发行与真实 AI 接入的未验收边界。

## v0.2.0-preview.1 — 公测候选准备

- 以RC4为基线接通歧义/假设登记、明确取舍、合同冻结和受影响结果失效，沿用原Store，兼容已有4.0状态。
- 修正验证计划模板与运行接口不一致，增加payload字段帮助、最小示例及未知字段说明。
- 默认先给全题理解与逐问候选对照，保留专业模型名称、数学结构、算法、验证与取舍；删除无条件逐阶段编号确认。
- Dashboard从明确模型输出声明读取名称和单位，缺失/冲突不猜测；复用原组件按需显示数值来源与检查条件。
- 新增只读事实简报，完成度和有效结果来自当前观察，外部自述、过期文件和旧聊天不授予核验。
- 独立负向审查补齐旧解释迁入降级、伪造假设验证、同键对象身份替换和新增解释绕过旧合同失效的边界；报告拒绝Windows路径别名写入状态目录，文件扫描不跟随目录链接。
- 运行代码身份与实际环境分开记录；未获得的Git提交、人工确认、AI调用或跨平台验收不作推断。
- 展示版本为preview.1，Python版本为0.2.0rc5，保持版本排序连续。实际测试和剩余公开分发条件见随包验收证据及docs/PREVIEW_READINESS.md。

## v0.2.0-rc.4 — 内测反馈修复与本地意见交互

- 运行包只保留一个 Skill 入口；开发源码单独交付。默认安装不生成旧名别名，已有安装拒绝覆盖。
- 文件同步失败提供可操作诊断并保留原状态，不静默跳过持久化保障。
- Windows 原子替换期间的短暂读取占用会有界重试；持续权限错误仍报错，不回退到旧快照，不跳过状态完整性检查。
- 建模方案保留通俗引导，同时明确专业模型、数学结构、求解算法、验证与采用状态；按论证价值推荐图表。
- 论文由人主导，默认材料与批注，按需生成局部候选稿；加入可追溯摘要案例模板和只读材料预检，未内置未知授权论文库。
- 复用原 Dashboard 加入可选意见/回执组件。默认只读；交互写入通过原 Store 事务，支持版本冲突、精确重试、取消和过期提示。
- 可选本地 Codex CLI 新分析入口，页面不能传任意命令；不接管现有桌面聊天。真实宿主成功闭环按独立验收记录判断。
- 补充启动失败、完成/取消竞态、上下文过期、任务错配、来源错配、异常数值及安装包边界回归。
- 仍为私下内测 RC，不自动云同步、不修改原安装、不公开发布；数学与论文人工审阅、跨平台及真实宿主接入分别列明验收范围。

## v0.2.0-rc.3 — 私下内测准备

- 新增简短中文使用说明和无需 pip 的首次体验路径，明确演示与真实赛题使用不同工作区；修正示例的错误命令参数。
- 题意合同在登记时即拒绝无效 `contract_id`，不再延迟到模型绑定时失败；拒绝事务保留原状态。
- 工作台正确读取 ParameterSet.entries，显示可读的参数含义、取值和单位；返回页面时重新观察当前权威状态。
- Skill 固化“专业建模术语 + 通俗解释”、从权威记录恢复上下文和集中反馈的交流方式。
- 分析/测试依赖补充 openpyxl；CI 安装验证读取实际生成的唯一候选ZIP，不再写死旧版文件名。
- 内置演示使用具体中文要求、模型名称、参数含义与任务标题，保留流体排队模型和有限策略枚举的准确名称。
- 历史附件缺失明确列项跳过并单独分类，不误报为代码失败，也不计为通过。
- 增加领域输入与页面续接回归。具体执行结果随本轮验收证据交付；未改变状态 schema、旧项目或已安装版本，未公开发布。

## v0.2.0-rc.2 — 本地工作台易读性更新

- 以各问进展和下一步组织首页；增加当前方案、需确认事项及变化影响，空栏目按需隐藏。
- 四个主导航采用中文；内部标识只保留在诊断导出中，计算记录使用可读名称。
- 明确本机范围；保留既有 Git 接力能力，不增加远程同步或状态写入。
- 保留要求、计算、检查、论文及提交状态的差别；已完成的材料审计不再被重复推荐。
- 新增界面语义负向测试，更新真实浏览器导航、错误和空状态验收；具体执行结果随交付记录。
- 权威状态 schema、领域检查器和文件读取边界不变。

## v0.2.0-rc.1 — local review candidate

Built from the supplied v0.1.3 baseline. This candidate adds a distinct `mathmodel-copilot` installation and discovery name, standard Python packaging with preserved runtime resources, grouped optional dependencies, a local read-only Dashboard, optional local Git collaboration, and a synthetic MCM demonstration. Original state/evidence/Context and DOCX source-checking safeguards remain the compatibility baseline.

Installation and release tools use create-only destinations, explicit legacy alias selection and a source allowlist. Official historical attachments and internal evidence are excluded from clean candidate archives. Maintainer/repository identity and several rights remain unconfirmed, so this is not a cleared or published open-source release.

The actual acceptance report delivered alongside the candidate is authoritative for executed platforms, cases and checks. This changelog describes the implementation scope and does not claim that every planned check passed.

## v0.1.3

Preserved the v0.1.2 behavior and tightened DOCX inline source readback. Unsupported symbols, fields and visible constructs are rejected explicitly. See [docs/DOCX_INLINE_V013.md](docs/DOCX_INLINE_V013.md).

## v0.1.2 / v0.1.1 / v0.1

Introduced and hardened the single authority Store, true runtime evidence, Context projection, claim/source binding, controlled numeric display and document delivery chain. Historical design decisions remain under `docs/` and the original archive is retained separately.
