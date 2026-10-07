> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。

# Feedback Layer 4 — 独立证据校准

> 深度审查模式使用。L4 通过不同的证据视角复核高影响维度，发现“分数上升但证据没有变强”的情况。它不模拟奖项、不猜测评委偏好，也不把两个模型分数之差直接解释为 rubric 被操纵。

## 为何需要 L4

同一 Critic 反复看同一结构，可能逐渐偏好熟悉的措辞。L4 的任务不是再打一遍分，而是独立检查：

- 关键主张是否能定位到公式、数据、代码或规则；
- 复现实验是否真的支持主张；
- 反例、失败样本和适用边界是否被遗漏；
- 高分来自证据改善，还是只来自语言对齐。

模型评分存在随机性。分差只是复核信号，不能单独证明 artifact 变好、变差或“被 game”。

## 触发条件

在 `championship` 模式中，对高影响阶段最多校准一次；出现以下任一情况时优先触发：

1. L1 分数明显上升，但结果文件、实验或引用没有变化；
2. Critic 给出高分，却无法指出具体证据位置；
3. 高风险主张只有单一验证；
4. 两个审查视角对事实或影响范围有实质分歧；
5. Stage 9 终审前仍有 carryover。

```python
def should_calibrate(stage, l1_result, history):
    if mode != "championship" or history.already_calibrated(stage):
        return False
    return (
        l1_result.unsourced_high_score
        or history.score_rose_without_new_evidence(stage)
        or l1_result.high_risk_single_check
        or l1_result.substantive_disagreement
        or history.has_carryover(stage)
    )
```

若没有触发信号，不为覆盖固定维度而运行 L4。

## 校准输入

L4 必须获得：

- 当前 artifact 及版本标识；
- L1 的维度、分数、证据定位和 issues；
- 支撑文件清单及可运行命令；
- 本轮相对上一版的实际变更；
- 竞赛当年规则和题目要求。

只给论文片段、不提供支撑文件时，L4 必须把“无法复核”写入结论。

## Prompt 框架 A：证据账本

```text
独立复核维度 {dim_name}。不要先看原分数。

1. 列出 artifact 中影响本维度的关键主张。
2. 为每个主张定位支撑：公式、数据、代码、实验、引用或官方规则。
3. 标记 support = verified | partial | missing | contradicted。
4. 指出复现命令或仍需执行的最小检查。
5. 仅根据可核验证据给 1-10 内部质量分，并说明适用范围。

禁止根据奖项印象、写作气势或关键词数量评分。
```

## Prompt 框架 B：反例与边界

```text
独立复核维度 {dim_name}。

尝试找出最可能推翻核心结论的反例、失败样本或边界条件。
只列与该模型真实风险相关的项，不凑数量。
对每项写：当前证据、缺失测试、若失败会影响的结论。
然后根据已经验证的范围给内部质量分。
```

两种框架按风险选择；不是为了随机换措辞。事实核验优先于故事化角色扮演。

## 输出协议

```json
{
  "type": "L4_calibration",
  "stage": 6,
  "dim": "1_multivariate_perturbation",
  "framework": "evidence_ledger | counterexample_boundary",
  "artifact_version": "...",
  "claims": [
    {
      "claim": "...",
      "support": "verified | partial | missing | contradicted",
      "evidence": ["path#anchor"],
      "recheck": "command or null"
    }
  ],
  "original_score": 8,
  "alt_score": 6,
  "score_delta": 2,
  "reasoning_disagreement": "none | interpretation | evidence_gap | factual_conflict",
  "action": "keep | verify | revise_claim | rerun_stage | block",
  "notes": "说明影响范围；分差本身不触发改分"
}
```

## 决策规则

按分歧类型行动，而不是按固定分差自动重置：

| 分歧 | 行为 |
|---|---|
| `none` | 保留 L1，记录校准 |
| `interpretation` | 记录两种解释；检查 rubric 是否含糊，不自动改分 |
| `evidence_gap` | 补最小实验/引用/定位，完成后重评受影响维度 |
| `factual_conflict` | 回到数据、代码或官方规则核验；未解决前标记 `block` |
| 主张被证伪 | 修改或删除主张，必要时回退相应 stage |

只有证据复核完成后才能更新分数。`alt_score` 用于展示审查差异，不直接覆盖 decision log。

```python
def apply_calibration(result):
    log_event(result)
    if result.reasoning_disagreement == "factual_conflict":
        return "block_until_verified"
    if result.reasoning_disagreement == "evidence_gap":
        return "run_minimum_recheck"
    if any(c["support"] == "contradicted" for c in result.claims):
        return "revise_or_rerun"
    return "keep_with_note"
```

## 阶段优先级

优先校准错误代价高的内容：

- Stage 3：模型选择理由是否有真实基线或约束依据；
- Stage 5：数学定义、代码结果和论文数值是否一致；
- Stage 6：验证方法是否匹配风险，结果能否复现；
- Stage 8：摘要主张是否能回指正文和结果；
- Stage 9：合规结论是否来自当年官方规则。

维度名称为兼容状态文件可保持旧键，例如 `1_multivariate_perturbation`；校准时评价的是风险匹配和证据充分性，不是参数数量。

## 去重与预算

- 同一 stage、artifact 版本和维度只校准一次；artifact 实质变化后才可重跑。
- 先检查高影响主张，预算不足时缩小范围并记录未审项。
- 不承诺固定 token 数或调用次数；实际成本取决于支撑文件和复现实验。

## 设计风险

- **校准器也会犯错**：事实冲突回到原始数据、代码与官方规则，不做多数投票。
- **证据不可用**：明确标为 `missing`，不要凭语言质量补分。
- **重复审查拖慢交付**：同版本去重，优先解决会改变结论或合规性的分歧。
- **rubric 本身含糊**：记录 `interpretation`，修订 rubric 后再评价，不把责任归给 artifact。
