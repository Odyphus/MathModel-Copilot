"""Fresh numeric presentation over real Core runs and hostile legacy caches."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_copilot_runtime import make_project
import copilot_domain as domain
from copilot_runtime import _put
from copilot_store import ConflictError, digest
from copilot_view import snapshot, _metric_semantics, _numeric_views


class NumericViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt, self.ids, self.reg = make_project(self.root, count=1)

    def rev(self):
        return self.rt.read()['copilot']['revision']

    def result(self):
        self.run = self.rt.execute(self.rev(), 'Q1', ['{python}', 'solver.py'], ['result.json'],
            dependencies=[self.ids[k] for k in ('model', 'params', 'data', 'code', 'plan')])['result']['object_id']
        result = self.rt.validate_run(self.rev(), self.run, 'checker.py', ['{python}', '{checker}', '{run}', '{report}'])['result']
        self.assertTrue(result['passed'], result)
        self.result_id = result['result_id']
        return self.result_id

    def claim(self):
        run = self.rt.read()['copilot']['objects'][self.run]['payload']
        payload = {'claim_id':'numeric-view', 'claim':'计算长度为 10 m。', 'paper_anchor':'results', 'formal_run_id':self.run,
            'requirement_ids':['REQ-Q1-001'], 'data_sources':[run['data_hash']], 'code_locations':['solver.py'],
            'tables':[run['outputs'][0]['path']], 'validation_evidence':['Q1.run.formal'], 'limitations':['仅适用于合成长度测试。']}
        return self.rt.claim(self.rev(), payload, [self.result_id])['result']['claim_id']

    def test_public_model_outputs_declaration_reaches_real_result(self):
        cp = self.rt.read()['copilot']
        model = copy.deepcopy(cp['objects'][self.ids['model']]['payload'])
        model['outputs'] = [{'name':'value', 'meaning':'计算长度', 'unit':'m', 'scope':'合成长度案例'}]
        self.ids['model'] = self.reg('ModelSpec', 'model.Q1', model, [self.ids['contract']])
        current = self.rt.read()['copilot']['objects'][self.ids['model']]['payload']
        self.ids['params'] = self.reg('ParameterSet','params.Q1',domain.ParameterSet(question='Q1',spec_id=current['spec_id'],
            modelspec_semantic_hash=current['semantic_hash'],modelspec_record_hash=current['record_hash'],version=2,
            entries=[domain.ParameterEntry.from_dict(p) for p in current['parameters']]).to_dict(),[self.ids['model']])
        self.ids['code'] = self.reg('CodeManifest','code.Q1',{'question':'Q1'},[self.ids['model']],['solver.py'])
        self.ids['plan'] = self.reg('ValidationPlan','plan.Q1',{'question':'Q1',
            'checker':{'path':'checker.py','sha256':domain.sha256_file(self.root/'checker.py')},
            'checks':[{'check_id':'known','method':'independent addition','criterion':'computed length equals independently added length'}]},[self.ids['model']])
        result = self.result()
        row = snapshot(self.root)['objects'][result]['metric_details']['items'][0]
        self.assertEqual((row['label'], row['unit'], row['scope']),('计算长度','m','合成长度案例'))
        self.assertEqual(row['metadata_source_ids'],[self.ids['model']])
        self.assertEqual(row['assurance'],'declaration_only_not_unit_validation')

    def test_absent_semantics_never_guesses_units_and_snapshot_writes_nothing(self):
        result = self.result()
        before = self.rt.store.path.read_bytes()
        view = snapshot(self.root)
        metric = view['objects'][result]['metric_details']['items'][0]
        self.assertEqual(metric['metric_path'],'/value')
        self.assertIsNone(metric['label'])
        self.assertIsNone(metric['unit'])
        self.assertEqual(before,self.rt.store.path.read_bytes())
        self.assertEqual(view['snapshot_id'],digest({k:v for k,v in view.items() if k!='snapshot_id'}))

    def test_ambiguous_keys_use_only_exact_upstream_declarations(self):
        result = {'dependencies':['model1']}
        cp = {'objects':{'model1':{'kind':'ModelSpec','dependencies':[],'payload':{'outputs':[{'name':'capacity','meaning':'储能容量','unit':'kWh'},{'name':'horizon','meaning':'预测跨度','unit':'h'}]}}}}
        self.assertEqual(_metric_semantics(cp,result,'/capacity')['unit'],'kWh')
        self.assertEqual(_metric_semantics(cp,result,'/horizon')['unit'],'h')
        self.assertIsNone(_metric_semantics(cp,result,'/other/capacity')['unit'])
        cp['objects']['model2']={'kind':'ModelSpec','dependencies':[],'payload':{'outputs':[{'name':'capacity','meaning':'通行能力','unit':'pcu/s'}]}}
        result['dependencies'].append('model2')
        self.assertEqual(_metric_semantics(cp,result,'/capacity')['declaration_status'],'conflicting')
        self.assertIsNone(_metric_semantics(cp,result,'/capacity')['unit'])

    def test_claim_binding_is_recomputed_instead_of_using_forged_cache(self):
        self.result();original = self.claim()
        payload=self.rt.read()['copilot']['objects'][original]['payload']
        def corrupt_cache(state):
            claim=_put(state,'EvidenceMapEntry','legacy-cache',payload,[self.result_id],status='verified')
            state['copilot']['objects'][claim]['numeric_bindings']=[{'text':'999','sources':[]}]
            return claim
        claim=self.rt._tx(self.rev(),'fixture','Load legacy object with forged cache',corrupt_cache)['result']
        before = self.rt.store.path.read_bytes()
        projection = snapshot(self.root)['objects'][claim]['numeric_provenance']
        self.assertEqual(projection['bindings'][0]['text'],'10')
        self.assertEqual(projection['bindings'][0]['sources'][0]['metric']['value'],10)
        self.assertEqual(projection['semantic_review'],'not_performed')
        self.assertNotIn('verified',projection)
        self.assertEqual(before,self.rt.store.path.read_bytes())

    def test_same_revision_file_drift_marks_numeric_source_unusable(self):
        self.result();claim = self.claim()
        before = snapshot(self.root)
        self.assertTrue(before['objects'][claim]['numeric_provenance']['current'])
        (self.root/'solver.py').write_text('print("changed")',encoding='utf-8')
        after = snapshot(self.root)
        self.assertEqual(before['revision'],after['revision'])
        self.assertFalse(after['objects'][claim]['numeric_provenance']['current'])
        self.assertFalse(after['objects'][claim]['numeric_provenance']['bindings'][0]['sources'][0]['current'])

    def test_drift_during_numeric_projection_rejects_mixed_snapshot(self):
        self.result()
        def change_during_projection(cp,objects):
            _numeric_views(cp,objects)
            solver=self.root/'solver.py'
            solver.write_text(solver.read_text(encoding='utf-8')+'\n# drift',encoding='utf-8')
        with patch('copilot_view._numeric_views',side_effect=change_during_projection),self.assertRaises(ConflictError):
            snapshot(self.root,attempts=1)

    def test_legacy_ambiguous_dot_paths_never_choose_a_metric_semantics(self):
        self.result();claim = self.claim()
        cp = self.rt.read()['copilot']
        result=cp['objects'][self.result_id]
        result['payload']['metrics']={'a.b':10,'a':{'b':10}}
        result['payload_hash']=digest(result['payload'])
        objects=copy.deepcopy(cp['objects'])
        for obj in objects.values():
            obj.update(is_current=True,current_errors=[],effective_status=obj['status'])
        _numeric_views(cp,objects)
        sources=objects[claim]['numeric_provenance']['bindings'][0]['sources']
        self.assertEqual(len(sources),2)
        self.assertTrue(all(source['metric'] is None for source in sources))


if __name__=='__main__':
    unittest.main()
