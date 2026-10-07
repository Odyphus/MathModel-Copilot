import json
import tempfile
import unittest
from pathlib import Path
from test_copilot_runtime import make_project
from copilot_context import build_context, acknowledge
from copilot_runtime import Runtime
from copilot_store import ConflictError


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.rt,self.ids,self.reg=make_project(self.root)
    def rev(self):return self.rt.read()["copilot"]["revision"]

    def test_roles_share_exact_common_facts_and_views_are_read_only(self):
        before=self.rt.store.path.read_bytes()
        views=[build_context(self.root,role=x) for x in ("modeler","coder","writer")]
        self.assertEqual(len({x["common_hash"] for x in views}),1)
        self.assertEqual(before,self.rt.store.path.read_bytes())
        self.assertNotEqual(set(views[0]["objects"]),set(views[2]["objects"]))

    def test_cumulative_changes_include_skipped_versions(self):
        base=self.rev()
        self.rt.configure(base,stage=3)
        self.rt.configure(self.rev(),stage=4)
        self.rt.configure(self.rev(),stage=5)
        ctx=build_context(self.root,role="coder",since=base)
        self.assertEqual([x["revision"] for x in ctx["changes"]],list(range(base+1,self.rev()+1)))

    def test_receipt_adoption_and_verification_are_distinct(self):
        ctx=build_context(self.root,role="coder",member="member_2")
        ack=acknowledge(self.root,self.rev(),ctx,member="member_2",action="received")["result"]
        self.assertEqual(ack["adoptions"],[]);self.assertEqual(ack["verifications"],[])
        adopted=acknowledge(self.root,self.rev(),ctx,member="member_2",action="adopted",object_ids=[self.ids["model"]])["result"]
        self.assertEqual(adopted["verifications"],[])
        with self.assertRaises(ValueError):acknowledge(self.root,self.rev(),ctx,member="member_2",action="verified",object_ids=[self.ids["model"]])
        (self.root/"review.txt").write_text("Actual scoped QA notes",encoding="utf-8")
        checked=acknowledge(self.root,self.rev(),ctx,member="member_2",action="verified",object_ids=[self.ids["model"]],actor_kind="agent_evaluator",note="reviewed model mapping for this test",evidence="review.txt")["result"]
        self.assertEqual(checked["verifications"][0]["actor_kind"],"agent_evaluator")

    def test_stale_or_unreceived_context_cannot_be_adopted(self):
        ctx=build_context(self.root,role="coder",member="member_2")
        with self.assertRaises(ValueError):acknowledge(self.root,self.rev(),ctx,member="member_2",action="adopted",object_ids=[self.ids["code"]])
        acknowledge(self.root,self.rev(),ctx,member="member_2",action="received")
        (self.root/"solver.py").write_text("print('changed')",encoding="utf-8")
        with self.assertRaises(ConflictError):acknowledge(self.root,self.rev(),ctx,member="member_2",action="adopted",object_ids=[self.ids["code"]])

    def test_context_hash_and_cross_project_boundary(self):
        ctx=build_context(self.root,role="modeler")
        ctx["common"]["blockers"]=[]
        with self.assertRaises(ValueError):acknowledge(self.root,self.rev(),ctx,member="x",action="received")

    def test_task_context_contains_dependency_closure(self):
        self.rt.task(self.rev(),"T1",{"title":"implement","role":"coder","requirements":["REQ-Q1-001"],"dependencies":[self.ids["params"]]})
        ctx=build_context(self.root,role="writer",task_id="T1")
        for key in ("params","model","contract"):self.assertIn(self.ids[key],ctx["objects"])


if __name__=="__main__":unittest.main()
