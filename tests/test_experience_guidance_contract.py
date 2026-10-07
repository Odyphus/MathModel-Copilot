"""Real public CLI paths behind Skill guidance; not a claim about LLM compliance."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from copilot_dashboard import make_server
from test_copilot_runtime import make_project


class ExperienceGuidanceCliTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' if os.name == 'nt' else Path('/tmp')
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='copilot-guidance-cli-', dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / 'project'
        self.profile = self.base / 'private'
        self.rt, self.ids, self.reg = make_project(self.project)
        self.env = dict(os.environ, MATHMODEL_COPILOT_DATA_DIR=str(self.profile), PYTHONIOENCODING='utf-8')
        self.input_no = 0

    def cli(self, *args, project=None, command='experience', expected=0):
        proc = subprocess.run([sys.executable, str(ROOT/'scripts/copilot.py'), '--workspace',
                               str(project or self.project), command, *map(str,args)],
                              env=self.env, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout if expected == 0 else proc.stderr)
        if expected == 0:
            self.assertTrue(data['ok'], data)
            return data['result']
        self.assertFalse(data['ok'], data)
        return data

    def payload(self, value):
        self.input_no += 1
        path = self.base/f'input-{self.input_no}.json'
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def configure(self, patch):
        settings = self.cli('settings')
        return self.cli('configure', '--settings-revision', settings['settings_revision'],
                        '--payload', self.payload(patch), '--user-request', '合成CLI验收中的明确选择')

    def begin(self, request='first-session'):
        return self.cli('start', '--goal', '核对题意与方案', '--request-id', request,
                        '--save-once', '--user-request', '合成CLI验收：只保存本次过程')

    def finish(self, record, reason='handoff'):
        return self.cli('recap', '--id', record['id'], '--record-revision', record['record_revision'],
                        '--reason', reason, '--payload', self.payload({'summary':'只记录已取得的过程。',
                                                                   'next_steps':['重新核对当前题意再继续。']}))

    @staticmethod
    def hashes(root):
        return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()} if root.exists() else {}

    def test_public_teaching_has_no_project_or_personal_storage_prerequisite(self):
        before = self.hashes(self.project)
        missing = self.base/'missing'
        self.env['MATHMODEL_COPILOT_DATA_DIR'] = str(missing/'forbidden-profile')
        for args in [('catalog',), ('tutorial','--topic','all'), ('tutorial','--topic','models')]:
            result = self.cli(*args, project=missing)
            self.assertTrue(result['read_only'])
        self.assertFalse(missing.exists())
        self.assertFalse(self.profile.exists())
        self.assertEqual(before, self.hashes(self.project))

    def test_manual_teaching_still_works_after_skipped_completed_or_disabled_invitation(self):
        for state in ('skipped','completed'):
            self.configure({'tutorial':{'state':state,'invite_policy':'never'},'guidance_mode':'off'})
            before = self.hashes(self.profile)
            self.assertEqual(self.cli('tutorial','--topic','handoff')['topic'], 'handoff')
            self.assertEqual(before, self.hashes(self.profile))

    def test_unanswered_recording_choice_denies_start_without_changing_authority(self):
        before = self.hashes(self.project)
        self.assertEqual(self.cli('settings')['recap_default'], 'ask')
        self.cli('start','--goal','未授权工作','--request-id','not-authorized', expected=2)
        self.assertFalse(self.profile.exists())
        self.assertEqual(before, self.hashes(self.project))

    def test_record_close_readback_and_repeat_close_follow_the_public_cli(self):
        before = self.hashes(self.project)
        record = self.begin()
        record = self.cli('record','--id',record['id'],'--record-revision',record['record_revision'],
                          '--payload',self.payload({'event_id':'choice','kind':'decision',
                                                    'text':'先比较 LP 与 MILP，是否需要整数变量仍待判断。',
                                                    'source_kind':'agent_summary'}))
        result = self.finish(record)
        path = Path(result['saved_to'])
        self.assertEqual(path.read_text(encoding='utf-8'), result['recap']['markdown'])
        self.assertIn('先比较 LP 与 MILP', path.read_text(encoding='utf-8'))
        second = self.finish(record)
        self.assertTrue(second['reused'])
        self.assertEqual(result['saved_to'], second['saved_to'])
        self.assertEqual(len(list((self.profile/'recaps').glob('*.md'))),1)
        self.assertEqual(before,self.hashes(self.project))

    def test_exit_sequence_reads_current_status_context_and_recap_without_writes(self):
        record = self.begin();self.finish(record)
        before_project, before_private = self.hashes(self.project), self.hashes(self.profile)
        self.cli('tutorial','--topic','evidence')
        status = self.cli(command='status')
        context = self.cli('--role','modeler',command='context')
        resumed = self.cli('resume','--tags','energy')
        self.assertTrue(resumed['current']['available'])
        self.assertEqual(resumed['previous']['goal'],record['goal'])
        self.assertFalse(resumed['changed_since_recap'])
        self.assertIn('common', context)
        self.assertFalse(status['submission']['ready'])
        self.assertEqual(before_project,self.hashes(self.project))
        self.assertEqual(before_private,self.hashes(self.profile))

    def test_resuming_detects_same_revision_source_drift_instead_of_inheriting_old_success(self):
        rev = lambda:self.rt.read()['copilot']['revision']
        run = self.rt.execute(rev(),'Q1',['{python}','solver.py'],['result.json'],
                              dependencies=[self.ids[k] for k in ('model','params','data','code','plan')])['result']['object_id']
        checked = self.rt.validate_run(rev(),run,'checker.py',['{python}','{checker}','{run}','{report}'])['result']
        self.rt.cover(rev(),'REQ-Q1-001',{'value':checked['result_id']})
        record=self.begin();done=self.finish(record)
        self.assertEqual(done['recap']['observation']['report']['report_facts']['requirements']['verified'],1)
        authority=self.rt.store.path.read_bytes()
        with (self.project/'solver.py').open('a',encoding='utf-8') as out:
            out.write('\n# explicitly changed after recap\n')
        resumed=self.cli('resume')
        self.assertTrue(resumed['changed_since_recap'])
        self.assertEqual(resumed['current']['report']['report_facts']['requirements']['verified'],0)
        self.assertEqual(resumed['previous']['recap']['observation']['report']['report_facts']['requirements']['verified'],1)
        self.assertEqual(authority,self.rt.store.path.read_bytes())

    def test_cross_project_experience_is_selected_only_after_permission_and_stops_after_withdrawal(self):
        entry=self.cli('lesson-save','--payload',self.payload({'text':'核对时间槽宽后再做功率到能量换算。',
                         'conditions':'数据表示区间平均功率，且时间宽度有明确来源时。','tags':['energy'],
                         'source_kind':'user_suggestion','reusable':True}),
                       '--user-request','合成验收：选入可参考经验')
        other=self.base/'other-project';make_project(other)
        self.assertEqual(self.cli('resume','--tags','energy',project=other)['lessons']['selected'],[])
        self.configure({'experience_reuse':True,'preferences':{'detail_level':'detailed'}})
        resumed=self.cli('resume','--tags','energy',project=other)
        self.assertEqual(resumed['lessons']['selected'][0]['id'],entry['id'])
        self.assertEqual(resumed['preferences']['detail_level'],'detailed')
        self.assertEqual(self.cli('resume','--tags','routing',project=other)['lessons']['selected'],[])
        self.cli('lesson-withdraw','--id',entry['id'],'--record-revision',entry['record_revision'])
        self.assertEqual(self.cli('resume','--tags','energy',project=other)['lessons']['selected'],[])

    def test_dashboard_recap_get_remains_read_only_after_markdown_document_creation(self):
        record=self.begin();done=self.finish(record)
        self.assertTrue(Path(done['saved_to']).is_file())
        before_project,before_private=self.hashes(self.project),self.hashes(self.profile)
        with patch.dict(os.environ, {'MATHMODEL_COPILOT_DATA_DIR':str(self.profile)}):
            server=make_server(self.project)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for _ in range(2):
                    con=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
                    try:
                        con.request('GET','/api/recap',headers={'X-Copilot-Read':'1'})
                        response=con.getresponse();raw=json.loads(response.read())
                        self.assertEqual(response.status,200)
                        self.assertEqual(raw['result']['recap']['markdown'],done['recap']['markdown'])
                        self.assertNotIn('saved_to',raw['result']['recap'])
                    finally:con.close()
            finally:server.shutdown();server.server_close();thread.join(2)
        self.assertEqual(before_project,self.hashes(self.project))
        self.assertEqual(before_private,self.hashes(self.profile))


if __name__ == '__main__':
    unittest.main()
