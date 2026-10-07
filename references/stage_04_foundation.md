---
stage: 4
name: foundation
duration_h: 1
inputs:
  - "stage.2.key_variables"
  - "stage.3.selected_per_subproblem"
outputs:
  - "stage.4.{assumptions, symbols, terminology, consistency_check}"
loads_reference: ["references/rubrics.md§Stage_4", "competitions/<comp>/anti_patterns.md§B"]
loads_template: ["templates/shared/assumption_table.md", "templates/shared/notation_table.md"]
feedback: ["L1"]
next: stage_05_subproblem_loop
---

> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。


# Stage 4 — Foundation (假设 + 符号 + 术语 一体化)

**时长**: 1h | **反馈层**: L1 | **特点**: 短但关键,任何下游不一致都从这里溯源

---

## 目标

把假设 / 符号 / 术语**一次性**系统化成正式的论文章节素材,确保 stage 5-9 不会出现 "符号变了"、"假设忘了"、"术语没定义" 等基础失分。

---

## 输入

- stage 2 全局变量表
- stage 3 选定模型 (隐含一些假设)

## 产出

- 假设清单 (仅保留模型实际依赖且有支撑或可检验的假设) → 论文 §3
- 符号说明表 (含单位、类型) → 论文 §4
- 术语表 (仅收录正文实际使用且可能歧义的专业词、缩写) → 论文 §4 附录或脚注
- 写入 `decision_log.stages.4`

---

## 操作流程

### Step 1: 假设挖掘 (20 min)

从三个维度提问:

**a) 模型隐含假设** (来自 stage 3 选型):
- 选 LP → 暗含线性关系假设
- 选 蒙特卡罗 → 暗含分布假设
- 选 SIR → 暗含均匀混合假设

**b) 数据假设** (来自附件扫描):
- 附件数据无系统偏差
- 缺失值机制 MCAR (随机缺失)
- 时间序列平稳

**c) 环境假设** (来自题目语境):
- 短期内市场/政策/物理环境不变
- 决策者理性
- 无外部冲击

逐项追问“删掉这条是否会改变模型、数据处理或结论边界”。只保留答案为“会”的必要假设；同义假设合并，没有支撑且也无法验证的非必要假设删除。

### Step 2: 假设支撑与状态 (15 min)

每条假设记录来源、证据路径与状态。来源可为文献、附件数据、物理/业务机制或后续可执行检验；不要预填统计结果:

```
A1: <模型实际依赖的假设>
来源: literature | data | physical | business | test
证据: <引用、附件字段、规则条款或待运行检验的产物路径>
状态: verified | provisional | rejected
影响: <若不成立，哪些公式、代码和结论需要回退>
```

**反模式 B1 (假设无支撑)**: 必要但尚未验证的假设必须标记 `provisional`，并在 stage 5/6 安排检验或敏感性分析；若其不成立会推翻主结论且无法验证，则 block。不得编造“依据”让它看似已验证。

### Step 3: 符号表正式化 (15 min)

复制 stage 2 全局变量表,补全:

| 符号 | 含义 | 单位 | 类型 | 取值范围 |
|------|-----|------|------|---------|
| `<symbol>` | `<正文中的实际含义>` | `<实际单位或无量纲>` | `<decision|parameter|state|random>` | `<由题面、定义或数据给定>` |

**反模式 B5 (无单位)** 自动检测: 单位列空 → block (除非 "无量纲" 显式标注)。
**反模式 B4 (符号重复)** 自动检测: 同一符号不同行 → block。

下标约定:
- i: 产品索引, i = 1, ..., n
- t: 时间索引, t = 1, ..., T
- s: 场景索引, s = 1, ..., S

### Step 4: 术语表 (5 min)

只为正文实际使用且可能歧义的专业术语建立中英对照；通用词或未使用的术语不加入:

| 中文 | 英文 | 缩写 | 首次出现章节 |
|------|------|------|------------|
| `<实际使用术语>` | `<verified English name>` | `<有则填，无则留空>` | `<实际章节>` |

### Step 5: 一致性预检 (5 min)

回扫 stage 2-3 的所有产出,对照本文:
- 任何 stage 2 提到的变量,本文表中都有?
- stage 3 选模型时提到的 "假设 ABC",本文都列了?

如有不一致 → 立即修正,不要拖到 stage 5 才发现。

### Step 6: 输出 (5 min)

写入 `decision_log.stages.4`:
```json
{
  "assumptions": [
    {"id": "A1", "content": "...", "support": "...", "support_type": "literature|data|physical|business|test", "status": "verified|provisional|rejected", "impact": "..."},
    ...
  ],
  "symbols": [
    {"symbol": "x_i", "meaning": "...", "unit": "...", "type": "decision|parameter|state|random", "range": "..."},
    ...
  ],
  "terminology": [
    {"zh": "...", "en": "...", "abbrev": "...", "first_appearance": "§5.1"}
  ],
  "consistency_check": {"with_stage2": "pass", "with_stage3": "pass"}
}
```

---

## L1 Rubric

| 维度 | 满分行为 |
|------|---------|
| 1. 假设必要性 | 每条都对应实际模型依赖，无同义凑数项 |
| 2. 假设支撑 | 每条必须有 |
| 3. 符号唯一性 | 无重复 + 全有单位 |
| 4. 与模型一致性 | 与 stage 3 无矛盾 |
| 5. 术语规范 | 正文中可能歧义的术语均已定义；无未使用术语 |

## 常见坑

- B1 假设无支撑 → Step 2 强制
- B2/B3 假设过多/过少 → 以模型依赖和证据状态审查，不设数量门槛
- B4 符号重复 → Step 3 自动检
- B5 无单位 → Step 3 自动检
- 与 stage 5 不一致 → Step 5 预检 + L2 后续回检

## 退出条件

1. 所有必要假设都有证据，或标记 provisional 且已有验证/回退计划
2. 符号表覆盖后续实际使用的全部符号，全有单位与类型且无凑数项
3. 正文实际使用且可能歧义的术语均已定义 (若适用)
4. 一致性预检通过
5. L1 全维 ≥7

→ 跳转 `stage_05_subproblem_loop.md`

---

## 与 stage 5/8 的衔接

stage 5 建模时,任何用到的符号必须先在本文表中。
stage 8 写论文 §3 §4 时,直接复用本文产出；若需参考经验模式，按竞赛读取 `competitions/<comp>/winning_patterns.md` 并核验其证据边界。
