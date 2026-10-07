"""Reproduce parameter invalidation and a real rerun using public Runtime APIs.

Usage: python extend_demo.py SOURCE PROJECT EVIDENCE change|rerun
Run the product's `demo` command in PROJECT first. No direct authority edits.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('project', type=Path)
p.add_argument('evidence', type=Path)
p.add_argument('phase', choices=['change', 'rerun'])
a = p.parse_args()
sys.path.insert(0, str(a.source.resolve() / 'scripts'))
import copilot_domain as d
from copilot_runtime import Runtime, project_status

rt = Runtime(a.project.resolve())
rev = lambda: rt.read()['copilot']['revision']
cp = rt.read()['copilot']
model_id = 'model.Q1@1'
model = cp['objects'][model_id]['payload']

if a.phase == 'change':
    assert 'params.Q1@2' not in cp['objects'], 'Use a fresh demonstration workspace'
    entries = [d.ParameterEntry.from_dict(x) for x in cp['objects']['params.Q1@1']['payload']['entries']]
    for entry in entries:
        if entry.parameter_id == 'capacity':
            assert entry.current_value == 0.8
            entry.current_value = 0.7
    params = d.ParameterSet(question='Q1', spec_id=model['spec_id'],
        modelspec_semantic_hash=model['semantic_hash'], modelspec_record_hash=model['record_hash'],
        version=2, entries=entries).to_dict()
    registered = rt.register(rev(), 'ParameterSet', 'params.Q1', params, dependencies=[model_id])
    status = project_status(a.project.resolve(), rt.read())
    assert status['requirements']['verified'] == 0
    assert not status['submission']['ready']
    evidence = {'change': {'capacity_before': 0.8, 'capacity_after': 0.7, 'unit': 'vehicle/s'},
                'transaction': registered, 'status': status}
    name = '02-parameter-change.json'
else:
    assert 'params.Q1@2' in cp['objects']
    run = rt.execute(rev(), 'Q1', ['{python}', 'driver.py'],
        ['results/traffic.json', 'results/comparison.csv', 'results/technical_summary.md'],
        dependencies=[model_id, 'params.Q1@2', 'data.Q1@1', 'code.Q1@1', 'plan.Q1@1'], timeout=180)['result']
    assert run['status'] == 'executed'
    validation = rt.validate_run(rev(), run['object_id'], 'checker.py',
        ['{python}', '{checker}', '{run}', '{report}'], timeout=180)['result']
    assert validation['passed']
    for req_id, req in rt.read()['copilot']['requirements'].items():
        rt.cover(rev(), req_id, {o: validation['result_id'] for o in req['definition']['outputs']})
    status = project_status(a.project.resolve(), rt.read())
    assert status['requirements']['verified'] == 5
    assert not status['submission']['ready']
    cp = rt.read()['copilot']
    evidence = {'run': run, 'validation': validation,
        'metrics': cp['objects'][validation['result_id']]['payload']['metrics'], 'status': status,
        'old_claim_status': cp['objects']['CLAIM-MCM@1']['status'],
        'old_section_status': cp['objects']['paper.Q1@1']['status'],
        'note': 'Old paper/claim deliberately not rewritten or promoted by this demonstration.'}
    assert evidence['old_section_status'] == 'stale'
    name = '03-rerun.json'

a.evidence.mkdir(parents=True, exist_ok=True)
(a.evidence / name).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'phase': a.phase, 'revision': status['revision'],
    'verified': status['requirements']['verified'], 'total': status['requirements']['total'],
    'ready': status['submission']['ready']}, ensure_ascii=False))
