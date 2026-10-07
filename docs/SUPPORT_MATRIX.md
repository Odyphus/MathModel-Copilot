# 支持范围与证据口径

此表是候选声明范围。实际执行的平台、Python 版本、成功/失败/跳过数量和候选哈希，以交付目录的安装/总体验收 JSON 为准；不把 CI 配置写成远程已跑。

| 路径 | 实现与依赖 | 验证边界 |
|---|---|---|
| 本地核心 CLI、Store、Context | Python 3.10+ 标准库 | 针对声明的回归与安装行为；不等同数学结论正确 |
| 本地 Dashboard | 标准库服务 + 静态页面，无 Node 构建；默认只读 | 本机 127.0.0.1；可选意见记录，不是远程鉴权/多人实时服务 |
| 可选 AI 分析入口 | 本地 Codex CLI、有效登录与可用额度 | 新的只读分析，非桌面原聊天唤醒；实际调用结果单独记录 |
| Git 协作 | Git 可选；默认 Local | 本地事实、草稿和事务边界；远端实时状态需独立证据 |
| 合成 MCM demo | 标准库；历史模式 | 真实运行和独立检查；无现场交通校准、无正式提交 |
| CUMCM 历史案例 | 单独附件 + historical 依赖 | 清洁包不携带附件；内部完整运行证据另交 |
| Word/PDF 检查 | documents 依赖，实际渲染器单独安装 | 仅受支持正文/表格/原生公式；未知可见构造明确拒绝 |
| TeX | 独立外部编译器与字体 | 模板存在不等于完整 TeX 论文来源链已验收 |
| Windows / Linux | CI 配置各覆盖 Python 3.10、3.12 | 当前宿主实测与远程 CI 执行分别记录 |
| Python 3.12 | Preview 当前 Windows 宿主为 3.12.14 | 0.3 Windows 全套已执行并修复补测；WSL Ubuntu 24.04 / Python 3.12.3 另有 171 项关键测试，169 通过、2 项 Win32 专属跳过；macOS 与其他 Python 版本未实测 |

`failed`、`not_executed`、`stale`、`unknown` 和 `not_applicable` 分开。Stage 是导航；需求百分比必须有真实分母。文件哈希、测试通过或机器审计均不替代人工内容判断、来源许可或正式提交回执。

公开分发权利尚未确认时，候选可以本地评审，不能称为正式开源版。详见 [LICENSE_SCOPE.md](../LICENSE_SCOPE.md)。

本仓库维护者与目标已确认为 Odyphus / MathModel-Copilot，目前私有。GitHub Actions 保留原配置，首次上传时仓库级暂停执行，尚无远程 CI 成功声明。[当前验收](ACCEPTANCE_V03.md)。
