---
stage: 0
name: kickoff
duration_h: 1
inputs:
  - "user_inputs.{competition, problem_id, team_size, deadline, pdf_path}"
outputs:
  - "stage.0.{team_roles, tools_ready, problem_scan, time_budget_h, collab_protocol, checklist_completed}"
  - "root.{competition, task_type}"
loads_reference:
  - "competitions/<comp>/current_rules.md"
  - "competitions/<comp>/topic_specs.json"
  - "competitions/<comp>/README.md"
loads_template:
  - "templates/shared/decision_log.json"
  - "templates/shared/requirements.txt"
feedback: ["L1"]
next: "stage_01_problem_selection | wait_for_prompt"
---

> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。


# Stage 0 — 团队启动与资料预扫

**时长**: 1h | **反馈层**: L1 | **触发**: skill 首次启动 / 用户说"开始建模"

---

## 目标

在题目正式公布前(或公布后立即),把队伍状态调到"上手即可执行",避免后续阶段因协作/工具/角色问题反复返工。

---

## 输入

- 用户提供: 队员数 (默认 3) / 截止时间 / 模式偏好
- (若题目已发布) 题目 PDF 文件路径

## 产出

- `state/decision_log.json` 初始化,问题元信息填好
- 角色分工表 (写入 `decision_log.stages.0.team_roles`)
- 工具就绪 checklist
- 初步问题域识别 (优化 / 预测 / 评价 / 分类 / 仿真 / 综合) → 影响 stage 3

---

## 操作流程

### Step 1: 从题面与现有项目提取元信息

首次完整使用按 [功能发现与首次体验](feature_guidance.md) 简短介绍工作方式，再直接处理题目。项目就绪后有条件展示只读建模工作台，展示失败不阻断审题；局部问答与技能维护不套用首次项目引导。首次介绍、页面复用及后续按需提示以该文件为准，不另建一份欢迎菜单。

先合并当前用户消息、题面和已有 state。用户只给题目时，直接完成资料读取与全题初步分析；不能把下面的信息清单变成必须逐项回复的问卷。只合并询问真正阻塞当前工作的缺口，普通练习中队员姓名、截止时间等可先保留未知：

1. **竞赛** — 从题面核对 cumcm / mcm / diangong；无法确认时使用 generic，不默认冒认国赛
2. **题号** — 依竞赛动态生成选项 (cumcm A-E / mcm A-F / diangong A-B / `未公布`)
3. **队员数与各人擅长** — 自由文本 (例: "3 人, 张建模, 李编程, 王写作")
4. **截止时间** — 自由文本 (ISO 字符串或 "距现在 X 小时")
5. **题目 PDF 路径** — 自由文本 ("未公布"亦可)

**禁止**让用户手动编辑 decision_log.json; 拿到答案后由 agent 自动写入。

写入:
- `decision_log.competition` ← 第 1 问
- `decision_log.problem_meta.{year, letter, title, deadline_iso, team_size}` ← 第 2-4 问
- `decision_log.events.log` ← 第 5 问 (PDF 路径)

先读取 `competitions/<comp>/current_rules.md`，再打开其中的官方来源复核当年规则；仓库内经验值不能覆盖官方通知。Stage 0 不预加载 `winning_patterns.md`：只有后续阶段需要某条经验模式、且能追溯其适用证据时才按需读取，避免把历史启发式误当成当年规则。

**自动推断** (基于 competition 字段, 加载 `competitions/<comp>/README.md` 与 `topic_specs.json`):
- 时长预算 (cumcm 72h / mcm 96h / diangong 72h)
- 写作语言 (cumcm/diangong 中文 / mcm 英文)
- LaTeX 编译器 (cumcm/diangong xelatex / mcm pdflatex)
- 题号对应的 task-type 路由候选（仅在题号真实可用后确认）

题面未公布或尚未读取时，`problem_scan.subproblem_count` 与 `stages.5.qi_count` 保持 `null`；不得用历史题目或 `topic_specs.json` 猜默认子问数。

`task_type` 字段在 stage 1 选定题号后再填 (`competitions/<comp>/topic_specs.json` 给出 `<letter> → task_type_key` 映射)。

### Step 2: 角色分工 (10 min)

确保以下三类职责都有明确主责与互备。队员少于三人时允许一人兼任，队员更多时可拆分；不要虚构成员或为满足表格强行一人一岗:

| 角色 | 主责内容 | 互备 |
|------|---------|------|
| **建模主** | stage 2/3/4/5 主导,数学公式 | 编程主 |
| **编程主** | stage 5 求解、stage 6 灵敏度 | 建模主 |
| **写作主** | stage 8 主导,stage 1/9 协助 | 全员 |

**反模式 J1** (`competitions/<comp>/anti_patterns.md`): "人人都负责一切，实际无人主责" — 拒绝。
队员的顾虑可在接力时补充；没有成员资料时不虚构三个人或因此阻塞初步审题。

### Step 3: 工具就绪 checklist (15 min)

先用 `host` 探针和 Python 检查当前宿主。其余依赖在选定模型或开始论文渲染时按需核对，不为审题先安装全部库。下面是对应步骤可用的检查示例，不是每道题必须跑完的启动门槛：

```bash
python --version           # ≥ 3.10

# 先运行 skill 自检；按实际竞赛替换 competition
python <skill>/scripts/doctor.py --competition cumcm --workspace .

# 模型实际需要这些包时再检查；按需选择
python -c "import numpy, scipy, sklearn, cvxpy, matplotlib, pandas, statsmodels, seaborn, SALib, pdfplumber, imblearn"

# 仅在已选模型使用该 solver 时检查；其他求解器同样按实际可用性选择
python -c "import cvxpy; assert 'GLPK_MI' in cvxpy.installed_solvers(), '需 pip install cvxopt'"

# 使用 CUMCM/电工杯 LaTeX 渲染链时检查；缺失不阻塞初步审题
xelatex --version          # CUMCM/电工杯 ctexart 模板使用 xelatex

which git
```

确实需要但缺失的依赖安装到项目独立环境；不要默认覆盖全局安装。完整依赖列表仅供选择参考：
```bash
pip install -r <skill>/templates/shared/requirements.txt
```

**目录初始化** (agent 自动执行, 不要让用户敲命令):
```bash
# 只创建、不覆盖：state 已存在时只报告 competition 与 current_stage
python <skill>/scripts/init_workspace.py --competition cumcm --workspace . \
  --problem 未公布 --team-size 3 --hours-left 72
```

脚本创建 `state/ results/ figures/ paper_workspace/ paper_output/ support_materials/`。其余已知字段由 agent 通过 `configure`、`stage-record` 等原事务入口登记，不能直接 Edit/Write 或 apply_patch 改权威 JSON。模式按用户偏好或已有自治授权选择并说明理由，不另加机械确认。

确认 (按 competition 分支):
| competition | LaTeX 模板 | 引擎 | 静态资料 |
|---|---|---|---|
| cumcm | `<skill>/templates/latex/cumcm/main.tex` | xelatex | 91 份来源记录 / 59 份可提取样本观察 |
| mcm | `<skill>/templates/latex/mcm/main.tex` | pdflatex | COMAP 2027 规则基线；经验统计 `n=0` |
| diangong | `<skill>/templates/latex/diangong/main.tex` | xelatex | 官网 2026-03-21 页面基线；经验统计 `n=0` |

### Step 4: 题目预扫 (题目公布后,15 min)

用户提供题目 PDF 后，agent 用当前 harness 可用的文件读取工具先核对题面与附件，再做快速识别；不要只读固定页数后就假定任务已完整：

输出格式:
```json
{
  "problem_id": "<year-letter from the official prompt>",
  "domain_keywords": ["<extracted keyword>"],
  "data_attachments": ["<actual attachment path and description>"],
  "subproblem_count": "<count parsed from the official prompt>",
  "primary_problem_type": "<inferred type with evidence>",
  "secondary_types": ["<only if applicable>"],
  "estimated_difficulty": "<easy|medium|hard with rationale>",
  "data_size_signal": "<actual scan result>"
}
```

写入 `decision_log.events.log`,作为 stage 1 输入。

### Step 5: 时间预算分配 (10 min)

从真实 deadline 倒推并写入 `decision_log.stages.0.time_budget_h`。题面未公布时只记录 **provisional** 总预算与以下保留项，不给 Stage 5 猜子问数量或“每问小时数”：

- 为最终装配、格式复核、支撑材料上传和不可预见故障保留明确缓冲。
- 题面公布后，根据实际子问、依赖链、数据清洗量、求解成本和当届交付要求，再分配 Stage 1–9。
- Stage 5 与 Stage 8 通常占主体，但具体比例必须来自当前题面和团队能力；验证与合规不能被压缩为零。
- MCM/ICM 的 Summary Sheet、问题特定交付物与 AI 报告，电工杯的封面/摘要页，以及 CUMCM 的 AI 披露材料都要进入真实预算。
- 剩余时间不足时，列出会牺牲的验证或表达范围，让用户确认取舍，不假装仍能完成完整流程。

### Step 6: 协作约定 (5 min)

写入 `decision_log.stages.0.notes`:
- 命名规范: 文件 / 变量 / Python 模块
- 版本控制: 由团队按产物边界约定提交/检查点节奏
- 沟通节奏: 由 deadline 与并行任务决定；每次同步必须包含阻断项和交接产物
- 求助升级: 为当前赛程约定明确触发条件，不使用脱离任务风险的固定时长

---

## L1 Rubric (5 维 × 1-10)

参考 `rubrics.md` Stage 0 节。每维必须 ≥7 才通过。

```json
{
  "stage_id": 0,
  "scores": {
    "1_role_clarity": {...},
    "2_tools_ready": {...},
    "3_time_planning": {...},
    "4_problem_scan": {...},
    "5_collab_protocol": {...}
  }
}
```

## 常见坑 (anti_patterns)

- **J1**: 三人都全栈不深 → 强制角色主责
- **J2**: 选题摇摆 (跳到 stage 1 才出现)
- **J3**: 写作留到最后 → time budget 把 stage 8 提前到 day 2

## 退出条件

1. `decision_log.stages.0.checklist_completed == true`
2. 当前工作责任和所需工具已检查；未使用的工具保持未验证，不阻塞已具备条件的审题工作
3. (若题目已发布) 题目预扫完成
4. L1 rubric 全维 ≥7

分支：

- **用户已给定具体题目且可读** → 直接进入 `stage_02_analysis.md`；已有选题不再投票。
- **用户希望在多个题目中选题** → 跳转 `stage_01_problem_selection.md`。
- **题面未公布/不可读** → 写入 `current_stage=0` 与等待原因，停止内容生成并等待用户提供题面；恢复时从 Step 4 继续，不重复已完成的角色和环境准备。

---

## 与 Stage 1 的衔接

仅在 Step 4 已完成时，把题目预扫 JSON 作为 Stage 1 的上下文输入，避免重新读题。没有题面时不得伪造预扫或进入选题。
