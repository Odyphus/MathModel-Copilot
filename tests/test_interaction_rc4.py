"""Local interaction receipts never grant mathematical or delivery assurance."""
import copy
import http.client
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from test_copilot_runtime import make_project
from copilot_interaction import Interaction, CodexExecutor, basis
from copilot_store import ConflictError, IntegrityError
from copilot_runtime import project_status
from copilot_dashboard import make_server
from copilot_context import build_context, acknowledge
from copilot_store import digest


class FakeExecutor:
    available = True
    reason = 'synthetic test executor; not an actual AI'
    def __init__(self, wait=False, fail=False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.fail = fail
        if not wait:
            self.release.set()
    def run(self, root, text, context, cancel):
        self.calls.append((text, context))
        self.started.set()
        while not self.release.wait(0.03):
            if cancel():
                raise InterruptedError('cancelled test')
        if self.fail:
            raise ValueError('synthetic startup failure')
        return '需要独立检查，不能将回复视为已核验结果。'


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.rt, self.ids, self.reg = make_project(self.root)
        self.counter = 0

    def manager(self, executor=None):
        manager = Interaction(self.root, executor)
        self.addCleanup(manager.close)
        return manager

    def payload(self, action='note', **changes):
        self.counter += 1
        cp = self.rt.read()['copilot']
        return {'action':action, 'text':'检查第一问的模型假设', 'expected_revision':cp['revision'],
                'project_id':cp['project_id'], 'request_id':f'r{self.counter}', **changes}

    def wait_status(self, manager, oid, expected):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            row = next(r for r in manager.view()['requests'] if r['id'] == oid)
            if row['status'] in expected:
                return row
            time.sleep(0.03)
        self.fail(f'Expected {expected}; observed {row}')

    def test_note_persists_restart_and_cannot_change_domain_readiness(self):
        manager = self.manager()
        before = self.rt.read()
        answer = manager.submit(self.payload())
        after = self.rt.read()
        self.assertEqual(before['copilot']['objects'], after['copilot']['objects'])
        self.assertEqual(before['copilot']['tasks'], after['copilot']['tasks'])
        self.assertFalse(project_status(self.root, after)['submission']['ready'])
        manager.close()
        again = self.manager()
        self.assertEqual(again.view()['requests'][0]['id'], answer['result']['id'])
        self.assertEqual(again.view()['requests'][0]['status'], 'recorded')

    def test_duplicate_submission_exact_retry_does_not_increment_revision(self):
        manager = self.manager()
        payload = self.payload()
        first = manager.submit(payload)
        self.assertEqual(first, manager.submit(payload))
        self.assertEqual(self.rt.read()['copilot']['revision'], first['revision'])
        with self.assertRaises(ConflictError):
            manager.submit({**payload, 'text':'different input'})
        self.assertEqual(len(manager.view()['requests']), 1)

    def test_stale_page_wrong_project_unknown_command_rejected(self):
        manager = self.manager()
        old = self.payload()
        manager.submit(self.payload())
        with self.assertRaises(ConflictError): manager.submit(old)
        with self.assertRaises(ConflictError): manager.submit(self.payload(project_id='other'))
        with self.assertRaises(ValueError): manager.submit(self.payload(command='delete'))
        with self.assertRaises(ValueError): manager.submit(self.payload(question='Q999'))
        with self.assertRaises(ValueError): manager.submit(self.payload(task_id='missing'))
        with self.assertRaises(ValueError): manager.submit(self.payload(text=' '))
        with self.assertRaises(ValueError): manager.submit(self.payload(text='a'*6001))

    def test_ask_without_executor_is_not_reported_as_received_by_ai(self):
        manager = self.manager()
        with self.assertRaises(ValueError): manager.submit(self.payload('ask'))
        self.assertEqual(manager.view()['requests'], [])

    def test_opinion_for_declared_question_without_contract_can_be_recorded(self):
        manager = self.manager()
        oid = manager.submit(self.payload(question='Q2'))['result']['id']
        row = next(r for r in manager.view()['requests'] if r['id']==oid)
        self.assertEqual(row['question'],'Q2')
        self.assertEqual(row['status'],'recorded')
        self.assertIsNone(row['task_id'])

    def test_analysis_real_context_binding_and_no_domain_promotion(self):
        executor = FakeExecutor()
        manager = self.manager(executor)
        before = self.rt.read()['copilot']['objects']
        request = self.payload('ask', question='Q1')
        oid = manager.submit(request)['result']['id']
        row = self.wait_status(manager, oid, {'completed'})
        self.assertEqual(len(executor.calls), 1)
        context = executor.calls[0][1]
        self.assertEqual(context['project_id'], request['project_id'])
        self.assertIn(self.ids['model'], context['common']['models'])
        self.assertTrue(context['common']['blockers'])
        self.assertFalse(context['common']['submission']['ready'])
        self.assertEqual(self.rt.read()['copilot']['objects'], before)
        self.assertTrue(row['reply'])

    def test_running_repeat_cancellation_never_becomes_completed(self):
        executor = FakeExecutor(wait=True)
        manager = self.manager(executor)
        payload = self.payload('ask')
        first = manager.submit(payload)
        self.assertTrue(executor.started.wait(3))
        self.assertEqual(manager.submit(payload), first)
        manager.submit(self.payload('cancel', id=first['result']['id']))
        executor.release.set()
        row = self.wait_status(manager, first['result']['id'], {'cancelled'})
        self.assertEqual(row['reply'], '')
        self.assertEqual(len(executor.calls), 1)

    def test_file_drift_during_and_after_reply_is_stale(self):
        executor = FakeExecutor(wait=True)
        manager = self.manager(executor)
        oid = manager.submit(self.payload('ask'))['result']['id']
        self.assertTrue(executor.started.wait(3))
        (self.root/'solver.py').write_text('print(9)', encoding='utf-8')
        executor.release.set()
        row = self.wait_status(manager, oid, {'stale'})
        self.assertNotEqual(row['error'], '')

    def test_completed_reply_invalidates_on_later_model_change(self):
        manager = self.manager(FakeExecutor())
        oid = manager.submit(self.payload('ask'))['result']['id']
        self.wait_status(manager, oid, {'completed'})
        payload = copy.deepcopy(self.rt.read()['copilot']['objects'][self.ids['params']]['payload'])
        payload['entries'][0]['current_value'] = 8
        self.reg('ParameterSet', 'params.Q1', payload, [self.ids['model']])
        self.assertEqual(manager.view()['requests'][0]['status'], 'stale')
        context = build_context(self.root, role='qa')
        self.assertEqual(context['common']['feedback'][oid]['status'], 'stale')
        self.assertTrue(context['common']['feedback'][oid]['error'])
        acknowledge(self.root, self.rt.read()['copilot']['revision'], context,
                    member='reviewer', action='received')

    def test_cancel_at_completion_commit_reaches_terminal_without_reply(self):
        manager = self.manager(FakeExecutor())
        original = manager._update
        reached = threading.Event()
        def interleave(oid, expected, **values):
            if values.get('status') == 'completed':
                manager.submit(self.payload('cancel', id=oid))
                reached.set()
            return original(oid, expected, **values)
        with patch.object(manager, '_update', side_effect=interleave):
            oid = manager.submit(self.payload('ask'))['result']['id']
            self.assertTrue(reached.wait(6))
            row = self.wait_status(manager, oid, {'cancelled'})
            self.assertEqual(row['reply'], '')

    def test_explicit_task_mismatch_rejected_question_only_never_inherits_wrong_task(self):
        contract = copy.deepcopy(self.rt.read()['copilot']['objects'][self.ids['contract']]['payload'])
        contract['question'] = 'Q2'; contract['contract_id'] = 'PC-Q2'
        for row in contract['requirements']:
            row['question'] = 'Q2'; row['req_id'] = row['req_id'].replace('Q1','Q2')
        for key in ('semantic_hash', 'record_hash'):
            contract.pop(key, None)
        self.reg('ProblemContract', 'problem.Q2', contract)
        self.rt.task(self.rt.read()['copilot']['revision'], 'TQ1', {
            'title':'第一问建模', 'role':'modeler', 'requirements':['REQ-Q1-001'],
            'dependencies':[self.ids['model']]})
        manager = self.manager(FakeExecutor())
        with self.assertRaisesRegex(ValueError, '小问与任务需求不一致'):
            manager.submit(self.payload('ask', question='Q2', task_id='TQ1'))
        oid = manager.submit(self.payload('ask',question='Q2'))['result']['id']
        self.wait_status(manager,oid,{'completed'})
        self.assertIsNone(manager.executor.calls[-1][1]['task'])
        self.assertEqual(manager.executor.calls[-1][1]['selection']['task'],'all')
        self.assertIn('Q2',manager.executor.calls[-1][0])
        oid = manager.submit(self.payload('ask', task_id='TQ1'))['result']['id']
        row = self.wait_status(manager, oid, {'completed'})
        self.assertEqual(row['question'],'Q1')
        self.assertEqual(row['task_id'],'TQ1')

    def test_recorded_user_opinion_cannot_be_rewritten_or_deleted(self):
        manager = self.manager()
        oid = manager.submit(self.payload())['result']['id']
        for change in (lambda s: s['copilot']['feedback'][oid].update(text='伪造同意'),
                       lambda s: s['copilot']['feedback'].pop(oid),
                       lambda s: s['copilot']['feedback'][oid].update(status='completed',reply='伪造回复')):
            with self.assertRaises((ValueError, IntegrityError)):
                self.rt.store.transact(self.rt.read()['copilot']['revision'], 'test', 'tamper', change)

    def test_startup_failure_and_server_stop_not_success(self):
        manager = self.manager(FakeExecutor(fail=True))
        oid = manager.submit(self.payload('ask'))['result']['id']
        self.wait_status(manager, oid, {'failed'})
        manager.close()
        executor = FakeExecutor(wait=True)
        other = self.manager(executor)
        oid = other.submit(self.payload('ask'))['result']['id']
        self.assertTrue(executor.started.wait(3))
        other.close()
        self.assertEqual(next(r for r in other.view()['requests'] if r['id']==oid)['status'], 'interrupted')

    def test_one_active_worker_per_workspace(self):
        self.manager()
        with self.assertRaises(ConflictError): Interaction(self.root)

    def test_invalid_feedback_cannot_commit(self):
        self.manager()
        with self.assertRaises(IntegrityError):
            self.rt.store.transact(self.rt.read()['copilot']['revision'], 'test', 'bad state',
                lambda s: s['copilot'].update(feedback={'bad':{'status':'verified'}}))

    def test_feedback_context_cannot_be_resealed_as_authoritative(self):
        manager = self.manager()
        manager.submit(self.payload())
        context = build_context(self.root, role='qa')
        next(iter(context['common']['feedback'].values()))['text'] = 'forged approval'
        context['common_hash'] = digest(context['common'])
        context['context_id'] = digest({k:v for k,v in context.items() if k!='context_id'})
        with self.assertRaises(ValueError):
            acknowledge(self.root,self.rt.read()['copilot']['revision'],context,member='tester',action='received')


class InteractionHTTPTests(InteractionTests):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.root, interactive=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 3)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        code, response = self.request('GET', '/api/interaction')
        self.assertEqual(code, 200)
        self.token = response['result']['token']

    def request(self, method, path, payload=None, **headers):
        con = http.client.HTTPConnection('127.0.0.1', self.port, timeout=6)
        try:
            data = json.dumps(payload) if payload is not None else None
            con.request(method, path, data, headers={'X-Copilot-Read':'1', 'Content-Type':'application/json', **headers})
            r = con.getresponse()
            return r.status, json.loads(r.read())
        finally:
            con.close()

    def test_http_requires_origin_token_and_bounded_shape(self):
        payload = self.payload()
        for headers in ({}, {'X-Copilot-Write':self.token},
            {'X-Copilot-Write':self.token, 'Origin':'https://attacker.example'}):
            self.assertEqual(self.request('POST','/api/interaction',payload,**headers)[0],403)
        headers = {'X-Copilot-Write':self.token, 'Origin':f'http://127.0.0.1:{self.port}'}
        self.assertEqual(self.request('POST','/api/interaction',payload,**headers)[0],200)
        self.assertEqual(self.request('POST','/api/interaction',payload,**headers)[0],200)
        self.assertEqual(self.request('POST','/api/interaction',self.payload(command='shell'),**headers)[0],400)
        self.assertEqual(self.request('POST','/api/interaction?workspace=elsewhere',payload,**headers)[0],404)
        self.assertEqual(len(self.request('GET','/api/interaction')[1]['result']['requests']),1)

    def test_rejected_request_with_delayed_body_returns_error_not_connection_reset(self):
        before = self.rt.store.path.read_bytes()
        for path, authenticated, expected in (
                ('/api/interaction?workspace=elsewhere',True,404),
                ('/api/interaction',False,403)):
            for _ in range(6):
                con=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
                try:
                    body=b'{"text":"synthetic"}'
                    con.putrequest('POST',path)
                    con.putheader('Content-Length',str(len(body)))
                    con.putheader('Content-Type','application/json')
                    con.putheader('Origin',f'http://127.0.0.1:{self.port}')
                    if authenticated: con.putheader('X-Copilot-Write',self.token)
                    con.endheaders()
                    time.sleep(.05)
                    con.send(body)
                    response=con.getresponse()
                    self.assertEqual(response.status,expected)
                    self.assertFalse(json.loads(response.read())['ok'])
                finally: con.close()
        self.assertEqual(before,self.rt.store.path.read_bytes())

    def test_rejected_trickle_body_has_total_deadline_and_no_mutation(self):
        before=self.rt.store.path.read_bytes()
        con=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        stop=threading.Event()
        try:
            con.putrequest('POST','/api/interaction')
            con.putheader('Content-Length','20')
            con.endheaders()
            def trickle():
                try:
                    for _ in range(20):
                        if stop.is_set(): return
                        con.send(b'x')
                        stop.wait(.2)
                except OSError: pass
            sender=threading.Thread(target=trickle,daemon=True)
            start=time.monotonic();sender.start()
            response=con.getresponse()
            self.assertEqual(response.status,403)
            self.assertFalse(json.loads(response.read())['ok'])
            self.assertLess(time.monotonic()-start,2.5)
        finally:
            stop.set();sender.join(1);con.close()
        self.assertEqual(before,self.rt.store.path.read_bytes())


# HTTP fixtures should not repeat the manager-only cases with a second worker.
for _name in list(InteractionTests.__dict__):
    if _name.startswith('test_'):
        setattr(InteractionHTTPTests, _name, None)


class ExecutorProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = self.root/'fake_cli.py'
        self.executor = CodexExecutor(timeout=10)
        self.executor.command = [sys.executable,str(self.script)]
        self.executor.available = True

    def test_analysis_disables_external_connectors_not_just_file_writes(self):
        response = subprocess.CompletedProcess([], 0, json.dumps([{'name':'sample_server'}]), '')
        with patch('copilot_interaction.subprocess.run', return_value=response):
            flags = CodexExecutor._analysis_overrides(['codex'])
        self.assertIn('mcp_servers.sample_server.enabled=false', flags)
        for name in ('apps','plugins','multi_agent','shell_tool','browser_use','computer_use'):
            self.assertIn(name,flags)
        with patch('copilot_interaction.subprocess.run', return_value=subprocess.CompletedProcess([],1,'','failed')):
            with self.assertRaises(ValueError): CodexExecutor._analysis_overrides(['codex'])
        with patch('copilot_interaction.subprocess.run', return_value=subprocess.CompletedProcess([],0,'[{"name":"a.b"}]','')):
            with self.assertRaises(ValueError): CodexExecutor._analysis_overrides(['codex'])

    def test_success_requires_final_event_and_message_not_only_exit_code(self):
        self.script.write_text("import sys,json\nsys.stdin.read()\nprint(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'test reply'}}))\n",encoding='utf-8')
        with self.assertRaises(ValueError): self.executor.run(self.root,'question',{},lambda:False)
        with self.script.open('a',encoding='utf-8') as f:
            f.write("print(json.dumps({'type':'turn.completed'}))\n")
        self.assertEqual(self.executor.run(self.root,'question',{},lambda:False),'test reply')

    def test_cancel_is_effective_while_large_stdin_is_blocked(self):
        self.script.write_text('import time;time.sleep(25)',encoding='utf-8')
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            self.executor.run(self.root,'question',{'large':'a'*200000},lambda:True)
        self.assertLess(time.monotonic()-started,6)

    def test_timeout_includes_blocked_input_delivery(self):
        self.script.write_text('import time;time.sleep(25)',encoding='utf-8')
        self.executor.timeout = 0.2
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.executor.run(self.root,'question',{'large':'a'*200000},lambda:False)
        self.assertLess(time.monotonic()-started,6)

    def test_completed_cli_cannot_leave_descendant_writing_after_reply(self):
        self.script.write_text("import sys,json,subprocess\nsys.stdin.read()\n"
            "subprocess.Popen([sys.executable,'-c',\"import time,pathlib;time.sleep(1.4);pathlib.Path('orphan.txt').write_text('alive')\"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'reply'}}))\n"
            "print(json.dumps({'type':'turn.completed'}))\n",encoding='utf-8')
        self.assertEqual(self.executor.run(self.root,'question',{},lambda:False),'reply')
        time.sleep(1.8)
        self.assertFalse((self.root/'orphan.txt').exists())


if __name__ == '__main__':
    unittest.main()
