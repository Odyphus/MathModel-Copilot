"""
score_artifact.py — L1 Critic 输出后的本地处理脚本 (v3.1 三竞赛版)

功能:
1. 读取 critique JSON
2. 验证 schema (5 维 + verdict + dim key 白名单, 含竞赛 overlay)
3. 决定下一步: block / pass_early / pass / pass_with_review / refine / refine_partial / carryover
4. 写入 <cwd>/state/decision_log.scores
5. 格式化并打印 empirical 比较（不修改 critique）
6. 题型 dim 权重 (task_type weighting)
7. Stage 5 per-Qi 加权聚合 (compute_stage5_verdict)

路径协议:
- decision_log: 默认 <cwd>/state/decision_log.json, 可用 MATHMODEL_STATE_DIR (兼容老 CUMCM_STATE_DIR) 或 --decision-log 覆盖
- competition: 默认从 decision_log.competition 读, 缺失则 cumcm; 可用 --competition 或 MATHMODEL_COMPETITION env 覆盖
- task_type: 默认从 decision_log.task_type 读, null 则 default 全 1.0; 可用 --task-type 覆盖

用法:
    python scripts/score_artifact.py --stage 1 --critique state/critique_v0.json
    python scripts/score_artifact.py --competition mcm --task-type A_continuous --stage 3 --critique c.json
    # stage 5 per-Qi 评分:
    python scripts/score_artifact.py --stage 5 --variant per_qi --qi-id Q1 --critique critique_q1_v0.json
    # stage 5 多 Qi 聚合:
    python scripts/score_artifact.py --stage 5 --mode aggregate_qi --qi-results qi_results.json
"""

import json
import os
import argparse
import math
import re
import sys
import copy
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from copilot_store import Store, atomic_write as _atomic_write_json

VALID_VERDICTS = {
    "block", "pass_early", "pass", "pass_with_review",
    "refine", "refine_partial", "carryover"
}

VALID_VARIANTS = {"stage_level", "per_qi"}
COMPETITIONS = {"cumcm", "mcm", "diangong"}

# Baseline DIM_WHITELIST (cumcm-flavored; 其他竞赛通过 rubric_overlay.json dim_whitelist 覆盖)
DIM_WHITELIST = {
    0: {"1_role_clarity", "2_tools_ready", "3_time_planning", "4_problem_scan", "5_collab_protocol"},
    1: {"1_three_options_depth", "2_team_strength_match", "3_risk_identification",
        "4_time_feasibility", "5_decision_record_quality"},
    2: {"1_subproblem_decomposition", "2_key_variables_count", "3_math_skeleton_present",
        "4_data_alignment", "5_subproblem_dependency_identified"},
    3: {"1_candidate_diversity", "2_selection_rationale", "3_naming_variant",
        "4_solver_feasibility", "5_literature_support"},
    4: {"1_assumption_count", "2_assumption_support", "3_symbol_uniqueness",
        "4_consistency_with_model", "5_terminology_standard"},
    5: {"1_subproblem_completeness", "2_cross_reference_chain", "3_symbol_consistency",
        "4_visual_density", "5_time_budget"},
    "5_per_qi": {"1_problem_fit", "2_math_rigor", "3_solve_correctness",
                 "4_visualization", "5_physical_meaning"},
    6: {"1_multivariate_perturbation", "2_perturbation_realism", "3_output_completeness",
        "4_robust_interval_quantitative", "5_failure_warning"},
    7: {"1_strengths_specific", "2_weaknesses_real", "3_improvements_actionable",
        "4_generalization_concrete", "5_self_critique_credibility"},
    8: {"1_abstract_5_paragraph", "2_section_completeness", "3_formulas_figures_citations",
        "4_language_quality", "5_visual_consistency"},
    9: {"1_anti_pattern_coverage", "2_visual_polish", "3_panel_consensus",
        "4_bottleneck_addressed", "5_pdf_compile_clean"},
}

WEIGHT_CLAMP_MIN = 0.7
WEIGHT_CLAMP_MAX = 1.5

# 路径解析使用 skill 根目录, 因为 competitions/ 与 config/ 都在 skill 内
_SKILL_ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
# 路径与配置加载
# ============================================================================

def resolve_decision_log_path(cli_arg: str = None) -> Path:
    """路径解析协议: CLI > MATHMODEL_STATE_DIR > CUMCM_STATE_DIR (兼容) > <cwd>/state/decision_log.json"""
    if cli_arg:
        return Path(cli_arg)
    env_dir = os.environ.get("MATHMODEL_STATE_DIR") or os.environ.get("CUMCM_STATE_DIR")
    if env_dir:
        return Path(env_dir) / "decision_log.json"
    return Path.cwd() / "state" / "decision_log.json"


def resolve_competition(cli_arg: str = None, decision_log: dict = None) -> str:
    """优先级: CLI > env MATHMODEL_COMPETITION > decision_log.competition > 'cumcm'"""
    if cli_arg:
        return cli_arg
    env = os.environ.get("MATHMODEL_COMPETITION")
    if env:
        return env
    if decision_log and decision_log.get("competition"):
        return decision_log["competition"]
    return "cumcm"


def resolve_task_type(cli_arg: str = None, decision_log: dict = None) -> str:
    """优先级: CLI > decision_log.task_type > 'default'"""
    if cli_arg:
        return cli_arg
    if decision_log and decision_log.get("task_type"):
        return decision_log["task_type"]
    return "default"


def load_rubric_overlay(competition: str) -> dict:
    """加载 competitions/<comp>/rubric_overlay.json. 缺失返回空 dict."""
    path = _SKILL_ROOT / "competitions" / competition / "rubric_overlay.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_empirical(competition: str) -> dict:
    """加载 competitions/<comp>/empirical.json. 缺失返回空 dict."""
    path = _SKILL_ROOT / "competitions" / competition / "empirical.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dim_weights_table(competition: str, task_type: str) -> dict:
    """
    加载 config/dim_weights.json 中 (competition, task_type) 的 stage→dim→weight 表.
    fallback 链: task_type → competition.default → 全 1.0.
    返回 {stage_str: {dim_name: weight}} (stage_str = "3" / "5" / "8" 等).
    """
    path = _SKILL_ROOT / "config" / "dim_weights.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        table = json.load(f)
    comp_table = table.get(competition, {})
    if not comp_table:
        return {}
    # default 是竞赛级基线; 题型配置按 stage / dim 深合并后覆盖。
    # 旧实现整块替换 default, 会让 A/B/... 题型静默丢失竞赛通用权重。
    default_weights = {
        stage: dims for stage, dims in comp_table.get("default", {}).items()
        if not stage.startswith("_")
    }
    specific_weights = {
        stage: dims for stage, dims in comp_table.get(task_type, {}).items()
        if not stage.startswith("_")
    }
    merged = {
        stage: dict(dims) for stage, dims in default_weights.items()
        if isinstance(dims, dict)
    }
    for stage, dims in specific_weights.items():
        if not isinstance(dims, dict):
            continue
        merged.setdefault(stage, {}).update(dims)
    return merged


def load_dim_whitelist(competition: str, stage_id, variant: str = "stage_level") -> set:
    """
    加载竞赛特化 dim_whitelist; 缺失则 fallback 到 baseline DIM_WHITELIST.
    stage_id 可以是 int 或 str (如 "5_per_qi").
    """
    wl_key = "5_per_qi" if (stage_id == 5 and variant == "per_qi") else stage_id
    overlay = load_rubric_overlay(competition)
    overlay_wl = overlay.get("dim_whitelist", {})
    # JSON 中 key 是 str
    overlay_dims = overlay_wl.get(str(wl_key))
    if overlay_dims:
        return set(overlay_dims)
    return DIM_WHITELIST.get(wl_key, set())


def load_competition_config(competition: str, task_type: str = "default") -> dict:
    """聚合加载: overlay + empirical + dim weights table"""
    return {
        "competition": competition,
        "task_type": task_type,
        "overlay": load_rubric_overlay(competition),
        "empirical": load_empirical(competition),
        "weights": load_dim_weights_table(competition, task_type),
    }


# ============================================================================
# 评分核心: 实测注入 / 题型加权 / per-Qi 聚合
# ============================================================================

def inject_evidence(dim_key: str, value: float, empirical: dict, by_topic: str = None) -> str:
    """
    格式化 empirical p25/p50/p75 比较文本，仅供 CLI 打印，不修改 critique.
    dim_key: empirical.json dims 字段的 key (如 abstract_chars / formula_count)
    value: 当前实测值
    by_topic: 若提供 (e.g. "A"), 优先用 empirical.by_topic[A][dim_key]

    Returns:
        "value=720, p50=992, IQR=[748, 1146], status=低于 p25" 形式
    """
    if not empirical:
        return f"value={value} [empirical 数据缺失]"

    # 优先 by_topic, 缺失则 dims (整体)
    dim_data = None
    if by_topic and "by_topic" in empirical:
        dim_data = empirical.get("by_topic", {}).get(by_topic, {}).get(dim_key)
    if dim_data is None:
        dim_data = empirical.get("dims", {}).get(dim_key)

    if dim_data is None:
        return f"value={value} [{dim_key} 不在 empirical 字段]"

    p25, p50, p75 = dim_data.get("p25"), dim_data.get("p50"), dim_data.get("p75")
    if p25 is None or p75 is None:
        return f"value={value} [empirical 分位缺失]"

    if value > p75:
        status = "高于 p75"
    elif value < p25:
        status = "低于 p25"
    else:
        status = "IQR 内"

    return (f"value={value}, p50={p50}, IQR=[{p25}, {p75}]"
            f"{' (by topic ' + by_topic + ')' if by_topic else ''}, status={status}")


def apply_dim_weights(scores: dict, weights_for_stage: dict) -> dict:
    """
    weighted_score[dim] = clamp(weight, [WEIGHT_CLAMP_MIN, WEIGHT_CLAMP_MAX]).
    返回 {dim: weight} (1.0 if not in table); 给 compute_verdict 用.

    分离 weight 与 score 是为了:
    - 加权 mean = sum(score * weight) / sum(weight)
    - 加权 min = min(score) (不加权, 仍用作 'any dim too low' 触发)
    """
    out = {}
    for dim_name in scores:
        w = weights_for_stage.get(dim_name, 1.0)
        w_clamped = max(WEIGHT_CLAMP_MIN, min(WEIGHT_CLAMP_MAX, w))
        out[dim_name] = w_clamped
    return out


def summarize_scores(scores: dict, weights_for_stage: dict = None) -> dict:
    """Return one canonical score summary used by validation, verdicts, and logs."""
    score_values = {k: d["score"] for k, d in scores.items()}
    raw_min = min(score_values.values())
    raw_mean = sum(score_values.values()) / len(score_values)

    w_table = apply_dim_weights(score_values, weights_for_stage or {})
    weight_total = sum(w_table.values())
    weighted_mean = (
        sum(score_values[d] * w_table[d] for d in score_values) / weight_total
        if weight_total else raw_mean
    )
    return {
        "raw_min": raw_min,
        "raw_mean": raw_mean,
        "weighted_mean": weighted_mean,
        "weights": w_table,
    }


def compute_verdict(critique: dict, weights_for_stage: dict = None) -> str:
    """
    根据分数与 issues 重算 verdict (覆盖 critic 的 verdict 字段, 防 gaming).
    优先级 (高→低): block > pass_early > pass > refine
    支持题型 dim 权重 (weights_for_stage; None = 全 1.0).

    与 SKILL.md / feedback_layer1_critic.md 三处一致.
    """
    summary = summarize_scores(critique["scores"], weights_for_stage)
    raw_min = summary["raw_min"]
    weighted_mean = summary["weighted_mean"]

    high_issues = [i for i in critique["issues"] if i.get("severity") == "high"]

    if len(high_issues) >= 1:
        return "block"
    if raw_min >= 9 and weighted_mean >= 9:
        return "pass_early"
    if raw_min >= 7 and weighted_mean >= 8:
        return "pass"
    return "refine"


def compute_stage5_verdict(qi_results: list, qi_weights: list = None) -> dict:
    """
    Stage 5 per-Qi 加权聚合.
    qi_results: [{qi: 'Q1', min: int, mean: float, scores: {...}, issues: [...]}]
    qi_weights: [1.0, 1.0, 1.0]; None → 均匀

    Returns:
        {
          "verdict": "block" | "pass" | "pass_with_review" | "refine_partial" | "refine",
          "weighted_min": int,  # min over Qi.min
          "weighted_mean": float,
          "qi_status": {"Q1": "pass"|"mark_for_review"|"refine"|"block", ...},
          "review_qis": [...],  # mark_for_review 的 Qi
          "refine_qis": [...],  # 需要重做的 Qi (min < 7)
          "block_qis": [...]    # 含 high-severity issue 的 Qi
        }
    """
    if not isinstance(qi_results, list) or not qi_results:
        raise ValueError("qi_results 必须是至少包含一个子问的数组")

    n = len(qi_results)
    seen_qis = set()
    for index, qi in enumerate(qi_results):
        if not isinstance(qi, dict):
            raise ValueError(f"qi_results[{index}] 必须是 JSON object")
        qi_id = qi.get("qi")
        if not isinstance(qi_id, str) or not re.fullmatch(r"Q[1-9][0-9]*", qi_id):
            raise ValueError(f"qi_results[{index}].qi 必须形如 Q1/Q2")
        if qi_id in seen_qis:
            raise ValueError(f"qi_results 出现重复子问: {qi_id}")
        seen_qis.add(qi_id)
        for field in ("min", "mean"):
            value = qi.get(field)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or not (1 <= value <= 10)):
                raise ValueError(f"qi_results[{index}].{field} 必须是 [1,10] 数值")
        if qi["min"] > qi["mean"]:
            raise ValueError(f"qi_results[{index}].min 不能大于 mean")

        issues = qi.get("issues")
        if not isinstance(issues, list):
            raise ValueError(
                f"qi_results[{index}].issues 必须是 list；聚合不能丢弃子问问题"
            )
        if len(issues) > 5:
            raise ValueError(f"qi_results[{index}].issues 最多包含 5 项")
        for issue_index, issue in enumerate(issues):
            if not isinstance(issue, dict):
                raise ValueError(
                    f"qi_results[{index}].issues[{issue_index}] 必须是 object"
                )
            if issue.get("severity") not in {"high", "medium", "low"}:
                raise ValueError(
                    f"qi_results[{index}].issues[{issue_index}].severity 无效"
                )
            for field in ("where", "fix"):
                if not isinstance(issue.get(field), str) or not issue[field].strip():
                    raise ValueError(
                        f"qi_results[{index}].issues[{issue_index}].{field} "
                        "必须是非空字符串"
                    )

        scores = qi.get("scores")
        if scores is not None:
            if not isinstance(scores, dict) or len(scores) != 5:
                raise ValueError(f"qi_results[{index}].scores 必须是 5 维 object")
            score_values = []
            for dim_name, dim in scores.items():
                if not isinstance(dim, dict) or "score" not in dim:
                    raise ValueError(
                        f"qi_results[{index}].scores.{dim_name} 缺少 score"
                    )
                score = dim["score"]
                if (not isinstance(score, (int, float)) or isinstance(score, bool)
                        or not math.isfinite(score) or not (1 <= score <= 10)):
                    raise ValueError(
                        f"qi_results[{index}].scores.{dim_name}.score 必须是 [1,10] 数值"
                    )
                score_values.append(score)
            computed_min = min(score_values)
            computed_mean = sum(score_values) / len(score_values)
            if qi["min"] != computed_min:
                raise ValueError(
                    f"qi_results[{index}].min 与 scores 不一致: "
                    f"reported={qi['min']}, computed={computed_min}"
                )
            if abs(qi["mean"] - computed_mean) > 0.02:
                raise ValueError(
                    f"qi_results[{index}].mean 与 scores 不一致: "
                    f"reported={qi['mean']}, computed={computed_mean:.2f}"
                )

    canonical_ids = sorted(seen_qis, key=lambda key: int(key[1:]))
    if qi_weights is None:
        weight_map = {key: 1.0 for key in canonical_ids}
    elif isinstance(qi_weights, dict):
        if set(qi_weights) != set(canonical_ids):
            raise ValueError("qi_weights 必须按 Qi ID 覆盖全部聚合子问")
        weight_map = dict(qi_weights)
    elif not isinstance(qi_weights, list) or len(qi_weights) != n:
        raise ValueError(f"qi_weights 长度必须等于 qi_results 长度 {n}")
    else:
        # Legacy arrays always mean Q1, Q2, ... numeric ID order, not input order.
        weight_map = dict(zip(canonical_ids, qi_weights))
    if any(
        not isinstance(w, (int, float))
        or isinstance(w, bool)
        or not math.isfinite(w)
        or w <= 0
        for w in weight_map.values()
    ):
        raise ValueError("qi_weights 必须全部是有限正数")

    qi_status = {}
    for qi in qi_results:
        if any(issue.get("severity") == "high" for issue in qi["issues"]):
            qi_status[qi["qi"]] = "block"
        elif qi["min"] >= 7 and qi["mean"] >= 8:
            qi_status[qi["qi"]] = "pass"
        elif qi["min"] >= 7:
            qi_status[qi["qi"]] = "mark_for_review"
        else:
            qi_status[qi["qi"]] = "refine"

    weight_total = sum(weight_map.values())
    weighted_mean = sum(q["mean"] * weight_map[q["qi"]] for q in qi_results) / weight_total
    weighted_min = min(q["min"] for q in qi_results)

    review_qis = [q for q, s in qi_status.items() if s == "mark_for_review"]
    refine_qis = [q for q, s in qi_status.items() if s == "refine"]
    block_qis = [q for q, s in qi_status.items() if s == "block"]

    if block_qis:
        verdict = "block"
    elif refine_qis:
        # 只有部分 Qi 失败时才定向回修；全部失败说明基础或共享链路有问题。
        verdict = "refine_partial" if len(refine_qis) < n else "refine"
    elif review_qis:
        if weighted_min >= 7 and weighted_mean >= 8:
            verdict = "pass_with_review"
        else:
            verdict = "refine"
    else:
        # 全 Qi pass
        if weighted_min >= 9 and weighted_mean >= 9:
            verdict = "pass_early"
        elif weighted_min >= 7 and weighted_mean >= 8:
            verdict = "pass"
        else:
            verdict = "refine"

    return {
        "verdict": verdict,
        "weighted_min": weighted_min,
        "weighted_mean": round(weighted_mean, 2),
        "qi_status": qi_status,
        "review_qis": review_qis,
        "refine_qis": refine_qis,
        "block_qis": block_qis,
        "qi_weights": [weight_map[key] for key in canonical_ids],
        "qi_weight_map": weight_map,
    }


# ============================================================================
# Schema 校验
# ============================================================================

def resolve_whitelist_key(stage_id: int, variant: str):
    if stage_id == 5 and variant == "per_qi":
        return "5_per_qi"
    return stage_id


def validate_critique(critique: dict, stage_id: int, competition: str = "cumcm",
                      variant: str = "stage_level") -> tuple[bool, str]:
    """
    验证 critique JSON 是否符合 L1 schema, 含竞赛 overlay-aware 的 dim key 白名单
    """
    if not isinstance(critique, dict):
        return False, "critique 根节点必须是 object"

    required_keys = {"stage_id", "iteration", "scores", "min_score",
                     "mean_score", "issues", "verdict"}
    missing = required_keys - critique.keys()
    if missing:
        return False, f"缺少 keys: {missing}"

    if (not isinstance(critique["stage_id"], int)
            or isinstance(critique["stage_id"], bool)
            or critique["stage_id"] != stage_id):
        return False, f"stage_id 不一致: critique={critique['stage_id']}, CLI={stage_id}"

    if (not isinstance(critique["iteration"], int)
            or isinstance(critique["iteration"], bool)
            or critique["iteration"] < 0):
        return False, "iteration 必须是非负整数"

    if critique["verdict"] not in VALID_VERDICTS:
        return False, f"verdict 必须 ∈ {VALID_VERDICTS}, 实际: {critique['verdict']}"

    if variant not in VALID_VARIANTS:
        return False, f"variant 必须 ∈ {VALID_VARIANTS}, 实际: {variant}"

    if variant == "per_qi" and stage_id != 5:
        return False, f"variant=per_qi 仅适用于 stage 5, 实际 stage {stage_id}"

    if not isinstance(critique["scores"], dict) or len(critique["scores"]) != 5:
        return False, "scores 必须是 5 维 dict"

    expected_dims = load_dim_whitelist(competition, stage_id, variant)
    if not expected_dims:
        return False, f"未知 stage_id: {stage_id} (competition={competition}, variant={variant})"
    actual_dims = set(critique["scores"].keys())
    if actual_dims != expected_dims:
        unexpected = actual_dims - expected_dims
        missing_dims = expected_dims - actual_dims
        msg = f"dim key 不匹配 (competition {competition}, stage {stage_id}, variant {variant}). "
        if unexpected:
            msg += f"未预期 keys: {unexpected}. "
        if missing_dims:
            msg += f"缺失 keys: {missing_dims}."
        return False, msg

    for dim_name, dim in critique["scores"].items():
        if not isinstance(dim, dict) or "score" not in dim:
            return False, f"scores.{dim_name} 缺 score 字段"
        if (not isinstance(dim["score"], (int, float))
                or isinstance(dim["score"], bool)
                or not (1 <= dim["score"] <= 10)):
            return False, f"scores.{dim_name}.score 超出 [1,10]"
        if not isinstance(dim.get("evidence"), str) or not dim["evidence"].strip():
            return False, f"scores.{dim_name}.evidence 必须是非空字符串"

    summary = summarize_scores(critique["scores"])
    if (not isinstance(critique["min_score"], (int, float))
            or isinstance(critique["min_score"], bool)
            or critique["min_score"] != summary["raw_min"]):
        return False, (
            f"min_score 与 scores 不一致: reported={critique['min_score']}, "
            f"computed={summary['raw_min']}"
        )
    if (not isinstance(critique["mean_score"], (int, float))
            or isinstance(critique["mean_score"], bool)
            or not math.isfinite(critique["mean_score"])
            or abs(critique["mean_score"] - summary["raw_mean"]) > 0.02):
        return False, (
            f"mean_score 与 scores 不一致: reported={critique['mean_score']}, "
            f"computed={summary['raw_mean']:.2f}"
        )

    if not isinstance(critique["issues"], list):
        return False, "issues 必须是 list"
    if len(critique["issues"]) > 5:
        return False, f"issues 长度 {len(critique['issues'])} > 5, 应回 stage 重做而非精修"
    for index, issue in enumerate(critique["issues"]):
        if not isinstance(issue, dict):
            return False, f"issues[{index}] 必须是 object"
        if issue.get("severity") not in {"high", "medium", "low"}:
            return False, f"issues[{index}].severity 必须是 high/medium/low"
        for field in ("where", "fix"):
            if not isinstance(issue.get(field), str) or not issue[field].strip():
                return False, f"issues[{index}].{field} 必须是非空字符串"
        anti_pattern_id = issue.get("anti_pattern_id")
        if (anti_pattern_id is not None
                and (not isinstance(anti_pattern_id, str)
                     or not re.fullmatch(r"[A-Z][0-9]+", anti_pattern_id))):
            return False, f"issues[{index}].anti_pattern_id 必须形如 A1 或为 null"

    return True, "ok"


# ============================================================================
# decision_log 写入
# ============================================================================

def update_decision_log(stage_id: int, critique: dict, decision_log_path: Path,
                        variant: str = "stage_level", qi_id: str = None,
                        weighted_mean: float = None, extra: dict = None,
                        expected_revision: int = None, max_iter: int = 3,
                        competition: str = None, task_type: str = None):
    """
    把 critique 写入 decision_log.scores[stage_key]
    - stage_level: stage_key = str(stage_id)
    - per_qi:      stage_key = "5_per_qi", entry 含 qi_id 字段
    - extra:       附加字段 (e.g., review_qis, refine_qis from compute_stage5_verdict)
    """
    if not decision_log_path.exists():
        raise FileNotFoundError(
            f"{decision_log_path} 不存在。"
            f"请先 stage 0 初始化 (cp <skill>/templates/shared/decision_log.json {decision_log_path})"
        )

    store = Store(decision_log_path)
    if expected_revision is None:
        expected_revision = store.read().get("copilot", {}).get("revision", 0)

    def mutate(log):
        selected = competition or log.get("competition", "cumcm")
        ok, message = validate_critique(critique, stage_id, selected, variant)
        if not ok:
            raise ValueError(message)
        if variant == "per_qi":
            if not isinstance(qi_id, str) or not re.fullmatch(r"Q[1-9][0-9]*", qi_id):
                raise ValueError("per_qi 必须指定有效 Qi ID")
            expected = expected_question_ids(log, required=False)
            if expected and qi_id not in expected:
                raise ValueError(f"{qi_id} 不属于当前题目的预期子问")
        weights = load_dim_weights_table(selected, task_type or log.get("task_type") or "default")
        stage_weights = {k: v for k, v in weights.get(str(stage_id), {}).items() if not k.startswith("_")}
        canonical = copy.deepcopy(critique)
        decide_next_action(canonical, max_iter, stage_weights)
        stage_key = "5_per_qi" if variant == "per_qi" else str(stage_id)
        entry = {
            "iteration": canonical["iteration"],
            "scores": {k: v["score"] for k, v in canonical["scores"].items()},
            "min": canonical["min_score"], "mean": canonical["mean_score"],
            "verdict": canonical["verdict"], "issues": canonical["issues"],
            "ts": datetime.now().isoformat(), "evidence_status": "review_only",
        }
        if variant == "per_qi":
            entry["qi_id"] = qi_id
            aggregate = log["stages"].setdefault("5", {}).get("aggregate")
            if isinstance(aggregate, dict) and aggregate.get("complete"):
                aggregate.update(complete=False, verdict="stale", invalidated_by=f"new review for {qi_id}")
        if stage_weights:
            entry["weighted_mean"] = round(summarize_scores(canonical["scores"], stage_weights)["weighted_mean"], 2)
        if extra:
            entry.update({k: v for k, v in extra.items() if k not in entry})
        log["scores"].setdefault(stage_key, []).append(entry)
        log["iterations"][stage_key] = max(log["iterations"].get(stage_key, 0), canonical["iteration"] + 1)
        return entry

    return store.transact(expected_revision, "score_artifact", f"review Stage {stage_id}", mutate)


def read_decision_log(decision_log_path: Path) -> dict:
    """读 decision_log; 不存在返回空 dict 不抛错 (用于 resolve_competition)"""
    if not decision_log_path.exists():
        return {}
    return Store(decision_log_path).read()


def expected_question_ids(log: dict, required: bool = True) -> list[str]:
    """Count confirmed from the problem includes questions without contracts yet."""
    count = log.get("stages", {}).get("5", {}).get("qi_count")
    if type(count) is int and count > 0:
        return [f"Q{index}" for index in range(1, count + 1)]
    if required:
        raise ValueError("尚未确认预期子问；请先建立 Requirement Matrix 或有效 qi_count")
    return []


def update_stage5_aggregate(result: dict, qi_results: list, qi_weights: list | None,
                            decision_log_path: Path, expected_revision: int = None) -> dict:
    """Persist the canonical per-Qi aggregate into the Stage 5 state node."""
    if not decision_log_path.exists():
        raise FileNotFoundError(
            f"{decision_log_path} 不存在。请先由 Stage 0 初始化 decision log。"
        )
    store = Store(decision_log_path)
    if expected_revision is None:
        expected_revision = store.read().get("copilot", {}).get("revision", 0)

    def mutate(log):
        expected = expected_question_ids(log)
        canonical = compute_stage5_verdict(qi_results, qi_weights)
        actual = set(canonical["qi_status"])
        if actual != set(expected):
            raise ValueError(f"完整聚合缺少子问 {sorted(set(expected) - actual)}；"
                             f"未预期子问 {sorted(actual - set(expected))}；状态未修改")
        stage5 = log["stages"].setdefault("5", {})
        for key in ("qi_status", "review_qis", "refine_qis", "block_qis"):
            stage5[key] = canonical[key]
        stage5["aggregate"] = {
            "method": "per_qi_weighted", "weighted_min": canonical["weighted_min"],
            "weighted_mean": canonical["weighted_mean"], "verdict": canonical["verdict"],
            "source_qis": expected, "complete": True, "evidence_status": "review_only",
            "ts": datetime.now().isoformat(),
        }
        stage5["qi_weights"] = canonical["qi_weights"]
        stage5["qi_weight_map"] = canonical["qi_weight_map"]
        return canonical

    return store.transact(expected_revision, "score_artifact", "aggregate all expected Qi", mutate)["result"]


# ============================================================================
# 决策
# ============================================================================

def decide_next_action(critique: dict, max_iter: int = 3,
                       weights_for_stage: dict = None) -> dict:
    """返回下一步行为"""
    actual_verdict = compute_verdict(critique, weights_for_stage)
    if actual_verdict != critique.get("verdict"):
        critique["verdict"] = actual_verdict

    iter_num = critique["iteration"]

    if actual_verdict == "block":
        return {"action": "halt", "verdict": "block",
                "reason": "critique.issues 含 high-severity, 需用户介入",
                "issues": [i for i in critique["issues"] if i.get("severity") == "high"]}
    if actual_verdict in ("pass", "pass_early", "pass_with_review"):
        return {"action": "next_stage", "verdict": actual_verdict}
    if iter_num >= max_iter:
        critique["verdict"] = "carryover"
        return {"action": "carryover", "verdict": "carryover",
                "reason": f"已迭代 {iter_num}+1 次仍未达标, 标记 carryover, L2 回检处理"}
    return {"action": "section_patch", "verdict": "refine",
            "issues": critique["issues"],
            "next_iteration": iter_num + 1}


# ============================================================================
# CLI
# ============================================================================

def cmd_aggregate_qi(args):
    """子命令: stage 5 多 Qi 聚合"""
    qi_results_path = Path(args.qi_results)
    if not qi_results_path.exists():
        print(f"[FAIL] {qi_results_path} 不存在")
        return 1

    try:
        with open(qi_results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] qi-results 不是有效 JSON: {exc}")
        return 1
    if not isinstance(data, dict):
        print("[FAIL] qi-results 根节点必须是 object")
        return 1
    qi_results = data.get("qi_results", [])
    qi_weights = data.get("qi_weights")

    try:
        result = compute_stage5_verdict(qi_results, qi_weights)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1

    decision_log_path = resolve_decision_log_path(args.decision_log)
    try:
        result = update_stage5_aggregate(result, qi_results, qi_weights, decision_log_path,
                                         expected_revision=args.expected_revision)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"[FAIL] 无法写入 Stage 5 聚合状态: {exc}")
        return 1
    print(f"Stage 5 per-Qi 聚合 (n={len(qi_results)})")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[OK] written: {decision_log_path}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, help="阶段编号 0-9 (mode=normal/aggregate_qi 必填)")
    parser.add_argument("--critique", type=str, help="critique JSON 文件路径 (mode=normal 必填)")
    parser.add_argument("--variant", choices=sorted(VALID_VARIANTS), default=None,
                        help="stage 5 区分 per-Qi vs stage-level; 默认读 critique.variant 或 stage_level")
    parser.add_argument("--qi-id", type=str, default=None,
                        help="per_qi variant 必填, e.g. Q1/Q2")
    parser.add_argument("--max-iter", type=int, default=3)
    parser.add_argument("--decision-log", type=str, default=None,
                        help="覆盖路径解析协议; 默认 <cwd>/state/decision_log.json")
    parser.add_argument("--expected-revision", type=int, default=None,
                        help="读取时的状态版本；旧版本拒绝写入，省略时先读取再 CAS")
    parser.add_argument("--competition", choices=sorted(COMPETITIONS), default=None,
                        help="cumcm | mcm | diangong (默认从 decision_log 读, 缺失则 cumcm)")
    parser.add_argument("--task-type", type=str, default=None,
                        help="题型 e.g. A_optimization (默认 default 全 1.0)")
    parser.add_argument("--mode", choices=["normal", "aggregate_qi"], default="normal",
                        help="aggregate_qi: stage 5 多 Qi 加权聚合 (需 --qi-results)")
    parser.add_argument("--qi-results", type=str,
                        help="aggregate_qi 模式: {qi_results: [...], qi_weights: [...]} JSON 文件")
    args = parser.parse_args()

    if args.mode == "aggregate_qi":
        if not args.qi_results:
            print("[FAIL] mode=aggregate_qi 需 --qi-results")
            return 1
        return cmd_aggregate_qi(args)

    # mode=normal: 单 critique 评分
    if args.stage is None or args.critique is None:
        print("[FAIL] mode=normal 需 --stage 与 --critique")
        return 1
    if args.max_iter < 0:
        print("[FAIL] --max-iter 必须是非负整数")
        return 1

    decision_log_path = resolve_decision_log_path(args.decision_log)
    try:
        decision_log = read_decision_log(decision_log_path)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] decision_log 无法读取: {exc}")
        return 1
    if not isinstance(decision_log, dict):
        print("[FAIL] decision_log 根节点必须是 object")
        return 1

    competition = resolve_competition(args.competition, decision_log)
    task_type = resolve_task_type(args.task_type, decision_log)
    if competition not in COMPETITIONS:
        print(f"[FAIL] 未知 competition: {competition!r}")
        return 1

    try:
        with open(args.critique, "r", encoding="utf-8") as f:
            critique = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] critique 无法读取: {exc}")
        return 1
    if not isinstance(critique, dict):
        print("[FAIL] critique 根节点必须是 object")
        return 1

    variant = args.variant or critique.get("variant", "stage_level")
    qi_id = args.qi_id or critique.get("qi_id")

    if variant == "per_qi":
        if not isinstance(qi_id, str) or not re.fullmatch(r"Q[1-9][0-9]*", qi_id):
            print("[FAIL] variant=per_qi 必须提供形如 Q1/Q2 的 --qi-id 或 critique.qi_id")
            return 1

    ok, msg = validate_critique(critique, args.stage, competition, variant)
    if not ok:
        print(f"[FAIL] Schema error: {msg}")
        return 1

    # 加载 dim weights 给该 stage
    weights_table = load_dim_weights_table(competition, task_type)
    weights_for_stage = weights_table.get(str(args.stage), {})
    # 过滤 _note 等元字段
    weights_for_stage = {k: v for k, v in weights_for_stage.items() if not k.startswith("_")}

    # 格式化并打印实测分位比较（不改写 critique）
    empirical = load_empirical(competition)
    if "evidence_metrics" in critique and empirical:
        topic = (decision_log.get("problem_meta", {}) or {}).get("letter")
        for metric_dim, value in critique["evidence_metrics"].items():
            evidence_str = inject_evidence(metric_dim, value, empirical, by_topic=topic)
            print(f"  [empirical] {metric_dim}: {evidence_str}")

    actual_verdict = compute_verdict(critique, weights_for_stage)
    label = f"stage {args.stage}" + (f" / {qi_id}" if variant == "per_qi" else "")
    print(f"{label}, iter {critique['iteration']}, variant {variant}, "
          f"competition {competition}, task_type {task_type}")
    print(f"  Min score: {critique['min_score']}, Mean: {critique['mean_score']:.2f}")
    if weights_for_stage:
        weighted_mean = summarize_scores(critique["scores"], weights_for_stage)["weighted_mean"]
        print(f"  Weighted mean (task_type={task_type}): {weighted_mean:.2f}")
    else:
        weighted_mean = None
    print(f"  Critic verdict: {critique['verdict']} -> Actual: {actual_verdict}")
    print(f"  decision_log: {decision_log_path}")

    # Decide before persisting: at the iteration cap, the canonical state is
    # carryover rather than the intermediate score-derived refine verdict.
    critique["verdict"] = actual_verdict
    action = decide_next_action(critique, args.max_iter, weights_for_stage)
    try:
        update_decision_log(args.stage, critique, decision_log_path,
                            variant, qi_id, weighted_mean=weighted_mean,
                            expected_revision=(args.expected_revision if args.expected_revision is not None
                                               else decision_log.get("copilot", {}).get("revision", 0)),
                            max_iter=args.max_iter, competition=competition, task_type=task_type)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"  [FAIL] 无法写入 decision_log: {exc}")
        return 1
    print(f"  [OK] written")

    print(f"\n下一步: {action['action']}")
    print(json.dumps(action, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
