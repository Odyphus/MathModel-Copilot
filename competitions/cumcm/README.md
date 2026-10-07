# CUMCM 国赛特化层

全国大学生数学建模竞赛专用资源。

| 字段 | 值 |
|------|-----|
| 竞赛代码 | `cumcm` |
| 官方名 | 全国大学生数学建模竞赛 |
| 时长 | 72 小时 (3 天) |
| 队员 | 3 人 (建模 / 编程 / 写作) |
| 语言 | 中文 |
| LaTeX 编译器 | xelatex |
| LaTeX 模板 | `templates/latex/cumcm/main.tex`（仓库原创电子论文装配模板） |
| 引用格式 | 按科技论文规范；仓库默认建议 GB/T 7714，提交前以当届要求为准 |
| 题号 | A / B / C / D / E (近年 F 并入 B) |
| 子问题数 | 只从当届题面提取；未知时保持 `null`，不预设数量 |
| 数据状态 | 91 份来源文档; 其中 59 份成功文本提取并进入分位统计 |
| 当前规则 | 2026 规则/格式 + 2025 AI 试行规定; 见 `current_rules.md` |

## 文件清单

| 文件 | 用途 | 加载阶段 |
|------|------|---------|
| `topic_specs.json` | 题号体系 + 题型→task_type 映射 | stage 1 |
| `rubric_overlay.json` | 国赛特化评分维度 overlay | stage 8/9, score_artifact |
| `empirical.json` | 59 份可提取样本的观察分位 | 评分前的参考锚点 |
| `empirical_notes.md` | 样本与提取限制说明 | 文档参考 |
| `winning_patterns.md` | 经验模式与操作性启发 | stage 8 (anchor) |
| `phrase_bank.md` | 中文学术句式库 | stage 8 |
| `anti_patterns.md` | 42 条启发式检查项 | stage 9 (逐条对照) |
| `distilled_phrases.md` | 段落模板 | stage 8 |
| `distilled_naming.md` | 命名变体 | stage 3 |
| `distilled_structures.md` | 章节结构模板 | stage 8 |
| `distilled_formats.md` | 格式细节 | stage 8/9 |
| `abstract_template.md` | 摘要信息功能模板 + 示例 | stage 8 |
| `paper_skeleton.md` | 按题目与当届格式调整的论文骨架 | stage 8 |
| `current_rules.md` | 2026 电子版、支撑材料与 AI 披露基线 | stage 0/9 |

## 数据来源

- 教育部"中国大学生在线"数学建模论文展廊 (2023-2025, 32 篇)
- GitHub `zhanwen/MathModel/国赛论文/2023年优秀论文/` (58 篇, A-F 全)
- GitHub `Jackyleo-Zhao/cumcm-2025` (1 篇国二 C 题)

烘焙时间 2026-05-05。91 份来源中仅 59 份成功文本提取；这些分位是观察基线，不是官方阈值或获奖预测。烘焙脚本已存档于 `scripts/ingest_papers.py`。

## 电子提交与 AI 合规

- 电子论文第一页必须是摘要页，不放承诺书、编号页、目录或身份信息。
- 论文文件与支撑材料分别提交，均不超过 20 MB；支撑材料应含完整可运行代码与文件清单。
- 使用 AI 时，正文相应位置和参考文献必须披露，并在支撑材料提供 `AI工具使用详情.pdf`。
- 明确未使用 AI 时，不生成详情 PDF；在参考文献后加入官网要求的未使用声明。
- Stage 0 与 Stage 9 必须读取 `current_rules.md` 并再次核对当届官方文件。

## 与 references/ 通用层的关系

- `references/stage_NN_*.md` 在加载本目录文件时, 通过 `decision_log.competition` 字段 dispatch
- 通用模型清单 `references/model_catalog.md` 跨竞赛复用
- 反馈层 `references/feedback_layer*.md` 通用；L1 critic 在需要经验锚点或异常提示时读取本目录的 `empirical.json`，不把样本分位当成官方门槛
