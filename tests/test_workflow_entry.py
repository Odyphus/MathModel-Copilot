"""Observe public entry help, actual execution and rejected stale input."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_copilot_runtime import ROOT, make_project
from copilot_run_input import prepare
from copilot_payload import payload_help
from copilot_store import ConflictError


class WorkflowEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/copilot.py'),
            '--workspace', str(self.root / 'unused'), *args], capture_output=True, encoding='utf-8', timeout=30)

    def test_wrappers_expose_real_help_without_a_project(self):
        for name, child in [('forecast', 'run'), ('data', 'inspect'), ('git', 'status'),
                            ('experience', 'tutorial'), ('usage-feedback', 'draft')]:
            for suffix in [[], ['--help']]:
                result = self.cli(name, *suffix)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(child, result.stdout)
                self.assertNotIn('positional arguments:\n  arguments', result.stdout)
        nested = self.cli('forecast', 'run', '--help')
        self.assertEqual(nested.returncode, 0, nested.stderr)
        self.assertIn('--spec', nested.stdout)
        self.assertFalse((self.root / 'unused').exists())

    def test_new_help_examples_need_no_project(self):
        for name in ['claim', 'section', 'usage-feedback']:
            result = self.cli('payload-help', name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('example', json.loads(result.stdout)['result'])
        self.assertFalse((self.root / 'unused').exists())

    def test_minimal_manifest_and_prepared_input_run_real_checker(self):
        rt, ids, reg = make_project(self.root)
        ids['code'] = reg('CodeManifest', 'code.Q1', payload_help('register', 'CodeManifest')['example'],
                          [ids['model']], ['solver.py'])
        before = rt.store.path.read_bytes()
        suggestion = prepare(self.root, 'Q1')
        self.assertTrue(suggestion['ready_to_run'], suggestion)
        self.assertEqual(before, rt.store.path.read_bytes())
        self.assertFalse((self.root / '.copilot/runs').exists())
        self.assertEqual(set(suggestion['payload']['dependencies']), {ids[k] for k in ['model','params','data','code','plan']})
        run = rt.execute(suggestion['expected_revision'], **suggestion['payload'])['result']['object_id']
        checked = rt.validate_run(rt.read()['copilot']['revision'], run, 'checker.py',
                                 ['{python}', '{checker}', '{run}', '{report}'])['result']
        self.assertTrue(checked['passed'])
        self.assertEqual(rt.read()['copilot']['objects'][checked['result_id']]['payload']['metrics']['value'], 10)
        example=payload_help('claim')['example']
        actual_run=rt.read()['copilot']['objects'][run]['payload']
        example['claim'].update(formal_run_id=run,data_sources=[actual_run['data_hash']],tables=[actual_run['outputs'][0]['path']])
        registered=rt.claim(rt.read()['copilot']['revision'],example['claim'],[checked['result_id']])['result']['claim_id']
        self.assertEqual(rt.read()['copilot']['objects'][registered]['status'],'verified')

    def test_multiple_code_candidates_are_not_arbitrarily_chosen(self):
        rt, ids, _ = make_project(self.root)
        from copilot_view import snapshot
        # Current Runtime rejects alias keys; simulate an ambiguous legacy view
        # to ensure this read-only helper never invents a selection in that case.
        view = snapshot(self.root)
        alternate = copy.deepcopy(view['objects'][ids['code']])
        alternate.update(id='code.alternative@1', key='code.alternative')
        view['objects']['code.alternative@1'] = alternate
        before = rt.store.path.read_bytes()
        with patch('copilot_run_input.snapshot', return_value=view):
            result = prepare(self.root, 'Q1')
            self.assertTrue(prepare(self.root, 'Q1', {'code':ids['code']})['ready_to_run'])
        self.assertFalse(result['ready_to_run'])
        self.assertIsNone(result['payload'])
        self.assertEqual(result['blockers'], [{'kind':'CodeManifest','reason':'ambiguous','next':'用 --code 指定一个候选'}])
        self.assertEqual(len(result['choices']['code']), 2)
        self.assertEqual(before, rt.store.path.read_bytes())

    def test_changed_parameter_uses_latest_version_and_old_cas_rejects(self):
        rt, ids, reg = make_project(self.root)
        old = prepare(self.root, 'Q1')
        params = copy.deepcopy(rt.read()['copilot']['objects'][ids['params']]['payload'])
        params['entries'][0]['current_value'] = 7
        latest = reg('ParameterSet', 'params.Q1', params, [ids['model']])
        new = prepare(self.root, 'Q1')
        self.assertTrue(new['ready_to_run'])
        self.assertIn(latest, new['payload']['dependencies'])
        self.assertNotIn(ids['params'], new['payload']['dependencies'])
        with self.assertRaises(ConflictError):
            rt.execute(old['expected_revision'], **old['payload'])
        with self.assertRaises(ValueError):
            prepare(self.root, 'Q1', {'parameters':ids['params']})

    def test_file_drift_and_absent_dependencies_are_not_ready(self):
        rt, ids, _ = make_project(self.root)
        before = rt.store.path.read_bytes()
        path = self.root / 'solver.py'
        path.write_text(path.read_text(encoding='utf-8')+'\n# drift\n', encoding='utf-8')
        current = prepare(self.root, 'Q1')
        self.assertFalse(current['ready_to_run'])
        self.assertEqual(current['blockers'][0]['kind'], 'CodeManifest')
        self.assertTrue(any(x['id']==ids['code'] and x['errors'] for x in current['excluded']))
        self.assertFalse(prepare(self.root, 'Q2')['ready_to_run'])
        for selector in [{'model':ids['code']}, {'missing':'unknown'}]:
            with self.assertRaises(ValueError): prepare(self.root, 'Q1', selector)
        self.assertEqual(before, rt.store.path.read_bytes())

    def test_bad_timeout_is_rejected_without_execution(self):
        make_project(self.root)
        for value in [float('nan'), float('inf'), 0, -1, True]:
            with self.assertRaises(ValueError): prepare(self.root, 'Q1', timeout=value)

    def test_recovery_advice_preserves_numeric_rejection(self):
        # Exercise an actual public rejection; no invented success or mutation.
        rt, _, _ = make_project(self.root)
        from copilot_payload import recovery_hint
        advice = recovery_hint('claim', '数值主张请使用无千位分隔符的十进制写法')
        self.assertIn('顿号', advice['action'])
        self.assertIsNone(recovery_hint('run', 'unknown error'))
        payload = self.root / 'bad.json'
        payload.write_text(json.dumps({'question':'Q1'}), encoding='utf-8')
        before = rt.store.path.read_bytes()
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/copilot.py'), '--workspace', str(self.root),
            'run', '--expected-revision', str(rt.read()['copilot']['revision']), '--payload', 'bad.json'],
            capture_output=True, encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 2)
        self.assertIn('缺少字段', json.loads(result.stderr)['message'])
        self.assertEqual(before, rt.store.path.read_bytes())
