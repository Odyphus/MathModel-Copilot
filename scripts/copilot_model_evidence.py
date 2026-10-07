"""Check decision-relevant evidence, not a contest-specific model recipe.

Inputs are measurements or declarations from project evidence. This checks their
consistency; it cannot certify that a declared independent experiment really was
independent. Keep that distinction in the review report.
"""
from __future__ import annotations
import math
import re
from pathlib import Path
from typing import Any, Mapping


def preprocessing_scope_errors(plan: Mapping[str, Any]) -> list[str]:
    """Check declared per-operation scope; actual code and evidence require review."""
    errors = []
    summary = re.sub(r'[_-]+', ' ', str(plan.get('preprocessing_scope', '')).lower()).strip()
    all_data = any(word in summary for word in ('full data', 'all data', '全数据', '全体数据'))
    if all_data:
        errors.append('预处理不得在切分前使用全体数据拟合')
    if 'preprocessing_steps' not in plan:
        return errors  # Compatibility: never rewrite an old frozen record.
    steps = plan['preprocessing_steps']
    if not isinstance(steps, list) or not steps:
        return errors + ['preprocessing_steps must be a nonempty list when supplied']
    scopes = set()
    for i, step in enumerate(steps):
        label = f'preprocessing_steps[{i}]'
        if not isinstance(step, Mapping):
            errors.append(f'{label} must be an operation record')
            continue
        for key in ('operation', 'code_ref'):
            if not isinstance(step.get(key), str) or not step[key].strip():
                errors.append(f'{label} requires {key}')
        refs = step.get('evidence_refs')
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or not r.strip() for r in refs):
            errors.append(f'{label} requires evidence_refs')
        kind, scope = step.get('operation_type'), step.get('fit_scope')
        if kind not in {'fixed', 'learned'}:
            errors.append(f'{label} operation_type must be fixed or learned')
        if scope not in {'none', 'train_fold_only', 'full_data'}:
            errors.append(f'{label} unknown fit_scope')
            continue
        scopes.add(scope)
        if kind == 'fixed' and scope != 'none':
            errors.append(f'{label} fixed transformations must not fit data')
        if kind == 'learned' and scope != 'train_fold_only':
            errors.append(f'{label} learned preprocessing must fit training folds only')
    expected = 'full_data' if 'full_data' in scopes else 'train_fold_only' if 'train_fold_only' in scopes else 'none'
    aliases = {'train fold only': 'train_fold_only', 'train only': 'train_fold_only',
               'fit on train only': 'train_fold_only', 'none': 'none', 'not fitted': 'none',
               'full data': 'full_data', 'all data': 'full_data'}
    actual_summary = 'full_data' if all_data else aliases.get(summary)
    if actual_summary != expected:
        errors.append(f'preprocessing_scope conflicts with operation scopes: expected {expected}')
    return errors


def temporal_split_errors(plan: Mapping[str, Any], train: set, test: set) -> list[str]:
    """Validate an explicitly limited same-entity continuation claim.

    Time ranges are inclusive numeric coordinates in time_order_field units.
    This checks the declared design; code/data bindings still need review.
    """
    errors: list[str] = []
    if plan.get('strategy') != 'temporal_holdout' or not plan.get('time_order_field'):
        errors.append('same-entity continuation requires temporal_holdout and a time field')
    if plan.get('split_unit') != plan.get('time_order_field'):
        errors.append('temporal split unit must be the declared time field')
    if not train or not test or not test <= train:
        errors.append('continuation evaluates only explicitly listed known entities')
    if plan.get('claims_new_entity_generalization') is not False or not plan.get('claim_boundary'):
        errors.append('continuation must explicitly exclude new-entity generalization')
    if plan.get('final_evaluation_reused') is not False:
        errors.append('final evaluation must not be reused for fitting or selection')
    ranges = {}
    for key in ('train_time_range', 'test_time_range', 'preprocessing_time_range', 'selection_time_range'):
        value = plan.get(key)
        if (not isinstance(value, list) or len(value) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
                or value[0] > value[1]):
            errors.append(f'{key} requires finite ordered inclusive bounds')
        else:
            ranges[key] = value
    if len(ranges) == 4:
        start, end = ranges['train_time_range']
        if end >= ranges['test_time_range'][0]:
            errors.append('training time must strictly precede held-out time')
        for key in ('preprocessing_time_range', 'selection_time_range'):
            low, high = ranges[key]
            if low < start or high > end:
                errors.append(f'{key} extends outside training time')
    return errors


def check_semantic_evidence(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(payload.get('checks', [])):
        prefix = str(row.get('id') or f'check-{i+1}')
        kind = row.get('kind')
        if kind == 'baseline':
            omitted = set(row.get('applicable_baselines', [])) - set(row.get('compared_baselines', []))
            if row.get('claims_superiority') and (omitted or not row.get('compared_baselines')):
                errors.append(f'{prefix}: superiority claim lacks applicable baseline comparison: {sorted(omitted)}')
        elif kind == 'semantic_mapping':
            if row.get('source_meaning') != row.get('target_meaning') and not row.get('validated_transformation'):
                errors.append(f'{prefix}: incompatible variable meanings without a validated transformation')
            if row.get('source_unit') != row.get('target_unit') and not row.get('unit_conversion'):
                errors.append(f'{prefix}: unit conversion missing')
        elif kind == 'split':
            train, test = set(row.get('training_entities', [])), set(row.get('test_entities', []))
            continuation = row.get('evaluation_target') == 'future_observations_same_entities'
            if continuation:
                errors.extend(f'{prefix}: {error}' for error in temporal_split_errors(row, train, test))
            elif train & test:
                errors.append(f'{prefix}: entity leakage across training and test')
            if set(row.get('preprocessing_fit_entities', [])) - train:
                errors.append(f'{prefix}: preprocessing fitted outside training entities')
            if not continuation and row.get('claims_independent_evaluation') and set(row.get('selection_entities', [])) & set(row.get('evaluation_entities', [])):
                errors.append(f'{prefix}: model selection reused final evaluation entities')
        elif kind == 'formula_equivalence':
            reference, actual = row.get('reference_values', []), row.get('actual_values', [])
            if not reference or len(reference) != len(actual):
                errors.append(f'{prefix}: missing or mismatched numerical evidence')
                continue
            if not row.get('reference_basis') or row.get('reference_basis') == row.get('implementation_basis'):
                errors.append(f'{prefix}: reference and implementation are not independently specified')
            atol, rtol = row.get('absolute_tolerance', 0), row.get('relative_tolerance', 1e-9)
            if not isinstance(atol, (int, float)) or not isinstance(rtol, (int, float)) or atol < 0 or rtol < 0 or not math.isfinite(atol + rtol):
                errors.append(f'{prefix}: invalid numerical tolerance')
                continue
            for expected, observed in zip(reference, actual):
                if (not isinstance(expected, (int, float)) or not isinstance(observed, (int, float))
                        or not math.isfinite(expected) or not math.isfinite(observed)
                        or not math.isclose(expected, observed, abs_tol=atol, rel_tol=rtol)):
                    errors.append(f'{prefix}: formula numerical mismatch')
                    break
        elif kind == 'sensitivity':
            scenarios = row.get('scenarios', [])
            if row.get('claims_robustness') and (not scenarios or any(s.get('conclusion_changed') for s in scenarios)):
                errors.append(f'{prefix}: robustness claim unsupported or conclusion flips')
            if row.get('structural_uncertainty_material') and not any(s.get('type') == 'structural' for s in scenarios):
                errors.append(f'{prefix}: parameter sweeps do not test material structural uncertainty')
        elif kind == 'claim_scope':
            if row.get('estimated_quantity') != row.get('claimed_quantity') and not row.get('validated_bridge'):
                errors.append(f'{prefix}: claim changes the estimated event, horizon, population or quantity')
            if row.get('decision_population') != row.get('evaluated_population') and not row.get('transfer_evidence'):
                errors.append(f'{prefix}: aggregate evaluation does not establish decision-population validity')
        elif kind == 'figure_table':
            if row.get('displayed_unit') != row.get('source_unit') or row.get('displayed_variable') != row.get('source_variable'):
                errors.append(f'{prefix}: figure/table variable or unit differs from source')
        else:
            errors.append(f'{prefix}: unknown semantic check kind {kind!r}')
    return errors


def audit_semantic_evidence(root: Path, spec: Any) -> list[str]:
    from copilot_domain import load_structured, sha256_file
    plan = spec.validation_plan
    if isinstance(plan, list):
        binding = next((row for row in plan if row.get('type') == 'semantic_evidence'), None)
        required = bool(binding and binding.get('required'))
    else:
        binding = plan.get('semantic_evidence')
        required = plan.get('semantic_checks_required')
    if not binding:
        return ['missing required semantic evidence'] if required else []
    if not isinstance(binding, Mapping) or not binding.get('path') or not binding.get('sha256'):
        return ['semantic evidence must bind path and SHA-256']
    root = root.resolve()
    path = (root / binding['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return ['semantic evidence file is missing or outside project']
    if sha256_file(path) != str(binding['sha256']).upper():
        return ['semantic evidence hash drift']
    payload = load_structured(path)
    if not payload.get('checks'):
        return ['semantic evidence has no substantive checks']
    bindings = payload.get('source_files', [])
    if not bindings:
        return ['semantic evidence must bind its actual code/data/result sources']
    errors = []
    for row in bindings:
        source = (root / row.get('path', '')).resolve()
        if not source.is_relative_to(root) or not source.is_file() or sha256_file(source) != str(row.get('sha256', '')).upper():
            errors.append('semantic evidence source is missing, outside project or changed')
    return errors + check_semantic_evidence(payload)
