> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。

# 评分细则 (rubrics)

> 三竞赛通用 5 维 rubric (国赛 / 美赛 / 电工杯 共享 stage 0-7 框架, stage 8/9 由 `competitions/<comp>/rubric_overlay.json` 特化)。L1 Critic 直接 JSON 化使用。

---

## Overlay 协议 (v3.1)

| 层级 | 来源 | 加载 |
|------|------|------|
| 通用基础 | 本文件 stage 0-9 表格 | 三竞赛共享 |
| 竞赛特化 dim 名 | `competitions/<comp>/rubric_overlay.json` 的 `dim_whitelist` | score_artifact.py 自动合并 |
| 题型 dim 权重 | `config/dim_weights.json[<comp>][<task_type>]` | compute_verdict 加权 mean |
| 样本观察 | `competitions/<comp>/empirical.json` | Critic 评分前按竞赛加载；只作参照 |

`task_type` 由 stage 1 选题后填入 decision_log; null 时 default 全 1.0 等价老逻辑。

---

## 三竞赛约束与内部质量视角

### CUMCM 国赛（内部启发式，不是官方评分权重）

| 维度 | 内部关注度 | 关键检查项 |
|------|-----|----------|
| **摘要质量** | 高 | 任务覆盖 / 可追溯的量化结果 / 验证与边界 / 信息密度 |
| **模型建立** | 高 | 与问题契合 / 假设有支撑 / 数学严谨 / 设计真实可解释 |
| **求解与结果** | 高 | 算法合理 / 代码可复现 / 结果可视化 / 现实意义 |
| **写作呈现** | 中 | 章节完整 / 公式编号规范 / 图表清晰 / 语言流畅 |
| **创新性** | 中 | 真实机制改进 / 跨学科融合 / 合理的子问题复用 |

### MCM/ICM 美赛（官方约束 + 内部质量检查）

> 当前没有可用于统计校准的语料；`competitions/mcm/empirical.json` 只是结构占位，不能把其中数值用于评分。

| 维度 | 关键检查项 |
|------|----------|
| **Summary Sheet** | 第 1 页 / 方法与结果可追溯 / 限制诚实 |
| **Approach & Modeling** | 问题契合 / 假设支撑 / 设计选择有证据 |
| **Solution & Results** | 算法 / 复现性 / 与模型风险匹配的验证 |
| **Communication** | 写作清晰 / 图表 self-contained / 术语精确 |
| **Problem-specific deliverable** | 仅题目明确要求时加入 / 面向目标读者 / 保留证据与 caveat |

### 电工杯（内部工程质量检查）

> 当前没有可用于统计校准的语料；`competitions/diangong/empirical.json` 只是结构占位，不能把其中数值用于评分。

| 维度 | 关键检查项 |
|------|----------|
| **工程实用性** | 落地可行 / 适用时的成本估算 / 实施条件 |
| **物理意义** | 数值带 kW/kWh/% / 工程语义 |
| **数据完整性** | 关键字段可追溯 / 未用字段说明取舍 / 预处理有据 |
| **多场景对比** | 场景覆盖主要工程风险 / 参数扰动有现实依据 |
| **写作呈现** | 引用格式按当年规则 / 工程惯用图表 / 单位与图例完整 |

---

## L1 阶段级 rubric (5 维 × 1-10)

每阶段产出后,Critic 输出以下 JSON:

```json
{
  "stage_id": 0-9,
  "iteration": 0-3,
  "scores": {
    "<dim_key_snake_case>": {"name": "中文名称", "score": 1-10, "evidence": "≤30字"},
    ...
  },
  "min_score": <number>,
  "mean_score": <number>,
  "issues": [
    {"severity": "high|medium|low", "where": "...", "anti_pattern_id": "A1|null", "fix": "..."},
    ...
  ],
  "verdict": "block | pass_early | pass | refine"
}
```

**dim key 命名约定**: 各 stage 的 5 个 `scores` 字段必须用**英文 snake_case**, 与 `feedback_layer1_critic.md §6` 各 stage 列出的固定集合精确一致 (`scripts/score_artifact.py` 加白名单校验)。下面各 stage 表第一列写中文是为了人读, 实际 JSON 输出用英文 key, **中文写在 `name` 子字段**。

退出条件: 见本文件末尾"阈值汇总"节, 与 SKILL.md / feedback_layer1_critic.md / score_artifact.py 三处统一。

---

### Stage 0 — 团队启动

| 维度 | 满分行为 (10) | 失败行为 (1) |
|------|-------------|-------------|
| 1. 角色分工明确性 | 按实际人数覆盖建模/编程/写作责任，并设置互备 | 职责和交接人不明确 |
| 2. 工具就绪度 | 题目需要的计算、写作、版本与沟通工具已验证 | 关键工具尚未试运行 |
| 3. 时间盒规划 | 按实际截止时间设置里程碑、关键路径和缓冲 | 无计划 |
| 4. 题目预扫信号 | 已识别问题域 (优化/预测/评价等) | 未读题 |
| 5. 协作约定 | 命名规范、版本控制、daily standup 时间 | 无规范 |

---

### Stage 1 — 选题

| 维度 | 满分行为 |
|------|---------|
| 1. 备选题对比深度 | 系统比较当年可选题，覆盖难度/数据/契合度/工具/资料与主要风险 |
| 2. 团队优势匹配 | 选题理由含"我们擅长 X,本题需要 X" |
| 3. 风险识别 | 覆盖最可能改变选题结论的风险，并给出预案 |
| 4. 时间可行性 | 已按实际截止时间估算阶段配额、关键路径与缓冲 |
| 5. 决策记录质量 | rationale 与关键 rejected alternatives 均有可核验依据 |

退出条件: 选定题号 + decision_log.json stage 1 节点完整 + 全维 ≥7。

---

### Stage 2 — 问题深度解析

| 维度 | 满分行为 |
|------|---------|
| 1. 子问题分解清晰度 | 每个 sub-problem 的输入/输出/约束明确 |
| 2. 关键变量识别 | 覆盖题面与模型实际使用的变量，并区分决策变量/状态变量/参数 |
| 3. 数学化程度 | 每个 sub-problem 的数学对象、输入输出、约束或评价关系与题意对应 |
| 4. 数据契合度 | 题目附件数据已扫描,与变量映射清楚 |
| 5. 子问题关联性 | 已判断后续问题是否依赖上游结果；存在依赖时可追踪 |

---

### Stage 3 — 模型选型

| 维度 | 满分行为 |
|------|---------|
| 1. 候选数量与多样性 | 比较足以支撑决策的结构性不同候选；没有合理替代时说明原因 |
| 2. 选型理由 | 每个候选有 (a) 适配理由 (b) 不选的原因 |
| 3. 模型命名真实性 | 名称准确反映实际机制、约束或组合，不用空泛修饰词制造创新感 |
| 4. 求解可行性 | 已确认 Python 库存在 + 时间复杂度可承受 |
| 5. 文献支撑 | 关键方法与假设有可靠来源；引用数量由实际使用决定 |

championship 模式额外：red-team 提出最可能推翻模型选择的反例或证据缺口，并给出验证动作。

---

### Stage 4 — Foundation (假设 + 符号 + 术语)

| 维度 | 满分行为 |
|------|---------|
| 1. 假设必要性 | 只保留模型真正依赖的假设；数量由题目与方法决定 |
| 2. 假设支撑 | 每条配 (a) 文献 / (b) 数据观察 / (c) 物理意义 三选一 |
| 3. 符号唯一性 | 同一符号不跨语境换义；需要单位的量均标明单位 |
| 4. 与模型一致性 | stage 5 后回检,无矛盾 |
| 5. 术语规范 | 专业术语首次出现给定义,中英对照 |

---

### Stage 5 — 子问题递归循环 (per Qi)

每个 sub-problem 跑一次 5 维 rubric,**外加** stage-level overall:

#### Per-Qi rubric:

| 维度 | 满分行为 |
|------|---------|
| 1. 模型与问题契合 | 目标函数 / 决策变量 / 约束 与题面一一对应 |
| 2. 数学严谨性 | 推导无跳跃,符号一致,边界条件齐全 |
| 3. 求解正确性 | 代码可运行,结果数量级合理,通过 sanity check |
| 4. 结果证据呈现 | 使用足以解释数据、方法与核心结果的图表；不按数量凑图 |
| 5. 现实意义讨论 | 把数值翻译为题目语境中的意义、范围与限制 |

#### Stage-level (跨子问题):

- **复用链**: 题目存在依赖时，上游结果的版本、单位与误差传播是否可追踪；独立子问题不强行建立复用
- **变量一致性**: 不同子问题间变量符号统一

退出条件: 所有 Qi 通过 + 复用链满足 + 全维 ≥7。

---

### Stage 6 — 全局灵敏度 / 稳健性

| 维度 | 满分行为 |
|------|---------|
| 1. 验证设计契合度 | 按核心风险选择 OAT、联合扰动、重采样、数据留出、情景或边界分析，并说明理由 |
| 2. 扰动/验证域合理 | 范围、切分和场景来自数据、测量、物理边界或明确的假设 |
| 3. 输出指标完备 | 报告题目相关的性能、决策变化、可行性和失败样本 |
| 4. 范围定量可复核 | 给出测试域、样本/种子、区间算法、判断标准与证据路径 |
| 5. 失效边界诚实 | 报告观察到的边界；未发现时说明测试域，不虚构临界参数 |

L2 触发: 末尾跨阶段回检 stage 3 的模型选择前提是否被本节结果推翻。

---

### Stage 7 — 模型评价 + 推广

| 维度 | 满分行为 |
|------|---------|
| 1. 优点具体 | 每项都有证据路径、适用范围与不外推声明 |
| 2. 缺点真实 | 每项说明证据、受影响结论、替代方案与验证代价 |
| 3. 改进方向 | 区分 planned/tested/adopted/rejected；未做对照实验时不填写收益 |
| 4. 推广场景 | 说明可复用结构、重新标定、新风险与最低验证；证据不足时不强行推广 |
| 5. 自我批判可信度 | 不写"假设理想化"等套话 (anti_patterns.md 自动检) |

---

### Stage 8 — 论文写作

| 维度 | 满分行为 |
|------|---------|
| 1. 摘要信息闭环 | 覆盖问题、逐问方法、可追溯结果、验证与边界；不机械凑段或字数 |
| 2. 章节完整性 | 题目要求与证据链所需章节齐全,无空节 |
| 3. 公式 / 图表 / 引用 | 编号规范,首次引用先解释,引用格式符合所选竞赛当年要求 |
| 4. 语言质量 | 句长适度,无明显语病 (phrase_bank 关键词命中率) |
| 5. 视觉一致性 | 字号/配色/字体 全文统一,无 Word/Excel 默认输出 |

---

### Stage 9 — 终稿审核

5 视角 panel (Layer 3),每个 panelist 独立打分:

| Panelist | 关注 |
|----------|------|
| **数学严谨** | 定理引用、推导、边界条件、单位 |
| **模型贡献** | 设计必要性、基线比较、实质改动证据 |
| **代码正确** | 复现性、注释、变量名、可读性 |
| **写作呈现** | 摘要、章节、图表、引用、配色 |
| **评委视角** | 30 秒内能否看懂核心问题、方法、结果与可信度 |

每位 panelist 输出:
```json
{"panelist": "...", "scores": {"1_dim": {"score": 8, "evidence": "..."}}, "issues": [], "verdict": "ready|refine|block"}
```

聚合器:
- 任一 high-severity issue 保持 `block`，权重不能覆盖
- 找最低分与高影响 issue，定向修补对应阶段一次
- 只让受影响视角复核；时间压力不把已知违规或错误变成 `ready`

---

## 阈值汇总 (与 SKILL.md / feedback_layer1_critic.md / score_artifact.py 统一)

**verdict 优先级 (从高到低)**:

| verdict | 触发条件 | 行为 |
|---------|---------|-----|
| `block` | issues 含 ≥1 high-severity | 暂停 skill, 用户介入 |
| `pass_early` | raw_min ≥ 9 AND weighted_mean ≥ 9 | iter-1 早退, 节省 token |
| `pass` | raw_min ≥ 7 AND weighted_mean ≥ 8 | 进下一阶段 |
| `pass_with_review` *(stage 5)* | 任 Qi mark_for_review 但加权阈值满足 | 进 stage 6, L2 必读 review_qis |
| `refine` | 其他 | section-patch 精修, iter+=1 (cap 3) |
| `refine_partial` *(stage 5)* | 任 Qi.min < 7, 但其他 Qi 已 pass | 仅 refine 标记 Qi, 不动其他 |
| `carryover` | iter == 3 仍 refine 或 refine_partial | 进下一阶段, 标记由 L2 处理 |

`weighted_mean` = Σ(s_i × w_i) / Σ(w_i), 其中 w_i 来自 `config/dim_weights.json` 题型加权 (clamp [0.7, 1.5]); `task_type=default` 全 1.0 等价老逻辑。

**内部质量档位**（用于工作流自检，不对应、也不预测竞赛奖项）：

| 档位 | 单维最低 | 均值 |
|---|---:|---:|
| 强 | ≥8 | ≥9 |
| 可交付 | ≥7 | ≥8 |
| 待复核 | ≥6 | ≥7 |
| 阻塞 | <6 | - |

---

## 与 winning_patterns / anti_patterns / empirical 的对应

本文件 rubric 项 ↔ `competitions/<comp>/winning_patterns.md` 段落 (路径按 decision_log.competition dispatch):
- abstract.* (stage 8 dim 1) → patterns §1, §9 + anti_patterns §A
- paper.section_completeness (stage 8 dim 2) → patterns §2 + anti_patterns §I
- paper.figure_density → patterns §3 + anti_patterns §E
- model.naming (stage 3 dim 3) → patterns §4 + anti_patterns §C1
- subproblems.cross_reference (stage 5 stage-level dim 2) → patterns §5 + anti_patterns §G
- assumptions.support (stage 4 dim 2) → patterns §6 + anti_patterns §B
- sensitivity.multivariate (stage 6 dim 1) → patterns §7 + anti_patterns §F
- evaluation.limitations_real (stage 7 dim 2) → patterns §8 + anti_patterns §H
- evaluation.real_critique → patterns §8

字数、图表数和公式数不作为官方硬阈值。CUMCM 的 `empirical.json` 记录 91 份来源中的 59 份可提取子集，只能用于异常提示。MCM/ICM 与电工杯的 `empirical.json` 均为无语料结构占位，不得引用其中数值。若 critique 提供 `evidence_metrics`，`score_artifact.py` 会打印可用的分位比较；它不会据此自动改分或把样本观察当作官方阈值。
