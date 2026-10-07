"""Read-only, version-bound observations for both CLI and Dashboard.

This module never persists a projection or treats a previous observation as
current. Domain validity is still computed by project_status, not by the UI.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

from copilot_runtime import Runtime, claim_assurance, project_status, safe_path
from copilot_store import ConflictError, digest, utc_now

VIEW_VERSION = "0.2"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_observation(root, cp):
    paths = sorted({item['path'] for obj in cp['objects'].values() for item in obj.get('files', [])})
    result = {}
    for name in paths:
        try:
            path = safe_path(root, name)
            result[name] = {'sha256': _sha(path), 'bytes': path.stat().st_size}
        except (OSError, ValueError):
            # Do not echo an absolute OS path or exception containing one.
            result[name] = {'unavailable': True}
    return result


def _metric_leaves(value, pointer='', legacy=''):
    if isinstance(value, dict):
        for name, child in value.items():
            escaped = str(name).replace('~', '~0').replace('/', '~1')
            yield from _metric_leaves(child, pointer + '/' + escaped, legacy + '.' + str(name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _metric_leaves(child, pointer + '/' + str(index), legacy + f'[{index}]')
    elif type(value) in (int, float) and (type(value) is int or math.isfinite(value)):
        yield {'metric_path': pointer, 'legacy_path': legacy, 'value': value}


def _metric_semantics(cp, result, pointer):
    """Read declarations from actual upstream Models; names never imply units."""
    pending, seen, declarations = list(result.get('dependencies', [])), set(), []
    while pending:
        oid = pending.pop()
        if oid in seen:
            continue
        seen.add(oid)
        obj = cp['objects'].get(oid, {})
        if obj.get('kind') == 'ModelSpec':
            for output in obj.get('payload', {}).get('outputs', []):
                if not isinstance(output, dict):
                    continue
                name = output.get('name')
                named_path = '/' + name.replace('~', '~0').replace('/', '~1') if isinstance(name, str) else None
                target = output.get('metric_path', named_path)
                if target != pointer:
                    continue
                label = output.get('meaning') or output.get('label')
                fields = {key: value if isinstance(value, str) and value.strip() else None
                          for key, value in [('label', label), ('unit', output.get('unit')), ('scope', output.get('scope'))]}
                declarations.append({**fields, 'model_id': oid})
        pending.extend(obj.get('dependencies', []))
    unique = {(row['label'], row['unit'], row['scope']) for row in declarations}
    conflict = len(unique) > 1
    fields = dict(zip(('label', 'unit', 'scope'), next(iter(unique)))) if len(unique) == 1 else {'label': None, 'unit': None, 'scope': None}
    return {**fields, 'declaration_status': 'conflicting' if conflict else 'declared' if declarations else 'missing',
            'metadata_source_ids': sorted({row['model_id'] for row in declarations}),
            'result_scope': result.get('payload', {}).get('scope', ''),
            'assurance': 'declaration_only_not_unit_validation'}


def _numeric_views(cp, objects):
    """Fresh display projection, never a second state store or a trust gate."""
    metrics = {}
    for oid, obj in objects.items():
        if obj['kind'] != 'ResultRecord':
            continue
        leaves = list(_metric_leaves(obj.get('payload', {}).get('metrics', {})))
        metrics[oid] = leaves
        obj['metric_details'] = {'items': [{**row, **_metric_semantics(cp, obj, row['metric_path'])} for row in leaves[:128]],
                                 'total': len(leaves), 'truncated': len(leaves) > 128}
    for obj in objects.values():
        if obj['kind'] != 'EvidenceMapEntry':
            continue
        results = [oid for oid in obj.get('dependencies', []) if cp['objects'].get(oid, {}).get('kind') == 'ResultRecord']
        current = obj['is_current'] and not obj['current_errors']
        try:
            assurance = claim_assurance(cp, obj['payload'], results)
            bindings = copy.deepcopy(assurance['numeric_bindings'])
            for binding in bindings:
                for source in binding['sources']:
                    result = objects.get(source['result_id'], {})
                    matches = [row for row in metrics.get(source['result_id'], [])
                               if source['metric_path'] in (row['metric_path'], row['legacy_path']) and row['value'] == source['value']]
                    metric = matches[0] if len(matches) == 1 else None
                    source['current'] = result.get('is_current', False) and not result.get('current_errors') and result.get('effective_status') == 'verified'
                    source['metric'] = ({**metric, **_metric_semantics(cp, result, metric['metric_path'])} if metric else None)
                    current = current and source['current']
            obj['numeric_provenance'] = {'bindings': bindings, 'unbound_numbers': assurance['unbound_numbers'],
                'numeric_status': assurance['numeric_status'], 'current': bool(current), 'semantic_review': 'not_performed',
                'scope': 'numeric_source_binding_only'}
        except (ValueError, KeyError, TypeError) as exc:
            obj['numeric_provenance'] = {'bindings': [], 'current': False, 'error': str(exc),
                'semantic_review': 'not_performed', 'scope': 'numeric_source_binding_only'}


def snapshot(workspace, *, include_git=False, attempts=2):
    """Observe one authority and recheck files around its derived status.

    Concurrent revision or bound-file drift retries a bounded observation;
    a continuously changing project returns a conflict, never a mixed page.
    This is a read observation, not a lock against external file writers.
    """
    root = Path(workspace).resolve()
    rt = Runtime(root)
    for _ in range(attempts):
        started = utc_now()
        before_hash = _sha(rt.store.path)
        state = rt.read()
        cp = state.get('copilot')
        if not cp:
            raise ValueError('旧项目尚未迁移，请通过 CLI 显式迁移后查看')
        if _sha(rt.store.path) != before_hash:
            continue
        files = _file_observation(root, cp)
        status = project_status(root, state)
        collaboration = {'mode': 'local', 'status': 'not_enabled', 'message': '本地模式；Git 协作未启用'}
        if include_git:
            from copilot_git import repository_status
            collaboration = repository_status(root)
        objects = {}
        for oid, original in cp['objects'].items():
            item = copy.deepcopy(original)
            errors = status['stale_objects'].get(oid, [])
            item['current_errors'] = list(errors)
            item['is_current'] = cp['current'].get(item['key']) == oid
            item['effective_status'] = 'stale' if errors and item.get('status') not in {'failed','timeout','interrupted','missing_outputs'} else item.get('status', 'unknown')
            objects[oid] = item
        _numeric_views(cp, objects)
        tasks = copy.deepcopy(cp['tasks'])
        for task in tasks.values():
            errors = {oid: status['stale_objects'][oid]
                      for oid in task.get('dependencies', []) + task.get('outputs', [])
                      if oid in status['stale_objects']}
            task['current_errors'] = errors
            task['effective_status'] = 'stale' if errors else task.get('status', 'unknown')
        if files != _file_observation(root, cp) or _sha(rt.store.path) != before_hash:
            continue
        result = {'view_version': VIEW_VERSION, 'project_id': cp['project_id'],
            'revision': cp['revision'], 'state_hash': cp['state_hash'],
            'authority_file_sha256': before_hash, 'file_observation_hash': digest(files),
            'observed_files': files,
            'observation_started_at': started, 'checked_at': utc_now(),
            'identity': {'competition': state.get('competition'), 'problem': copy.deepcopy(state.get('problem_meta', {})),
                'title': state.get('paper_metadata', {}).get('title') or state.get('problem_meta', {}).get('title'), 'workspace_name': root.name,
                'navigation_stage': state.get('current_stage'), 'demo': state.get('mode') == 'demo'},
            'status': status, 'objects': objects, 'tasks': tasks,
            'requirements': copy.deepcopy(cp['requirements']), 'members': copy.deepcopy(cp['members']),
            'changes': copy.deepcopy(cp['journal']), 'decisions': copy.deepcopy(cp['decisions']),
            'collaboration': collaboration,
            'read_only': True, 'observation_scope': 'One authority revision and bound-file stability during this read; not a future validity guarantee'}
        result['snapshot_id'] = digest(result)
        return result
    raise ConflictError('项目或绑定文件在读取期间持续变化，请刷新；未返回混合版本')


def read_bound_text(workspace, reference, *, snapshot_id, revision, authority_sha256, file_observation_hash, max_bytes=262144):
    """Only expose a bound, in-project text file from a freshly checked view.

    Clients bind the authority and request their view's snapshot ID for traceability.
    A new observation is returned because byte validity can change at one revision.
    Files not registered as evidence cannot be used as an arbitrary file browser.
    """
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError('缺少来源快照 ID')
    root = Path(workspace).resolve()
    view = snapshot(root)
    if (view['revision'] != revision or view['authority_file_sha256'] != authority_sha256
            or view['file_observation_hash'] != file_observation_hash):
        raise ConflictError('来源版本已变化，请先刷新')
    bindings = {item['path'] for obj in view['objects'].values() for item in obj.get('files', [])}
    if reference not in bindings:
        raise ValueError('仅可查看已登记的项目内文本文件')
    path = safe_path(root, reference)
    if path.stat().st_size > max_bytes:
        raise ValueError('文件过大，请在本地只读工具中打开')
    if path.suffix.lower() not in {'.txt','.log','.md','.json','.csv','.py','.yaml','.yml','.tex'}:
        raise ValueError('此文件类型不支持内联文本查看')
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError('文件过大，请在本地只读工具中打开')
    content = raw.decode('utf-8')
    raw_sha = hashlib.sha256(raw).hexdigest()
    if (view['observed_files'][reference].get('sha256') != raw_sha or _sha(path) != raw_sha
            or _sha(Runtime(root).store.path) != authority_sha256):
        raise ConflictError('文件在读取期间变化，请刷新')
    related = [oid for oid, obj in view['objects'].items() if any(f['path'] == reference for f in obj.get('files', []))]
    return {'path': reference, 'content': content, 'sha256': hashlib.sha256(raw).hexdigest(),
        'request_snapshot_id': snapshot_id, 'observation_snapshot_id': view['snapshot_id'],
        'revision': revision, 'checked_at': view['checked_at'],
        'current_errors': {oid:view['objects'][oid]['current_errors'] for oid in related if view['objects'][oid]['current_errors']},
        'display_as': 'text', 'read_only': True}
