"""Meaningful practice-solver checks; separate from the unchanged upstream suite."""
import copy
import unittest
from rgv_simulator import PARAMETERS, simulate
from verify_schedule import verify


class ScheduleTests(unittest.TestCase):
    def test_single_machine_closed_form(self):
        p=dict(group=0,move=[0,1,2,3],single=10,first=10,second=10,odd=2,even=2,clean=1)
        for horizon in (14,15,26,27,38,39,50,51):
            with self.subTest(horizon=horizon):
                r=simulate(p,machine_count=1,horizon=horizon)
                expected=0 if horizon<15 else 1+(horizon-15)//12
                self.assertEqual(r["count"],expected)
                verify(r,p)

    def test_all_official_parameter_groups_and_modes(self):
        for p in PARAMETERS:
            for mode in ("single","two"):
                for probability in (0,0.01):
                    with self.subTest(group=p["group"],mode=mode,p=probability):
                        r=simulate(p,mode=mode,first_machines=[1,3,5,7] if mode=="two" else [],fault_probability=probability,seed=4)
                        verify(r,p)
                        self.assertGreater(r["count"],0)

    def test_every_machining_fails(self):
        for mode in ("single","two"):
            r=simulate(PARAMETERS[0],mode=mode,first_machines=[1,3,5,7] if mode=="two" else [],fault_probability=1,horizon=3000)
            self.assertEqual(r["count"],0)
            self.assertGreater(r["failures"],0)
            verify(r,PARAMETERS[0])

    def test_same_seed_reproducible(self):
        kwargs=dict(mode="two",first_machines=[1,3,5,7],fault_probability=.1,seed=137,horizon=5000)
        self.assertEqual(simulate(PARAMETERS[2],**kwargs),simulate(PARAMETERS[2],**kwargs))

    def test_invalid_assignment_rejected(self):
        for assignment in ([],list(range(1,9)),[99]):
            with self.assertRaises(ValueError):
                simulate(PARAMETERS[0],mode="two",first_machines=assignment)

    def test_no_controller_access_to_future_event_queue(self):
        # Controller can select among observed demands even if event queue is unavailable.
        from rgv_simulator import Simulation
        s=Simulation(PARAMETERS[0])
        class ForbiddenFuture:
            def __getattribute__(self,name):
                raise AssertionError("controller inspected future events")
        s.events=ForbiddenFuture()
        self.assertEqual(s.choose(s.eligible()).number,1)

    def test_negative_trace_and_parameter_mutations(self):
        original=simulate(PARAMETERS[0],mode="two",first_machines=[1,3,5,7])
        def overlap(r): r["actions"][1]["start"]-=1
        def fake_count(r): r["count"]+=1
        def wrong_tool(r): next(a for a in r["actions"] if a["kind"]=="service")["phase"]=2
        def wrong_time(r): next(a for a in r["actions"] if a["kind"]=="move")["end"]+=1
        def wrong_gripper(r): next(a for a in r["actions"] if a["kind"]=="service")["holder_after"]=999
        for mutate in (overlap,fake_count,wrong_tool,wrong_time,wrong_gripper):
            r=copy.deepcopy(original);mutate(r)
            with self.subTest(mutation=mutate.__name__),self.assertRaises(ValueError): verify(r,PARAMETERS[0])
        changed=dict(PARAMETERS[0],single=1)
        with self.assertRaisesRegex(ValueError,"parameter table changed"): verify(original,changed)


if __name__=="__main__": unittest.main(verbosity=2)
