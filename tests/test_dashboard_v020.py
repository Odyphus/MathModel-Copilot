"""Observable read-only behavior and hostile requests, using the real Core."""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from test_copilot_runtime import make_project, SOLVER
from copilot_runtime import project_status
from copilot_store import ConflictError
from copilot_view import snapshot, read_bound_text
from copilot_dashboard import make_server


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.rt, self.ids, self.reg = make_project(self.root)

    def hashes(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def verified(self):
        rev = lambda: self.rt.read()['copilot']['revision']
        deps = [self.ids[k] for k in ('model','params','data','code','plan')]
        run = self.rt.execute(rev(), 'Q1', ['{python}','solver.py'], ['result.json'], dependencies=deps)['result']['object_id']
        result = self.rt.validate_run(rev(), run, 'checker.py', ['{python}','{checker}','{run}','{report}'])['result']['result_id']
        self.rt.cover(rev(), 'REQ-Q1-001', {'value':result})
        return run, result

    def server(self, root=None):
        assets = Path(self.tmp.name) / 'assets'
        assets.mkdir(exist_ok=True)
        (assets/'index.html').write_text('<!doctype html><title>Viewer</title>', encoding='utf-8')
        server = make_server(root or self.root, assets=assets)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def request(self, port, path='/api/snapshot', method='GET', headers=None):
        con = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            con.request(method, path, headers={'X-Copilot-Read':'1', **(headers or {})})
            response = con.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            con.close()

    def read_file(self, view, path='solver.py'):
        return read_bound_text(self.root, path, snapshot_id=view['snapshot_id'],
            revision=view['revision'], authority_sha256=view['authority_file_sha256'],
            file_observation_hash=view['file_observation_hash'])

    def test_observation_matches_cli_core_and_does_not_write(self):
        self.verified()
        before = self.hashes()
        view = snapshot(self.root)
        self.assertEqual(view['status'], project_status(self.root, self.rt.read()))
        self.assertEqual(view['revision'], view['status']['revision'])
        self.assertEqual(view['status']['requirements']['verified'], 1)
        self.assertFalse(view['status']['submission']['ready'])
        self.assertTrue(view['read_only'])
        self.assertEqual(self.hashes(), before)

    def test_same_revision_file_drift_invalidates_result_and_old_file_link(self):
        run, result = self.verified()
        old = snapshot(self.root)
        authority = self.rt.store.path.read_bytes()
        (self.root/'solver.py').write_text(SOLVER+'\n# changed outside Core\n', encoding='utf-8')
        new = snapshot(self.root)
        self.assertEqual(new['revision'], old['revision'])
        self.assertEqual(new['authority_file_sha256'], old['authority_file_sha256'])
        self.assertNotEqual(new['file_observation_hash'], old['file_observation_hash'])
        for oid in (run, result):
            self.assertEqual(new['objects'][oid]['effective_status'], 'stale')
            self.assertTrue(new['objects'][oid]['current_errors'])
        self.assertEqual(new['status']['requirements']['verified'], 0)
        self.assertEqual(self.rt.store.path.read_bytes(), authority)
        with self.assertRaises(ConflictError):
            self.read_file(old)

    def test_current_object_and_historical_versions_are_separate(self):
        old = self.ids['params']
        payload = copy.deepcopy(self.rt.read()['copilot']['objects'][old]['payload'])
        payload['entries'][0]['current_value'] = 7
        new = self.reg('ParameterSet','params.Q1',payload,[self.ids['model']])
        view = snapshot(self.root)
        self.assertFalse(view['objects'][old]['is_current'])
        self.assertTrue(view['objects'][new]['is_current'])
        self.assertEqual(view['objects'][old]['effective_status'], 'stale')

    def test_completed_task_with_drift_is_not_displayed_as_current_completion(self):
        _, result = self.verified()
        self.rt.task(self.rt.read()['copilot']['revision'], 'T1', {'title':'check result','role':'coder',
            'requirements':['REQ-Q1-001'], 'dependencies':[self.ids['model']]})
        self.rt.transition(self.rt.read()['copilot']['revision'], 'T1', 'running')
        self.rt.transition(self.rt.read()['copilot']['revision'], 'T1', 'completed', outputs=[result])
        (self.root/'solver.py').write_text(SOLVER+'# drift\n',encoding='utf-8')
        task = snapshot(self.root)['tasks']['T1']
        self.assertEqual(task['status'], 'completed')
        self.assertEqual(task['effective_status'], 'stale')
        self.assertIn(result, task['current_errors'])

    def test_failed_run_keeps_failure_identity(self):
        (self.root/'solver.py').write_text('raise SystemExit(7)', encoding='utf-8')
        self.ids['code'] = self.reg('CodeManifest','code.Q1',{'question':'Q1'},[self.ids['model']],['solver.py'])
        run = self.rt.execute(self.rt.read()['copilot']['revision'],'Q1',['{python}','solver.py'],['result.json'],
            dependencies=[self.ids[k] for k in ('model','params','data','code','plan')])['result']['object_id']
        self.assertEqual(snapshot(self.root)['objects'][run]['effective_status'], 'failed')

    def test_stage_is_only_navigation_not_a_percentage(self):
        before = self.rt.read()['copilot']['revision']
        view = snapshot(self.root)
        self.assertNotIn('completion_percentage', view)
        self.assertIn('navigation_stage', view['identity'])
        self.assertFalse(view['status']['submission']['ready'])
        self.assertEqual(self.rt.read()['copilot']['revision'], before)

    def test_default_observation_never_invokes_git(self):
        with patch('copilot_git.repository_status', side_effect=AssertionError('Git must be opt-in')):
            self.assertEqual(snapshot(self.root)['collaboration']['status'], 'not_enabled')

    def test_continuous_concurrent_file_change_returns_conflict(self):
        with patch('copilot_view._file_observation', side_effect=[{'a':1},{'a':2},{'a':3},{'a':4}]):
            with self.assertRaises(ConflictError):
                snapshot(self.root)

    def test_one_concurrent_change_retries_without_mixed_observation(self):
        with patch('copilot_view._file_observation', side_effect=[{'a':1},{'a':2},{},{ }]):
            self.assertEqual(snapshot(self.root)['observed_files'], {})

    def test_bound_text_is_plain_content_and_hash_checked(self):
        payload = '<script>window.hacked=1</script>\n<!-- prompt injection is data -->'
        (self.root/'note.md').write_bytes(payload.encode('utf-8'))
        self.reg('ArtifactRecord','note',{'path':'note.md'},files=['note.md'])
        view = snapshot(self.root)
        read = self.read_file(view, 'note.md')
        self.assertEqual(read['content'], payload)
        self.assertEqual(read['display_as'], 'text')
        self.assertEqual(read['sha256'], hashlib.sha256(payload.encode()).hexdigest())

    def test_unregistered_private_file_and_traversal_are_not_readable(self):
        (self.root/'private.txt').write_text('private value', encoding='utf-8')
        view = snapshot(self.root)
        for name in ('private.txt','../secret.txt','state/decision_log.json','C:/Windows/win.ini','solver.py/../private.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.read_file(view,name)

    def test_file_link_cannot_cross_authority_revision(self):
        old = snapshot(self.root)
        self.reg('ArtifactRecord','note',{'path':'problem.txt'})
        with self.assertRaises(ConflictError):
            self.read_file(old)

    def test_oversized_file_is_rejected(self):
        (self.root/'large.log').write_text('x'*262145, encoding='utf-8')
        self.reg('ArtifactRecord','large',{'path':'large.log'},files=['large.log'])
        with self.assertRaises(ValueError):
            self.read_file(snapshot(self.root),'large.log')

    def test_api_matches_observation_and_has_no_cache_or_cors(self):
        port = self.server()
        before = self.hashes()
        code, headers, raw = self.request(port)
        self.assertEqual(code,200)
        self.assertEqual(json.loads(raw)['result']['status'],project_status(self.root,self.rt.read()))
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(before,self.hashes())

    def test_write_methods_rejected_without_state_change(self):
        port = self.server()
        before = self.hashes()
        for method in ('POST','PUT','PATCH','DELETE','OPTIONS'):
            self.assertEqual(self.request(port,method=method)[0],405)
        self.assertEqual(before,self.hashes())

    def test_dns_rebinding_cross_origin_and_missing_read_header_rejected(self):
        port = self.server()
        for headers in ({'Host':f'evil.example:{port}'},{'Origin':'https://evil.example'}, {'X-Copilot-Read':''}):
            self.assertEqual(self.request(port,headers=headers)[0],403)
        self.assertEqual(self.request(port,headers={'Origin':f'http://127.0.0.1:{port}'})[0],200)

    def test_unknown_assets_and_workspace_query_are_rejected(self):
        port = self.server()
        for name in ('/../state/decision_log.json','/state/decision_log.json','/styles.css?path=private','/%2e%2e/secret'):
            self.assertEqual(self.request(port,name)[0],404)
        self.assertEqual(self.request(port,'/api/snapshot?workspace=../../')[0],400)
        self.assertEqual(self.request(port,'/api/file?path=solver.py&path=secret')[0],400)

    def test_file_api_requires_complete_exact_snapshot_binding(self):
        port = self.server()
        view = snapshot(self.root)
        q = {'path':'solver.py','snapshot':view['snapshot_id'],'revision':view['revision'],
            'authority':view['authority_file_sha256'],'observation':view['file_observation_hash']}
        self.assertEqual(self.request(port,'/api/file?'+urlencode(q))[0],200)
        q['authority']='0'*64
        self.assertEqual(self.request(port,'/api/file?'+urlencode(q))[0],409)

    def test_missing_or_corrupt_authority_is_not_success(self):
        port = self.server(Path(self.tmp.name)/'missing')
        self.assertEqual(self.request(port)[0],404)
        port = self.server()
        raw = json.loads(self.rt.store.path.read_text(encoding='utf-8'))
        raw['copilot']['revision']+=1
        self.rt.store.path.write_text(json.dumps(raw),encoding='utf-8')
        code, _, body = self.request(port)
        self.assertEqual(code,409)
        self.assertEqual(json.loads(body)['error'],'authority_untrusted')
        self.assertNotIn(str(self.root),body.decode())

    def test_remote_bind_is_not_available(self):
        with self.assertRaises(ValueError):
            make_server(self.root,host='0.0.0.0')


if __name__ == '__main__':
    unittest.main()
