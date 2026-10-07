# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Shared mode, scope and task identity policy; no file or network side effects."""
from __future__ import annotations

from typing import Any, Mapping
import re

EVALUATION_MODES = ("formal_contest", "historical_benchmark", "open_research")
TASK_SCOPES = ("full_workflow", "subtask")


def value(state: Any, name: str, default: Any = None) -> Any:
    return state.get(name, default) if isinstance(state, Mapping) else getattr(state, name, default)


def mode_of(state: Any) -> str:
    mode = value(state, "evaluation_mode", "formal_contest")
    if mode not in EVALUATION_MODES:
        raise ValueError(f"Unknown evaluation_mode: {mode}")
    return mode


def requires_human_decision(state: Any) -> bool:
    return mode_of(state) == "formal_contest"


def policy_errors(state: Any) -> list[str]:
    errors = []
    try:
        mode = mode_of(state)
    except ValueError as exc:
        return [str(exc)]
    problem_year = value(state, "problem_year", None) or value(state, "year", 0)
    rules_year = value(state, "rules_year", None) or value(state, "year", 0)
    if value(state, "year", problem_year) != problem_year:
        errors.append("year compatibility alias conflicts with problem_year")
    if not isinstance(problem_year, int) or problem_year <= 0:
        errors.append("problem_year must be a positive year")
    if not isinstance(rules_year, int) or rules_year <= 0:
        errors.append("rules_year must be a positive year")
    if mode == "formal_contest" and problem_year != rules_year:
        errors.append("正式比赛的 problem_year 与 rules_year 必须同届")
    if value(state, "task_scope", "full_workflow") not in TASK_SCOPES:
        errors.append("Unknown task_scope")
    return errors


def result_status(state: Any, passed: bool, *, scoped: bool = False) -> str:
    if not passed:
        return "NOT_READY"
    if scoped:
        return "TASK_COMPLETE"
    return "READY" if requires_human_decision(state) else "BENCHMARK_COMPLETE"


def resolve_source_mode(state: Any, requested: str | None = None) -> str:
    """A local subtask cannot downgrade its project's source restrictions."""
    mode = mode_of(state)
    expected = {"formal_contest": "live_contest", "historical_benchmark": "practice",
                "open_research": "post_contest"}[mode]
    if requested is None:
        return expected
    if requested not in {"live_contest", "practice", "post_contest"}:
        raise ValueError("Unknown literature source mode")
    if mode == "formal_contest" and requested != "live_contest":
        raise ValueError("正式比赛不能通过局部检索参数降低来源限制")
    if mode == "historical_benchmark" and requested == "post_contest" and not value(state, "source_exposures", {}):
        raise ValueError("历史盲测须先冻结基线并登记曝光，才能进行赛后对照")
    return requested


def recovery_context_errors(context: Any) -> list[str]:
    errors = []
    if value(context, "stage", "") == "closed":
        errors.append("project_closed")
    task = value(context, "active_task", {}) or {}
    project_id = value(context, "project_id", "")
    expected = value(context, "expected_project_id", "")
    if expected and expected != project_id:
        errors.append("project_identity_mismatch")
    if task.get("project_id") and task["project_id"] != project_id:
        errors.append("task_project_mismatch")
    if task.get("status") == "closed":
        errors.append("task_closed")
    if value(context, "context_ambiguous", False):
        errors.append("ambiguous_task_identity")
    return errors


def visual_reviewer_errors(state: Any, record: Mapping[str, Any]) -> list[str]:
    """An evaluation review must not be relabelled as a team review."""
    inspector = str(record.get('inspector', ''))
    recorded_mode = record.get('evaluation_mode', 'formal_contest')
    if recorded_mode not in EVALUATION_MODES:
        return ['Unknown visual review evaluation_mode']
    if requires_human_decision(state) and recorded_mode != 'formal_contest':
        return ['正式比赛不能复用历史代理视觉复核']
    if re.fullmatch(r'member_[1-9][0-9]*', inspector):
        return []
    if (not requires_human_decision(state) and inspector == 'agent_evaluator'
            and recorded_mode == mode_of(state) and record.get('review_origin') == 'agent_evaluation'):
        return []
    return ['视觉 QA inspector 必须为真实 member_N；非正式评测可显式登记 agent_evaluator']
