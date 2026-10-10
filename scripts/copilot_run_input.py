"""Read-only run input from a freshly checked view; execution remains in Runtime."""
from __future__ import annotations
import copy
import math

from copilot_domain import normalize_question
from copilot_view import snapshot

KINDS = {'model': 'ModelSpec', 'parameters': 'ParameterSet', 'data': 'DataContract',
         'code': 'CodeManifest', 'plan': 'ValidationPlan'}


def prepare(root, question, selected=None, *, seed='0', timeout=60):
    question = normalize_question(question)
    selected = selected or {}
    if set(selected) - set(KINDS):
        raise ValueError('未知依赖类别；只支持 model/parameters/data/code/plan')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout 必须为有限正数秒')
    if not isinstance(seed, str):
        raise ValueError('seed 为显式记录的字符串')
    view = snapshot(root)
    objects = view['objects']
    chosen, choices, excluded, blockers = {}, {}, [], []
    for name, kind in KINDS.items():
        candidates = []
        for oid, obj in objects.items():
            if obj['kind'] != kind or obj['payload'].get('question') != question:
                continue
            if not obj['is_current'] or obj['current_errors']:
                excluded.append({'id': oid, 'kind': kind, 'errors': obj['current_errors'],
                                 'is_current': obj['is_current']})
                continue
            if name in ('parameters', 'code', 'plan') and chosen.get('model') not in obj['dependencies']:
                continue
            candidates.append(oid)
        choices[name] = sorted(candidates)
        explicit = selected.get(name)
        if explicit:
            if explicit not in candidates:
                raise ValueError(f'{name} 不是当前有效、同问且绑定所选模型的候选：{explicit}')
            chosen[name] = explicit
        elif len(candidates) == 1:
            chosen[name] = candidates[0]
        else:
            blockers.append({'kind': kind, 'reason': 'missing' if not candidates else 'ambiguous',
                             'next': f'补齐当前有效的 {kind}' if not candidates else f'用 --{name} 指定一个候选'})
        if name == 'model' and name not in chosen:
            break
    result = {'read_only': True, 'ready_to_run': False, 'question': question,
              'expected_revision': view['revision'], 'authority_file_sha256': view['authority_file_sha256'],
              'file_observation_hash': view['file_observation_hash'], 'choices': choices, 'excluded': excluded,
              'blockers': blockers, 'payload': None,
              'notes': ['仅准备输入，没有执行、登记或产生核验结果。',
                        '把 payload 单独保存为项目内 JSON，再用 run --payload 引用；不要提交整个响应。',
                        '正式 run 仍检查版本、文件和依赖；本次观察不保证之后仍然有效。',
                        'seed 只记录本次选择，不证明已设置所有外部库的随机性。']}
    if blockers:
        return result
    model = objects[chosen['model']]['payload']
    result['payload'] = {'question': question, 'argv': copy.deepcopy(objects[chosen['code']]['payload']['argv']),
                         'outputs': copy.deepcopy(model['required_outputs']),
                         'dependencies': [chosen[name] for name in KINDS], 'seed': seed, 'timeout': timeout}
    result['ready_to_run'] = True
    result['next_command'] = ['run', '--expected-revision', str(view['revision']), '--payload', '<项目内的新输入.json>']
    return result
