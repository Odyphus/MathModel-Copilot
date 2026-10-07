---
stage: 6
name: robustness
duration_h: 2-3
inputs:
  - "stage.5.sub_problems.{Qi}.{code_path, key_metrics}"
  - "stage.4.{assumptions, symbols}"
  - "stage.3.selected_per_subproblem"
outputs:
  - "stage.6.{params_varied_jointly, method, deltas, robust_intervals, stability_verdict, failure_warning, L2_backtrack, figures}"
loads_reference:
  - "competitions/<competition>/winning_patterns.md"
  - "references/rubrics.md"
  - "competitions/<competition>/anti_patterns.md"
loads_template:
  - "templates/shared/code_starter/simulation.py"
  - "templates/shared/sensitivity_table.md"
feedback: ["L1", "L2_cross_stage"]
next: stage_07_evaluation
---

> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。


# Stage 6 — 验证、灵敏度与稳健性分析

**时长**: 2-3h | **反馈层**: L1 + L2（跨阶段回检触发点）

## 目标

检查核心结论在合理的不确定性、数据切分、随机性与边界条件下是否仍成立，并明确已经验证的范围和尚未验证的风险。本阶段不要求所有题目都使用同一种方法，也不把参数数量、图数或采样算法当成质量代理。

## 输入

- Stage 5 各子问题的求解代码、核心结论与复现入口
- Stage 4 的假设、参数来源、符号与单位
- Stage 3 的模型选择理由和被拒方案

## 产出

- 风险清单与验证设计
- 扰动范围、数据切分或场景的依据
- 关键性能指标和决策变化的定量结果
- 适用范围、观察到的失败边界，或“测试域内未观察到边界”的诚实结论
- 对 Stage 3/4/5 的 L2 回检记录

## 操作流程

### Step 1：先列风险，再选方法（20 min）

对每个核心结论回答：什么变化最可能让它失效？至少覆盖与题目真正相关的风险类别。

| 风险类别 | 例子 | 需要追踪的结果 |
|---|---|---|
| 参数不确定性 | 测量误差、估计区间、成本波动 | 目标值、决策变量、可行性 |
| 数据漂移 | 时间、地区、人群或工况变化 | 泛化误差、排序、分类稳定性 |
| 随机性 | 初始化、仿真种子、抽样噪声 | 均值、区间、最坏结果 |
| 模型结构 | 分布假设、线性化、权重方案 | 结论方向、基线差异 |
| 离散边界 | 约束激活、方案切换、规则阈值 | 解集切换、不可行点 |

只选择会影响核心结论、且能在当前时间内验证的风险。未覆盖项写入 Stage 7，不要用无关扰动凑数量。

### Step 2：按风险匹配验证设计（15 min）

| 情况 | 可选方法 | 使用条件 |
|---|---|---|
| 单一主导参数、局部关系清楚 | OAT、局部导数、剖面分析 | 说明为何交互作用可忽略 |
| 多参数可能交互 | 因子设计、LHS、随机联合抽样 | 参数域和相关结构有依据 |
| 需要归因各参数贡献 | Sobol、Morris、方差分解 | 样本预算足够且输出适合该方法 |
| 时间或空间数据 | 滚动验证、按组留出、时空外推 | 避免随机切分造成泄漏 |
| 随机算法或仿真 | 多随机种子、重复实验、置信区间 | 报告种子与重复次数选择依据 |
| 离散方案或制度变化 | 情景枚举、边界扫描、压力测试 | 场景覆盖实际可能状态 |
| 优化模型 | 系数/RHS 扰动、替代最优解、可行性压力测试 | 同时检查目标值和决策变化 |

LHS 适合有依据的连续多参数域，OAT 可处理局部单参数风险，Sobol 适合样本预算充足的方差归因。三者没有等级顺序；选择理由写入 `decision_log.stages.6.method`。

### Step 3：用证据确定范围和样本预算（20 min）

扰动范围优先来自：

1. 测量精度、置信区间或估计误差；
2. 附件数据的历史分位与缺失机制；
3. 物理可行域、业务规则或题目给定边界；
4. 明确定义的正常、压力与极端场景。

如果只能做假设场景，直接标注 `scenario_assumption`，不要写成“真实波动”。样本数由计算预算、输出方差和结论稳定性决定；记录初始样本数，并在追加样本后检查区间或排序是否明显变化。

### Step 4：预先定义指标与判断标准（15 min）

在看到结果前写清：

- 基线结果及其来源；
- 关键性能指标与单位；
- 决策变化的度量（如绝对差、相对差、Hamming 距离、排序相关）；
- 可行性、误差或业务上可接受的边界及其依据；
- 哪种变化会触发 Stage 3/5 回退。

没有题目或业务依据时，不使用“极稳健、较稳健”这类无定义标签，改为报告数值范围和观察事实。

### Step 5：运行并保留可复核记录（60-90 min）

下面仅是连续多参数场景的示意；参数、范围和样本数必须由 Step 1-4 替换。

```python
from scipy.stats.qmc import LatinHypercube
import numpy as np

bounds = np.array([[p_low, p_high], [c_low, c_high], [b_low, b_high]])
sampler = LatinHypercube(d=len(bounds), seed=42)
unit = sampler.random(n=n_samples)
samples = bounds[:, 0] + unit * (bounds[:, 1] - bounds[:, 0])

records = []
for p_value, c_value, b_value in samples:
    result = solve_Q1(p_value, c_value, b_value)
    records.append({
        "objective": result.value,
        "feasible": result.feasible,
        "decision_change": np.linalg.norm(result.x - baseline_x),
    })
```

同时保存运行入口、随机种子、失败样本、异常处理与软件版本。预测或统计任务应替换为合适的数据切分与误差计算，不能为了复用代码而强行扰动参数。

### Step 6：只画能回答问题的图（20 min）

按证据需求选择：

- 参数—结果关系图：检查非线性、阈值或交互；
- 箱线图/区间图：比较场景或随机种子；
- 误差随时间/群组图：检查漂移与外推；
- 可行域或方案切换图：显示离散边界；
- Tornado/Sobol 图：仅在对应贡献度计算有效时使用。

一张能解释核心风险的图可以胜过多张重复图。每张图写明样本、范围、指标与结论。

### Step 7：报告范围与失败边界（20 min）

使用 `templates/shared/sensitivity_table.md`，至少写清：

- 在已测试域内，核心指标和决策怎样变化；
- 哪些结论稳定、哪些只在局部成立；
- 是否观察到不可行、误差超限或方案切换；
- 测试域之外不能推断什么。

若观察到边界，记录触发条件和影响；若没有观察到，写“在已测试域内未发现失败边界”，不要虚构临界参数。

### Step 8：L2 跨阶段回检（15 min）

读取 `decision_log` 并检查：

1. Stage 3 的模型选择是否仍有证据支持；
2. Stage 4 的假设是否被数据或压力测试挑战；
3. Stage 5 的上游结果复用在验证域内是否仍有效；
4. 是否存在必须重算的子问题或只需在 Stage 7 披露的限制。

输出：

```json
{
  "backtrack_targets": ["stage_5_Q3"],
  "verdict": "no_revert | revise_stage_7 | full_revert",
  "notes": "说明证据、影响范围与下一步"
}
```

`full_revert` 只在核心结论、可行性或模型前提被实证推翻时使用。

### Step 9：写入状态（10 min）

```json
{
  "params_varied_jointly": ["仅填写实际联合变化的参数；若无则为空数组"],
  "method": "方法、数据切分、范围依据、样本数与随机种子",
  "deltas": ["实际测试范围或场景标识"],
  "robust_intervals": {"metric_name": "区间、样本域与计算方法"},
  "stability_verdict": "只描述已测试域内的定量结论",
  "failure_warning": "观察到的边界；或测试域内未观察到边界",
  "L2_backtrack": {},
  "figures": ["只列实际生成且正文使用的图"]
}
```

## L1 Rubric

| 维度 | 满分行为 |
|---|---|
| 1. 验证设计契合度 | 方法覆盖核心风险，并说明单变量/联合/场景/重采样选择理由 |
| 2. 范围真实性 | 参数域、数据切分与场景有题目、数据或领域依据 |
| 3. 输出完整性 | 同时追踪关键性能、决策变化、可行性与失败样本中适用的部分 |
| 4. 定量可复核 | 报告样本、种子、计算方法、区间及判断标准 |
| 5. 边界诚实度 | 不虚构临界点，明确已观察边界与未测试区域 |

## 常见坑

- F1：核心结论完全没有验证 → 补最能挑战该结论的测试
- F2：方法与风险不匹配 → 先说明风险，再选择 OAT、联合扰动、重采样或情景分析
- F3：扰动范围没有来源 → 标注依据或明确为假设场景
- F4：只写“模型稳健” → 补测试域、指标变化、失败样本与限制

## 退出条件

1. 核心结论至少有一种与其风险匹配的验证；
2. 范围、数据切分、样本预算和判断标准可追溯；
3. 结果包含定量变化及适用边界，不伪造失败点；
4. L2 回检写入状态；
5. L1 全维达到工作流阈值。

→ 跳转 `stage_07_evaluation.md`
