---
stage: 3
name: model_selection
duration_h: 2-3
inputs:
  - "stage.2.{decomposition, objective_per_subproblem, data_schema}"
outputs:
  - "stage.3.{candidate_models, selected_per_subproblem, rejection_log, toy_demos_passed, red_team, model_family_consistency}"
loads_reference:
  - "references/model_catalog.md"
  - "references/rubrics.md§Stage_3"
  - "competitions/<comp>/winning_patterns.md§4"
loads_template: ["templates/shared/code_starter/<problem_type>.py"]
feedback: ["L1", "counterfactual_exploration_in_championship"]
next: stage_04_foundation
---

> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。


# Stage 3 — 模型选型 (证据驱动的合理候选集)

**时长**: 2-3h | **反馈层**: L1 + 反事实探索 (championship 深挖真实可行的替代路径)

---

## 目标

为每个子问题选定一个证据最充分的主模型，并记录所有真实可行的替代模型及否决依据。候选数量由问题结构和证据决定；若检索后没有合理替代，记录检索范围与原因，不用不适配模型凑数。模型名称必须准确反映实际实现，跨子问题接口必须可解释。

---

## 输入

- stage 2 输出: 子问题卡片 + 目标函数雏形 + 数据 schema
- `references/model_catalog.md` 必读

## 产出

- 每个 Qi 的主模型 + 准确名称 + 选型理由
- 每个 Qi 的合理替代候选 + 否决理由；没有合理替代时记录检索证据
- 覆盖关键失败模式的最小可执行 demo (Python)
- (championship) red-team 攻击与回应

---

## 操作流程

### Step 1: 问题类型映射 (10 min)

对每个 Qi,查 `references/model_catalog.md` §0 速查表:

```
Q1: "求最优生产计划" → 优化类 (LP/IP)
Q2: "考虑库存约束" → 优化类 (MIP) + 启发式
Q3: "随机需求下的稳健决策" → 鲁棒优化 / 随机规划 / 蒙特卡罗
```

### Step 2: 候选生成 (45 min)

为每个 Qi 先从题面目标、约束类型、数据规模、缺失机制与可用求解器出发形成初步候选，再用目录和必要的原始文献核对适用条件与专业名称。注明哪些依据来自题面，哪些来自外部资料；无需为了开始分析先通读论文库。优先保留结构性不同且能解决**同一任务**的方案；跨模型族只有在目标与约束仍可公平比较时才有意义。若只有一个合理方案，明确记录原因和实际查阅范围，不虚构检索:

```
Qi 候选 <ID>: <模型与模型族>
  - 适配证据: <对应目标/约束/数据性质>
  - 实现路径: <库/求解器/自实现>
  - 可验证优势: <用什么基线或诊断验证>
  - 风险: <复杂度、假设或数据风险>
  - 结论: retain / reject；<证据>
```

**反模式 C3 检查**: 若候选只是同一方法换名字，合并重复项；若跨族方案不能解决同一任务，不得为了“多样性”加入。多样性是发现反事实的手段，不是数量门槛。

### Step 3: 选型决策矩阵 (30 min)

为每个 Qi 做加权评分:

| 维度 | 权重 | `<候选 1>` | `...` | `<候选 N>` |
|------|-----|-----------|-------|-----------|
| 1. 适配度 (与问题契合) | 0.30 | `<score>` | `...` | `<score>` |
| 2. 求解可行性 (库支持/复杂度) | 0.25 | `<score>` | `...` | `<score>` |
| 3. 时间预算 (实施所需 h) | 0.20 | `<score>` | `...` | `<score>` |
| 4. 可验证增益空间 | 0.15 | `<score>` | `...` | `<score>` |
| 5. 文献或理论支持 | 0.10 | `<score>` | `...` | `<score>` |
| **加权** | | `<weighted>` | `...` | `<weighted>` |

→ 选择证据最充分且在时间预算内可验证的候选；分数不能替代否决证据。

先向用户展示候选的真实结构差异与取舍，不只报分数。若用户要求选择或缺少会改变长期方向的偏好，集中请其决定；已有自主推进授权时，记录建议路线及理由后开展小规模验证。不要要求每个 Qi、每轮验证都回复编号；未选路线仍是候选，用户意见也不自动等于已核验。

### Step 4: 可核验命名 (15 min)

名称只写已经进入公式、代码或实验的限定条件与机制:

模式: `<已实现且可核验的限定/机制> + <核心模型>`

若只实现标准模型，就使用标准名称。不得为了显得创新添加“改进”“自适应”“多层”等修饰词；声称复合、松弛或动态机制时，必须能指向对应公式、代码与消融/基线证据。

最终名称与证据位置写入 `decision_log.stages.3.selected_per_subproblem.<Qi>`。

面向队员用一张简短的模型说明卡交付。先用直觉解释问题，再让解释落到可核对的专业结构；不要只在标题中补几个缩写：

| 内容 | 写清什么 |
|---|---|
| 直觉与专业名称 | 用日常语言说明在求什么，随后给准确模型名称及常用简称 |
| 数学结构 | 决策变量/状态变量、目标函数或控制方程、关键约束/初边值条件，说明关键假设 |
| 求解方法 | 将模型与算法分开，例如“非线性扩散方程；有限体积法离散；隐式时间积分” |
| 选择与替代 | 适配当前数据/约束的理由，候选之间真正的差异和代价 |
| 验证与状态 | 将如何检查可行性、误差或最优性；当前是候选、已采用、已运行还是已核验，并指向记录 |

例如把圆柱材料视为同心薄层是直觉解释，落实到模型应说明“轴对称一维径向瞬态传热/扩散模型”。只有方程中确实存在相互依赖时才叫热湿耦合；只有结构满足线性条件才叫线性规划。专业名称和算法示例都不是为所有题目预选的答案。对尚未运行的候选写“拟采用”，不能用求解器名称暗示已求得最优解。

### Step 5: Toy Demo 验证 (45 min)

为每个 Qi 写最小可执行 demo。规模应足以覆盖关键约束、数据接口和已知失败模式：优先从真实数据构造代表性切片；若真实数据尚不可用，使用明确标注的合成 sanity case。不要用固定行数、固定抽样比例或固定秒数代替可行性证据:

```python
# Qi feasibility demo - 用项目中的实际构造器保持接口一致
case = build_representative_case(problem_data, cover=critical_constraints)
model = build_model(case)
result = solve(model, time_budget=remaining_stage_budget)

assert result.status in accepted_statuses
assert constraints_hold(result, case)
record_runtime_and_scale(result, case)
```

要求:
- 求解器状态可解释，输出满足关键约束
- 数据规模与覆盖范围有记录，能暴露主要失败模式
- 运行时间不超过该候选在实际 deadline 下的可用预算
- 结果数量级通过题面边界或独立基线校验

不通过 → 候选无效,回 Step 2 换。

### Step 6: 跨子问题模型族协调 (10 min)

检查全部 Qi 的主模型是否能通过明确接口衔接:
- 库或数据结构不同是否有可靠转换层?
- 不同模型族组合时，输入输出、触发条件与误差传播是否明确?
- 为统一工具而牺牲问题适配度时，回到 Step 3 重评。

写入 `decision_log.stages.3` 的 "model_family_consistency" 字段。

### Step 7 (championship 模式): Red-team 攻击 (30 min)

> 假装最严苛评委，列出能够改变选型结论的实质攻击，并给出可核验回应。合并同义攻击；没有新的实质攻击时停止，不凑数量。

模板:
```
攻击: <能够改变选型结论的失败模式>
证据需求: <benchmark、收敛诊断、接口检查或公式/代码定位>
回应: <已有证据；没有证据时写待验证，不预填结论>
状态: resolved | open
```

写入 `decision_log.stages.3.red_team`。

### Step 8: 输出移交 (10 min)

写入 `decision_log.stages.3`:
```json
{
  "candidate_models": [...],
  "selected_per_subproblem": {
    "<Qi>": {"name": "...", "library": "...", "rationale": "...", "evidence_paths": [...]}
  },
  "rejection_log": [...],
  "toy_demos_passed": true,
  "red_team": [...],
  "model_family_consistency": "..."
}
```

---

## L1 Rubric

| 维度 | 满分行为 |
|------|---------|
| 1. 候选质量与反事实覆盖 | 所有合理替代均被评估；无合理替代时检索范围与原因可审计 |
| 2. 选型理由 | 每候选有适配 + 不选原因 |
| 3. 命名准确性 | 每个修饰词均能定位到公式、代码与验证；允许标准名称 |
| 4. 求解可行性 | toy demo 通过 |
| 5. 文献/理论支撑 | 关键选型主张有相关且已核验的来源；不以篇数代替相关性 |

championship 额外: red_team 覆盖所有能改变结论的实质攻击，每个回应有证据或明确的待验证状态。

## 常见坑

- C1 为显得创新强行改名 → Step 4 要求名称与实际实现逐项对应
- C2 模型不匹配 → Step 1 速查表对照
- C3 候选重复或伪跨族 → 合并同义项，只保留真正可比较的替代
- C4 选型理由薄弱 → Step 3 5 维矩阵
- C5 不验证可行性 → Step 5 toy demo

## 退出条件

1. 每 Qi 选型完成 + 名称与实现一致
2. 每 Qi 的合理替代已评估；若无替代，检索范围与理由已记录
3. toy demo 通过
4. (championship) 所有实质 red-team 攻击均有证据回应或明确的未解决风险
5. L1 全维 ≥7

→ 跳转 `stage_04_foundation.md`
