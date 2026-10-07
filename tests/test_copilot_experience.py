"""Private recap lifecycle, observable continuity and preserved authority."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_experience import ExperienceStorage, execute, parser
from copilot_recap import (start, record_event, close, resume, save_lesson,
                           withdraw_lesson, edit_lesson, export_recap, forget, observation)
from copilot_store import ConflictError, IntegrityError
from test_copilot_runtime import make_project


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        # The developer checkout itself may be under Git. Private profiles must
        # instead use the OS private temporary area, never relax the product rule.
        base = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' if os.name == 'nt' else Path('/tmp')
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'contest'
        self.profile = Path(self.temp.name) / 'private'
        self.rt, self.ids, self.reg = make_project(self.root)
        self.store = ExperienceStorage(self.root, self.profile)

    def begin(self):
        return start(self.store, '完成第一问', 'session-a', save_once=True, user_request='只保存这一次')

    def verified(self):
        rev = lambda: self.rt.read()['copilot']['revision']
        rid=self.rt.execute(rev(),'Q1',['{python}','solver.py'],['result.json'],
             dependencies=[self.ids[k] for k in ('model','params','data','code','plan')])['result']['object_id']
        checked=self.rt.validate_run(rev(),rid,'checker.py',['{python}','{checker}','{run}','{report}'])['result']
        self.rt.cover(rev(),'REQ-Q1-001',{'value':checked['result_id']})

    def test_default_read_creates_nothing_and_tutorial_needs_no_project(self):
        self.assertEqual('ask',self.store.settings()['recap_default'])
        self.assertFalse(self.profile.exists())
        value=execute(parser().parse_args(['--workspace',str(self.root/'missing'),'tutorial','--topic','all']))
        self.assertTrue(value['read_only'])
        self.assertFalse((self.root/'missing').exists())
        with self.assertRaises(ValueError): start(self.store,'goal','id')

    def test_configure_conflict_project_scope_and_cross_project_preference(self):
        self.store.configure({'project_recap':'on','preferences':{'detail_level':'detailed'}},0,'本人开启')
        self.assertTrue(self.store.recording_enabled())
        other=ExperienceStorage(self.root.parent/'other',self.profile)
        self.assertFalse(other.recording_enabled())
        self.assertEqual('detailed',resume(other)['preferences']['detail_level'])
        with self.assertRaises(ConflictError): self.store.configure({'recap_default':'off'},0,'关闭')

    def test_project_profile_and_git_profile_are_rejected(self):
        with self.assertRaises(ValueError): ExperienceStorage(self.root,self.root/'private')
        self.profile.mkdir();(self.profile/'.git').mkdir()
        with self.assertRaises(ValueError): ExperienceStorage(self.root,self.profile/'nested')

    def test_timely_excerpt_checked_and_idempotent(self):
        rec=self.begin()
        (self.root/'selected.txt').write_text('用户选择\n比较 LP 和 MILP\n',encoding='utf8')
        p={'event_id':'e1','kind':'decision','text':'比较 LP 和 MILP','source_kind':'artifact_excerpt',
           'source_file':'selected.txt','start_line':2,'end_line':2}
        saved=record_event(self.store,rec['id'],1,p)
        self.assertEqual(saved,record_event(self.store,rec['id'],1,p))
        p['text']='用户同意了所有结果'
        with self.assertRaises(ValueError): record_event(self.store,rec['id'],2,p)
        with self.assertRaises(ValueError): record_event(self.store,rec['id'],2,{'verified':True})

    def test_false_report_is_labeled_not_authority(self):
        rec=self.begin();before=self.rt.store.path.read_bytes()
        rec=record_event(self.store,rec['id'],1,{'event_id':'e','kind':'note','text':'报告自称全部完成',
                                             'source_kind':'agent_summary'})
        done=close(self.store,rec['id'],2,'goal_finished')
        self.assertEqual(0,done['recap']['observation']['report']['report_facts']['requirements']['verified'])
        self.assertIn('AI转述',done['recap']['markdown'])
        self.assertEqual(before,self.rt.store.path.read_bytes())

    def test_recap_writes_document_and_retry_no_duplicate(self):
        rec=self.begin()
        result=close(self.store,rec['id'],1,'handoff',{'next_steps':['检查第二问']})
        self.assertEqual(result['recap']['markdown'],Path(result['saved_to']).read_text(encoding='utf8'))
        again=close(self.store,rec['id'],1,'handoff',{'next_steps':['检查第二问']})
        self.assertTrue(again['reused']);self.assertEqual(result['saved_to'],again['saved_to'])
        self.assertEqual(1,len(again['record']['recaps']))
        Path(result['saved_to']).write_text('作者编辑',encoding='utf8')
        with self.assertRaises(IntegrityError): close(self.store,rec['id'],2,'handoff',{'next_steps':['检查第二问']})
        self.assertEqual('作者编辑',Path(result['saved_to']).read_text(encoding='utf8'))

    def test_resume_rechecks_drift_at_same_revision(self):
        self.verified();rec=self.begin();done=close(self.store,rec['id'],1,'goal_finished')
        old=done['recap']['observation']['report']['revision']
        self.assertFalse(resume(self.store)['changed_since_recap'])
        (self.root/'solver.py').write_text('print(999)',encoding='utf8')
        current=resume(self.store)
        self.assertTrue(current['changed_since_recap'])
        self.assertEqual(old,current['current']['report']['revision'])
        self.assertEqual(0,current['current']['report']['report_facts']['requirements']['verified'])
        self.assertEqual(1,current['previous']['recap']['observation']['report']['report_facts']['requirements']['verified'])

    def test_bad_recap_analysis_does_not_set_shared_facts(self):
        rec=self.begin()
        with self.assertRaises(ValueError): close(self.store,rec['id'],1,'manual',{'verified':100})
        self.assertEqual([],self.store.read('experiences',rec['id'])['recaps'])

    def test_disable_stops_record_and_close(self):
        rec=self.begin();self.store.configure({'project_recap':'off'},0,'关闭本项目记录')
        with self.assertRaises(ValueError): close(self.store,rec['id'],1,'manual')
        self.assertEqual(1,self.store.read('experiences',rec['id'])['record_revision'])

    def test_clone_has_no_old_recap_or_authorization(self):
        rec=self.begin();close(self.store,rec['id'],1,'manual')
        import shutil
        other=self.root.parent/'clone';shutil.copytree(self.root,other)
        clone=ExperienceStorage(other,self.profile)
        self.assertIsNone(resume(clone)['previous'])
        self.assertFalse(clone.recording_enabled())

    def test_missing_authority_is_unknown_and_no_automatic_recovery_write(self):
        other=ExperienceStorage(self.root.parent/'missing',self.profile)
        rec=start(other,'未能初始化','start',save_once=True,user_request='保留失败')
        value=resume(other)
        self.assertFalse(value['current']['available'])
        self.assertEqual(rec['id'],value['unfinished_experiences'][0]['id'])
        self.assertFalse(other.workspace.exists())

    def test_selected_lesson_actually_read_and_stale_or_withdrawn_excluded(self):
        rec=self.begin();close(self.store,rec['id'],1,'manual')
        lesson=save_lesson(self.store,{'text':'先核对单位','conditions':'处理功率与能量时',
               'tags':['energy'],'source_kind':'experience','source_experience':rec['id'],'reusable':True},'以后可参考')
        self.store.configure({'experience_reuse':True},0,'允许跨项目参考选定经验')
        other=ExperienceStorage(self.root.parent/'newproject',self.profile)
        self.assertEqual(lesson['id'],resume(other,['energy'])['lessons']['selected'][0]['id'])
        self.assertEqual([],resume(other,['geometry'])['lessons']['selected'])
        (self.root/'solver.py').write_text('changed',encoding='utf8')
        self.assertEqual([],resume(other,['energy'])['lessons']['selected'])
        self.assertEqual(1,len(resume(other,['energy'])['lessons']['excluded']))
        withdraw_lesson(self.store,lesson['id'],1)
        self.assertEqual([],resume(other,['energy'])['lessons']['excluded'])

    def test_export_never_overwrites_and_forget_removes_only_selected(self):
        rec=self.begin();done=close(self.store,rec['id'],1,'manual')
        target=self.root/'outputs'/'my-recap.md'
        export_recap(self.store,rec['id'],target)
        with self.assertRaises(ValueError): export_recap(self.store,rec['id'],target)
        with self.assertRaises(ValueError): export_recap(self.store,rec['id'],self.root/'state.'/'evil.md')
        forget(self.store,'experiences',rec['id'],2)
        self.assertFalse(Path(done['saved_to']).exists());self.assertTrue(target.exists())
        self.assertIsNone(self.store.read('experiences',rec['id']))

    def test_corrupt_settings_fail_without_reset(self):
        self.store.configure({'recap_default':'on'},0,'允许')
        path=self.store.path('experience-settings.json')
        data=json.loads(path.read_text(encoding='utf8'));data['recap_default']='off'
        path.write_text(json.dumps(data),encoding='utf8')
        before=path.read_bytes()
        with self.assertRaises(IntegrityError): self.store.settings()
        self.assertEqual(before,path.read_bytes())

    def test_public_cli_routes_without_initialization(self):
        from copilot import parser as main_parser, execute as main_execute
        result=main_execute(main_parser().parse_args(['--workspace',str(self.root/'none'),'experience','tutorial','--topic','recap']))
        self.assertEqual('recap',result['topic'])
        self.assertFalse((self.root/'none').exists())

    def test_edit_lesson_has_revision_and_cannot_rewrite_source(self):
        lesson=save_lesson(self.store,{'text':'先核对单位','conditions':'功率数据','tags':['energy']},'保存')
        edited=edit_lesson(self.store,lesson['id'],1,{'conditions':'明确槽宽后换算','reusable':True},'修改')
        self.assertEqual('明确槽宽后换算',edited['conditions'])
        with self.assertRaises(ConflictError): edit_lesson(self.store,lesson['id'],1,{'text':'旧版本'},'修改')
        with self.assertRaises(ValueError): edit_lesson(self.store,lesson['id'],2,{'source_kind':'verified'},'修改')


if __name__=='__main__': unittest.main()
