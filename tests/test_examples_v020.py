"""Actual historical examples; synthetic model tests are not field validation."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
model=load('mcm_model_v020','examples/mcm2009a/traffic_model.py')
checker=load('mcm_check_v020','examples/mcm2009a/checker.py')
runner=load('mcm_run_v020','examples/mcm2009a/run_example.py')

class McmCaseTests(unittest.TestCase):
    def test_zero_demand_has_no_vehicles_and_no_delay(self):
        for mode in ('circle','entry','signal'):
            result=model.simulate([0]*4,mode=mode,horizon=20)
            self.assertEqual((result['arrived'],result['departed'],result['residual'],result['queue_area']),(0,0,0,0))
            self.assertEqual(checker.verify_trial(result),20)

    def test_first_two_balanced_steps_known_analytic_state(self):
        result=model.simulate([0.1]*4,horizon=2)
        self.assertAlmostEqual(result['arrived'],0.8)
        self.assertAlmostEqual(result['departed'],0.2)
        self.assertAlmostEqual(result['residual'],0.6)
        self.assertTrue(all(abs(x-0.15)<1e-10 for x in result['ledger'][-1]['ring_after']))
        self.assertEqual(checker.verify_trial(result),2)

    def test_signal_phases_include_real_clearance(self):
        result=model.simulate([0.3,0.1,0.2,0.1],mode='signal',horizon=60,weighted=True)
        self.assertEqual(sum(result['greens'])+8,60)
        self.assertEqual(sum(row['active'] is None for row in result['ledger']),8)
        checker.verify_trial(result)

    def test_declared_weighted_signal_allocation_is_verified(self):
        result=model.simulate([0.3,0.1,0.2,0.1],mode='signal',horizon=30,cycle=30,weighted=True)
        self.assertEqual(result['greens'],[10,3,6,3])
        result['greens']=[9,4,6,3]
        with self.assertRaisesRegex(ValueError,'allocation'):checker.verify_trial(result)

    def test_corrupt_flow_is_rejected(self):
        result=model.simulate([0.2]*4,horizon=10)
        result['ledger'][2]['departures'][0]+=0.1
        with self.assertRaisesRegex(ValueError,'conservation|Exit'):checker.verify_trial(result)

    def test_false_metric_is_rejected(self):
        result=model.simulate([0.2]*4,horizon=10)
        result['departed']+=1
        with self.assertRaisesRegex(ValueError,'metric'):checker.verify_trial(result)

    def test_missing_trajectory_step_is_rejected(self):
        result=model.simulate([0.2]*4,horizon=10);result['ledger'].pop()
        with self.assertRaisesRegex(ValueError,'Missing'):checker.verify_trial(result)

    def test_invalid_parameters_fail_before_computation(self):
        for kwargs in ({'horizon':0},{'capacity':float('nan')},{'cycle':5},{'mode':'unknown'}):
            with self.assertRaises(ValueError):model.simulate([0.2]*4,**kwargs)
        with self.assertRaises(ValueError):model.simulate([0.1,-1,0.1,0.1])

    def test_real_runtime_covers_requirements_but_not_formal_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)/'new'
            report=runner.run_example(project,18)
            self.assertTrue(report['status']['requirements']['complete'])
            self.assertEqual(len(report['status']['requirements']['rows']),5)
            self.assertTrue(all(row['status']=='verified' for row in report['status']['requirements']['rows']))
            self.assertFalse(report['status']['submission']['ready'])
            self.assertTrue(report['synthetic'])
            self.assertEqual(report['metrics']['candidate_count'],72)
            self.assertEqual(report['metrics']['checked_steps'],18*72)
            state=(project/'state/decision_log.json').read_bytes()
            with self.assertRaises(FileExistsError):runner.run_example(project,18)
            self.assertEqual((project/'state/decision_log.json').read_bytes(),state)
