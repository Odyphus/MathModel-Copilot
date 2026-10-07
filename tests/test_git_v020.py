"""Real local repositories; no GitHub access, accounts or global Git writes."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import copilot_git as cg
from copilot_context import acknowledge
from copilot_delivery import Delivery
from copilot_runtime import Runtime, project_status
from copilot_store import ConflictError, IntegrityError, digest
from test_copilot_runtime import make_project, SOLVER

GIT = shutil.which("git")


class LocalFallbackTests(unittest.TestCase):
    def test_no_git_leaves_local_core_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, _, _ = make_project(tmp, count=1)
            before = rt.store.path.read_bytes()
            with patch.object(cg.shutil, "which", return_value=None):
                report = cg.repository_status(tmp)
                self.assertFalse(report["git_available"])
                self.assertEqual(report["network_actions"], [])
                self.assertFalse(project_status(tmp, rt.read())["submission"]["ready"])
            self.assertEqual(before, rt.store.path.read_bytes())


@unittest.skipUnless(GIT, "optional Git executable not installed; local core tests remain active")
class GitCollaborationTests(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get("MATHMODEL_GIT_TEST_EVIDENCE")
        if evidence:
            # Keep real Git object paths usable on default Windows MAX_PATH.
            self.base = Path(evidence) / cg._sha(self._testMethodName.encode())[:10]
            self.base.mkdir(parents=True, exist_ok=False)
        else:
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            self.base = Path(temp.name)
        self.commands = []
        self.observations = {}
        self.addCleanup(self.write_evidence)
        self.seed = self.base / "seed"
        self.rt_seed, self.ids, _ = make_project(self.seed, count=1)
        (self.seed / ".gitignore").write_text("/state/\n/.copilot/\n/handoff/\n", encoding="utf-8")
        self.git(self.seed, "init", "--initial-branch=integration")
        self.git(self.seed, "add", "--", ".gitignore", "problem.txt", "solver.py", "checker.py")
        self.git(self.seed, "commit", "-m", "Synthetic fixture initial files; authority excluded")
        self.one, self.two = self.base / "modeler", self.base / "integrator"
        for root in (self.one, self.two):
            self.git(self.base, "clone", "--no-hardlinks", str(self.seed), str(root))
            shutil.copytree(self.seed / "state", root / "state")
            cg.protect(root)

    def write_evidence(self):
        if os.environ.get("MATHMODEL_GIT_TEST_EVIDENCE"):
            (self.base / "case.json").write_text(json.dumps({"id": self.id()}, indent=2), encoding="utf-8")
            (self.base / "commands.json").write_text(json.dumps(self.commands, ensure_ascii=False, indent=2), encoding="utf-8")
            (self.base / "observations.json").write_text(json.dumps(self.observations, ensure_ascii=False, indent=2), encoding="utf-8")

    def git(self, root, *args, ok=(0,)):
        result = subprocess.run([GIT, "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
                                 "-c", "core.hooksPath=" + os.devnull,
                                 "-c", "user.name=Copilot Synthetic Fixture", "-c", "user.email=fixture@example.invalid",
                                 "-c", "protocol.file.allow=always", "-C", str(root), *args],
                                env=cg._safe_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False, shell=False)
        self.commands.append({"cwd": str(Path(root).relative_to(self.base)), "argv": list(args),
                              "exit_code": result.returncode,
                              "stdout": result.stdout.decode("utf-8", "replace"),
                              "stderr": result.stderr.decode("utf-8", "replace")})
        self.assertIn(result.returncode, ok, result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8", "replace").strip()

    def rev(self, root):
        return Runtime(root).read()["copilot"]["revision"]

    def proposal(self, root, kind="ArtifactRecord", key="note.new", payload=None, dependencies=(), files=("problem.txt",)):
        return cg.create_proposal(root, compare="HEAD", reason="Explicit synthetic integration change",
            action={"kind": kind, "key": key, "payload": payload or {"path": files[0]},
                    "dependencies": list(dependencies), "files": list(files)})

    def params(self, root, value):
        payload = copy.deepcopy(Runtime(root).read()["copilot"]["objects"][self.ids["params"]]["payload"])
        payload["entries"][0]["current_value"] = value
        return self.proposal(root, "ParameterSet", "params.Q1", payload, [self.ids["model"]], [])

    def test_non_repository_is_normal_degradation(self):
        report = cg.repository_status(self.base)
        self.assertTrue(report["git_available"])
        self.assertFalse(report["is_repository"])
        self.assertEqual(report["remote_live_state"], "unknown_not_fetched")

    def test_line_ending_only_change_is_explicit_in_text_diff(self):
        path = self.one / 'problem.txt'
        before = path.read_bytes()
        path.write_bytes(before.rstrip(b'\r\n') + b'\n')
        report = cg.diff_report(self.one, 'HEAD', patch=True)
        change = next(x for x in report['changes'] if x['path'] == 'problem.txt')
        self.assertNotEqual(change['sha256'], change['base_sha256'])
        self.assertEqual(change.get('patch_reason'), 'line endings or final newline differ; inspect byte hashes')

    def test_historical_replacement_does_not_fail_current_binding_review(self):
        rt = Runtime(self.one)
        payload = copy.deepcopy(rt.read()['copilot']['objects'][self.ids['params']]['payload'])
        payload['entries'][0]['current_value'] = 7
        new = rt.register(self.rev(self.one), 'ParameterSet', 'params.Q1', payload,
            dependencies=[self.ids['model']])['result']['object_id']
        report = cg.verify_workspace(self.one)
        self.assertIn(self.ids['params'], report['status']['stale_objects'])
        self.assertNotIn(new, report['status']['stale_objects'])
        self.assertTrue(report['passed'])
        self.assertFalse(report['submission_ready'])

    def test_unborn_staged_untracked_and_detached_states(self):
        root = self.base / "unborn"
        root.mkdir()
        self.git(root, "init", "--initial-branch=new-project")
        (root / "new.txt").write_text("new", encoding="utf-8")
        report = cg.repository_status(root, "missing")
        self.assertTrue(report["unborn"])
        self.assertTrue(report["changes"][0]["untracked"])
        self.git(root, "add", "--", "new.txt")
        self.assertEqual(cg.repository_status(root)["changes"][0]["index"], "A")
        self.git(root, "commit", "-m", "new fixture")
        self.git(root, "checkout", "--detach")
        self.assertTrue(cg.repository_status(root)["detached"])
        self.observations["unborn"] = report

    def test_local_saved_reference_behind_is_not_remote_realtime(self):
        (self.one / "notes.txt").write_text("local source commit", encoding="utf-8")
        self.git(self.one, "add", "--", "notes.txt")
        self.git(self.one, "commit", "-m", "advance fixture")
        # Controlled file transport in the test only. The adapter never fetches.
        self.git(self.two, "fetch", str(self.one), "integration:refs/remotes/team/integration")
        report = cg.repository_status(self.two, "team/integration")
        self.assertEqual(report["comparison"]["behind"], 1)
        self.assertEqual(report["comparison"]["ahead"], 0)
        self.assertEqual(report["remote_live_state"], "unknown_not_fetched")
        self.assertEqual(cg.repository_status(self.two, "origin/integration")["comparison"]["behind"], 0)
        self.observations["local_saved_refs"] = report

    def test_missing_or_unrelated_comparison_stays_unknown(self):
        self.assertEqual(cg.repository_status(self.one, "not-present")["comparison"]["status"], "unknown")
        self.git(self.one, "checkout", "--orphan", "unrelated")
        self.git(self.one, "commit", "-m", "independent root")
        self.assertIsNone(cg.repository_status(self.one, "integration")["comparison"]["merge_base"])
        self.assertEqual(cg.diff_report(self.one, "integration")["status"], "unknown")

    def test_branch_and_path_injection_are_rejected(self):
        for ref in ("--help", "HEAD~1", "x;echo hacked", "x$(whoami)", "a..b", "x\n--all", "x@{1}"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                cg.repository_status(self.one, ref)
        for path in ("../outside", "C:/outside", "/outside", "x\\y", "a/../b", "-option", "state./decision_log.json", ".git /config", "x./file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                cg._file_snapshot(self.one, path)

    def test_remote_credentials_and_invalid_remote_not_echoed_or_contacted(self):
        secret = "ghp_SYNTHETIC_ONLY_DO_NOT_USE_TOKEN"
        self.git(self.one, "remote", "set-url", "origin", "https://user:" + secret + "@invalid.example/private.git?token=also-secret")
        report = cg.repository_status(self.one, "origin/integration")
        text = json.dumps(report)
        self.assertNotIn(secret, text)
        self.assertNotIn("also-secret", text)
        self.assertNotIn("private.git", text)
        self.assertEqual(report["network_actions"], [])
        self.assertEqual(report["remotes"][0]["authorization"], "not_established")
        self.observations["redacted_remote"] = report

    def test_untrusted_filters_and_fsmonitor_are_not_executed(self):
        probe = self.base / "must-not-run.py"
        sentinel = self.base / "executed.txt"
        probe.write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('executed')\n", encoding="utf-8")
        command = '"' + sys.executable + '" "' + str(probe) + '"'
        self.git(self.one, "config", "filter.evil.clean", command)
        self.git(self.one, "config", "filter.evil.process", command)
        self.git(self.one, "config", "filter.evil.required", "true")
        self.git(self.one, "config", "core.fsmonitor", command)
        self.git(self.one, "config", "diff.external", command)
        (self.one / ".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")
        (self.one / "solver.py").write_text(SOLVER + "\n# local dirty bytes\n", encoding="utf-8")
        self.assertTrue(cg.repository_status(self.one)["dirty"])
        self.assertTrue(cg.diff_report(self.one, "HEAD", patch=True)["changes"])
        self.assertFalse(sentinel.exists())

    def test_nested_submodule_filters_are_not_executed_or_reported_as_inspected(self):
        self.git(self.one, "submodule", "add", str(self.seed), "module")
        submodule = self.one / "module"
        probe = self.base / "submodule-probe.py"
        sentinel = self.base / "submodule-executed.txt"
        probe.write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('executed')\n", encoding="utf-8")
        command = '"' + sys.executable + '" "' + str(probe) + '"'
        self.git(submodule, "config", "filter.nested.clean", command)
        (submodule / ".gitattributes").write_text("*.py filter=nested\n", encoding="utf-8")
        (submodule / "solver.py").write_text(SOLVER + "# trigger submodule clean filter if inspected\n", encoding="utf-8")
        report = cg.repository_status(self.one)
        self.assertFalse(sentinel.exists(), "read-only inspection executed a submodule-configured filter")
        self.assertIn("module", report["uninspected_submodules"])

    def test_readonly_diff_maps_real_files_and_keeps_unknown_paths(self):
        rt = Runtime(self.one)
        before = rt.store.path.read_bytes()
        (self.one / "solver.py").write_text(SOLVER + "\n# changed\n", encoding="utf-8")
        (self.one / "unknown-note.txt").write_text("unregistered", encoding="utf-8")
        report = cg.diff_report(self.one, "HEAD", patch=True)
        self.assertIn(self.ids["code"], report["impact"]["direct_objects"])
        self.assertIn("unknown-note.txt", report["impact"]["unknown_paths"])
        self.assertIn("+# changed", next(x["patch"] for x in report["changes"] if x["path"] == "solver.py"))
        self.assertEqual(before, rt.store.path.read_bytes())
        self.observations["diff"] = report

    def test_deleted_and_renamed_files_are_not_silently_omitted(self):
        self.git(self.one, "mv", "solver.py", "renamed.py")
        report = cg.diff_report(self.one, "HEAD")
        rows = {x["path"]: x for x in report["changes"]}
        self.assertEqual(rows["solver.py"]["change"], "deleted")
        self.assertEqual(rows["renamed.py"]["change"], "added")
        self.assertIn(self.ids["code"], report["impact"]["affected_objects"])

    def test_dirty_snapshot_is_distinct_from_commit_and_applies_atomically(self):
        old_commit = cg.repository_status(self.one)["commit"]
        (self.one / "solver.py").write_text(SOLVER + "\n# reviewed replacement\n", encoding="utf-8")
        proposal = self.proposal(self.one, "CodeManifest", "code.Q1", {"question": "Q1"}, [self.ids["model"]], ["solver.py"])
        self.assertTrue(proposal["dirty"])
        self.assertEqual(proposal["source_commit"], old_commit)
        shutil.copy2(self.one / "solver.py", self.two / "solver.py")
        old_revision = self.rev(self.two)
        applied = cg.apply_proposal(self.two, proposal, expected_revision=old_revision)
        self.assertEqual(applied["revision"], old_revision + 1)
        self.assertEqual(applied["result"]["git_proposal_id"], proposal["proposal_id"])
        self.assertEqual(Runtime(self.two).read()["copilot"]["objects"][self.ids["code"]]["status"], "stale")
        self.assertEqual(cg.repository_status(self.two)["commit"], old_commit)
        self.observations.update(proposal=proposal, applied=applied)

    def test_file_drift_after_proposal_refuses_transaction(self):
        proposal = self.proposal(self.one)
        rt = Runtime(self.two)
        before = rt.store.path.read_bytes()
        (self.two / "problem.txt").write_text("changed after proposal", encoding="utf-8")
        with self.assertRaises(ConflictError):
            cg.apply_proposal(self.two, proposal, expected_revision=self.rev(self.two))
        self.assertEqual(before, rt.store.path.read_bytes())

    def test_same_baseline_parameter_conflict_refused_without_overwrite(self):
        first, second = self.params(self.one, 7), self.params(self.two, 9)
        cg.apply_proposal(self.two, first, expected_revision=self.rev(self.two))
        before = Runtime(self.two).store.path.read_bytes()
        with self.assertRaises(ConflictError):
            cg.apply_proposal(self.two, second, expected_revision=self.rev(self.two))
        self.assertEqual(before, Runtime(self.two).store.path.read_bytes())
        self.observations.update(first=first, rejected=second)

    def test_unrelated_proposals_same_baseline_merge_via_separate_transactions(self):
        first = self.proposal(self.one, key="artifact.one")
        second = self.proposal(self.two, key="artifact.two", files=["checker.py"])
        base_revision = self.rev(self.two)
        cg.apply_proposal(self.two, first, expected_revision=base_revision)
        cg.apply_proposal(self.two, second, expected_revision=base_revision + 1)
        cp = Runtime(self.two).read()["copilot"]
        self.assertIn("artifact.one", cp["current"])
        self.assertIn("artifact.two", cp["current"])
        self.assertEqual(cp["revision"], base_revision + 2)
        self.observations.update(first=first, second=second, journal=cp["journal"][-2:])

    def test_stale_expected_revision_is_not_automatically_retried(self):
        proposal = self.proposal(self.one)
        old = self.rev(self.two)
        Runtime(self.two).configure(old, stage=2)
        with self.assertRaises(ConflictError):
            cg.apply_proposal(self.two, proposal, expected_revision=old)

    def test_divergent_authority_history_is_not_a_git_merge_candidate(self):
        Runtime(self.one).configure(self.rev(self.one), stage=2)
        proposal = self.proposal(self.one)
        Runtime(self.two).configure(self.rev(self.two), stage=3)
        with self.assertRaises(ConflictError):
            cg.apply_proposal(self.two, proposal, expected_revision=self.rev(self.two))

    def test_resealed_omitted_base_or_file_guards_rejected(self):
        for corrupt in ("base", "files"):
            with self.subTest(corrupt=corrupt):
                proposal = self.params(self.one, 7) if corrupt == "base" else self.proposal(self.one)
                if corrupt == "base":
                    proposal["base_objects"].pop("model.Q1")
                else:
                    proposal["file_snapshots"] = []
                proposal["proposal_id"] = digest({k: v for k, v in proposal.items() if k != "proposal_id"})
                before = Runtime(self.two).store.path.read_bytes()
                with self.assertRaises(IntegrityError):
                    cg.apply_proposal(self.two, proposal, expected_revision=self.rev(self.two))
                self.assertEqual(before, Runtime(self.two).store.path.read_bytes())

    def test_proposal_cannot_create_a_verified_run_or_include_sealed_files(self):
        with self.assertRaises(ValueError):
            self.proposal(self.one, "RunRecord", "fake.run", {"status": "verified"})
        with self.assertRaises(ValueError):
            self.proposal(self.one, files=["state/decision_log.json"])

    def test_unlisted_dirty_material_is_not_automatically_transferred(self):
        (self.one / "private-notes.txt").write_text("Synthetic private data; must not be copied by proposal", encoding="utf-8")
        proposal = self.proposal(self.one)
        self.assertIn("private-notes.txt", proposal["impact"]["unknown_paths"])
        self.assertNotIn("private-notes.txt", {x["path"] for x in proposal["file_snapshots"]})
        cg.apply_proposal(self.two, proposal, expected_revision=self.rev(self.two))
        self.assertFalse((self.two / "private-notes.txt").exists())

    def test_pr_draft_is_local_and_never_infers_tests_passed(self):
        proposal = self.proposal(self.one)
        draft = cg.draft_proposal(proposal)
        self.assertIn("未发送至 GitHub", draft)
        self.assertIn("未提供，不能填写测试通过", draft)
        self.assertEqual(proposal["tests_executed_by_adapter"], [])
        self.assertIn("received != adopted != verified", proposal["handoff_semantics"])
        with self.assertRaises(ValueError):
            cg.create_proposal(self.one, compare="HEAD", reason="bad test claim", action=proposal["action"],
                               test_receipts=[{"command": ["test"], "exit_code": 0, "log": "missing.log"}])
        self.observations["draft"] = draft

    def test_handoff_uses_actual_context_and_cumulative_receipts(self):
        view = cg.handoff(self.one, role="coder", member="member-coder", compare="HEAD")
        ctx = view["context"]
        ack = acknowledge(self.two, self.rev(self.two), ctx, member="member-coder", action="received")["result"]
        self.assertEqual(ack["adoptions"], [])
        self.assertEqual(ack["verifications"], [])
        acknowledge(self.two, self.rev(self.two), ctx, member="member-coder", action="adopted", object_ids=[self.ids["model"]])
        rt = Runtime(self.two)
        rt.configure(self.rev(self.two), stage=2)
        rt.configure(self.rev(self.two), stage=3)
        newer = cg.handoff(self.two, role="coder", member="member-coder")["context"]
        self.assertEqual(newer["changes_since"], ctx["source_revision"])
        self.assertEqual(len(newer["changes"]), 4)
        self.assertEqual(rt.read()["copilot"]["members"]["member-coder"]["verifications"], [])
        self.observations.update(original_handoff=view, next_context=newer)

    def test_handoff_drift_requires_explicit_reconcile(self):
        (self.one / "solver.py").write_text(SOLVER + "# drift", encoding="utf-8")
        with self.assertRaises(ConflictError):
            cg.handoff(self.one, role="coder")
        Runtime(self.one).reconcile(self.rev(self.one))
        ctx = cg.handoff(self.one, role="coder")["context"]
        self.assertIn(self.ids["code"], ctx["common"]["stale_objects"])

    def test_actual_merge_conflict_is_visible_and_not_adoptable(self):
        for root, value in ((self.one, "print('branch one')\n"), (self.two, "print('branch two')\n")):
            (root / "solver.py").write_text(value, encoding="utf-8")
            self.git(root, "add", "--", "solver.py")
            self.git(root, "commit", "-m", "conflicting fixture change")
        self.git(self.two, "fetch", str(self.one), "integration:refs/remotes/peer/integration")
        self.git(self.two, "merge", "--no-edit", "peer/integration", ok=(1,))
        report = cg.repository_status(self.two, "peer/integration")
        self.assertIn("solver.py", report["conflicts"])
        with self.assertRaises(ConflictError):
            self.proposal(self.two)
        self.observations["merge_conflict"] = report

    def test_protect_refuses_already_tracked_authority_without_changing_index(self):
        self.git(self.seed, "add", "-f", "--", "state/decision_log.json")
        before = (self.seed / ".git/index").read_bytes()
        with self.assertRaises(IntegrityError):
            cg.protect(self.seed)
        self.assertEqual(before, (self.seed / ".git/index").read_bytes())
        self.assertFalse(cg._marker(cg.LocalGit(self.seed)).exists())

    def test_fast_forward_valid_authority_cannot_bypass_plain_runtime_read(self):
        self.git(self.seed, "add", "-f", "--", "state/decision_log.json")
        self.git(self.seed, "commit", "-m", "deliberately unsafe tracked authority fixture")
        original = Runtime(self.one).store.path.read_bytes()
        (self.base / "authority-backup.json").write_bytes(original)
        # This disposable file is backed up above, enabling the otherwise
        # correctly refused overwrite of an untracked file in the test.
        (self.one / "state/decision_log.json").unlink()
        self.git(self.one, "fetch", "origin")
        self.git(self.one, "merge", "--ff-only", "origin/integration")
        self.assertEqual(original, (self.one / "state/decision_log.json").read_bytes())
        with self.assertRaises(IntegrityError):
            cg.assert_authority_boundary(self.one)
        with self.assertRaises(IntegrityError):
            Runtime(self.one).read()
        with self.assertRaises(IntegrityError):
            cg.verify_workspace(self.one)
        self.observations["blocked_reason"] = "same valid JSON bytes became Git-tracked; ordinary Store.read refused"

    def test_nested_unicode_project_and_worktree_protection(self):
        host = self.base / "host"
        nested = host / "teams/中文 with spaces"
        nested.mkdir(parents=True)
        rt, _, _ = make_project(nested, count=1)
        (host / "README.txt").write_text("unrelated repository root", encoding="utf-8")
        self.git(host, "init", "--initial-branch=integration")
        self.git(host, "add", "--", "README.txt")
        self.git(host, "commit", "-m", "nested fixture")
        cg.protect(nested)
        if os.name == "nt":
            Runtime(Path(str(nested).upper())).read()
        self.assertEqual(cg.repository_status(nested)["project_prefix"], "teams/中文 with spaces/")
        self.git(host, "check-ignore", "teams/中文 with spaces/state/decision_log.json")
        rt.configure(self.rev(nested), stage=2)
        self.git(host, "add", "-f", "--", "teams/中文 with spaces/state/decision_log.json")
        with self.assertRaises(IntegrityError):
            Runtime(nested).read()
        wt = self.base / "worktree"
        self.git(self.seed, "worktree", "add", "-b", "second-worktree", str(wt))
        shutil.copytree(self.seed / "state", wt / "state")
        self.assertTrue((wt / ".git").is_file())
        cg.protect(wt)
        Runtime(wt).configure(self.rev(wt), stage=4)
        self.assertEqual(Runtime(wt).read()["current_stage"], 4)
        self.observations["worktree_policy"] = cg.repository_status(wt)["authority_protection"]

    def test_file_integration_invalidates_actual_run_claim_and_paper(self):
        rt = Runtime(self.two)
        run_id = rt.execute(self.rev(self.two), "Q1", ["{python}", "solver.py"], ["result.json"],
                            dependencies=[self.ids[k] for k in ("model", "params", "data", "code", "plan")])["result"]["object_id"]
        validated = rt.validate_run(self.rev(self.two), run_id, "checker.py", ["{python}", "{checker}", "{run}", "{report}"])["result"]
        self.assertTrue(validated["passed"])
        run = rt.read()["copilot"]["objects"][run_id]["payload"]
        claim = rt.claim(self.rev(self.two), {"claim_id": "C1", "claim": "Computed length is 10 m.", "claim_type": "numerical",
            "paper_anchor": "results", "limitations": ["Synthetic fixture only"], "formal_run_id": run_id,
            "requirement_ids": ["REQ-Q1-001"], "data_sources": [run["data_hash"]], "code_locations": ["solver.py"],
            "tables": [run["outputs"][0]["path"]], "validation_evidence": ["Q1.run.formal"]}, [validated["result_id"]])["result"]["claim_id"]
        (self.two / "section.md").write_text("Computed length is 10 m. [[claim:" + claim + "]]\n", encoding="utf-8")
        section = Delivery(self.two).section(self.rev(self.two), "paper.results", "section.md", [claim])["result"]["section_id"]
        rt.cover(self.rev(self.two), "REQ-Q1-001", {"value": claim})
        before = cg.verify_workspace(self.two)
        self.assertTrue(before["passed"])
        authority = rt.store.path.read_bytes()
        (self.one / "solver.py").write_text(SOLVER + "# actual new committed source\n", encoding="utf-8")
        self.git(self.one, "add", "--", "solver.py")
        self.git(self.one, "commit", "-m", "changed source fixture")
        self.git(self.two, "fetch", str(self.one), "integration:refs/remotes/peer/integration")
        self.git(self.two, "merge", "--ff-only", "peer/integration")
        after = cg.verify_workspace(self.two)
        self.assertFalse(after["passed"])
        self.assertEqual(authority, rt.store.path.read_bytes())
        for oid in (run_id, validated["result_id"], claim, section):
            self.assertIn(oid, after["status"]["stale_objects"])
        self.assertEqual(after["status"]["requirements"]["verified"], 0)
        self.assertFalse(after["submission_ready"])
        self.observations.update(before=before, after=after)

    def test_cli_outputs_are_project_relative_exclusive_and_authority_readonly(self):
        before = Runtime(self.one).store.path.read_bytes()
        args = cg.parser().parse_args(["--workspace", str(self.one), "status", "--compare", "HEAD"])
        self.assertEqual(cg.execute(args)["comparison"]["status"], "known")
        proposal = self.proposal(self.one)
        cg._write_new(self.one, "handoff/proposal.json", proposal)
        draft_args = cg.parser().parse_args(["--workspace", str(self.one), "draft", "--proposal", "handoff/proposal.json", "--output", "handoff/pr-draft.md"])
        self.assertTrue(cg.execute(draft_args)["local_only"])
        with self.assertRaises(FileExistsError):
            cg.execute(draft_args)
        with self.assertRaises(ValueError):
            cg._write_new(self.one, ".git/config", "unsafe")
        self.assertEqual(before, Runtime(self.one).store.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
