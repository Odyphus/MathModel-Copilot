"""Behavioral regression and negative checks for migrated stateless contracts."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import copilot_domain as domain
import copilot_model_evidence as semantic
import copilot_document_checks as documents


class MigratedDomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="copilot-domain-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "problem.txt"
        self.source.write_text("Q1: Calculate the known quantity in metres.", encoding="utf-8")
        self.code = self.root / "solver.py"
        self.code.write_text("print(2 + 3)\n", encoding="utf-8")
        self.output = self.root / "result.csv"
        self.output.write_text("value\n5\n", encoding="utf-8")

    def contract(self):
        return {
            "question": "Q1", "title": "Known quantity",
            "source_files": [{"path": "problem.txt", "source_kind": "official_problem",
                              "sha256": domain.sha256_file(self.source)}],
            "requirements": [{"req_id": "REQ-Q1-001", "question": "Q1",
                              "source_anchor": "paragraph 1", "requested_action": "Calculate",
                              "outputs": ["value"], "acceptance_evidence": ["result.csv"],
                              "units": ["m"]}],
        }

    def dataset(self):
        inventory = domain.seal_record({"entries": [{"path": "result.csv", "sha256": domain.sha256_file(self.output)}]})
        passport = domain.seal_record({"fields": [{"name": "value", "unit": "m"}],
            "observation_unit": "specimen", "missing_policy": "reject missing values",
            "outlier_policy": "inspect each extreme", "repeated_measurements": True,
            "entity_id": "subject"})
        split = domain.seal_record({"strategy": "grouped_holdout", "split_unit": "subject",
            "preprocessing_scope": "train_fold_only", "leakage_controls": ["group isolation"],
            "train_entities": ["A"], "test_entities": ["B"]})
        return inventory, passport, split

    def run_payload(self):
        return domain.RunRecord.from_dict({"run_id": "RUN-1", "question": "Q1", "spec_id": "MS-Q1-1",
            "git_commit": "local-snapshot", "data_version": "data-v1", "data_hash": "A" * 64,
            "config_hash": "B" * 64, "repeat_count": 1, "seed": "0", "status": "completed",
            "outputs": [{"path": "result.csv", "sha256": domain.sha256_file(self.output)}]}).to_dict()

    def report(self, status="pass"):
        run = self.run_payload()
        return domain.seal_record({"record_type": "run_validation_report",
            **{key: run[key] for key in ("question", "spec_id", "git_commit", "data_version", "data_hash", "config_hash", "repeat_count", "outputs")},
            "status": status,
            "checks": [{"check_id": "known_solution", "status": status, "predeclared": True,
                        "criterion": "value equals five exactly", "evidence": ["result.csv"]}]})

    def test_seal_hashes_preserve_semantic_identity_but_detect_tampering(self):
        first = domain.seal_record({"stable_id": "A", "value": 5, "created_at": "old"})
        second = domain.seal_record({"stable_id": "B", "value": 5, "created_at": "new"})
        self.assertEqual(first["semantic_hash"], second["semantic_hash"])
        self.assertNotEqual(first["record_hash"], second["record_hash"])
        self.assertEqual([], domain.verify_sealed_record(first))
        first["value"] = 6
        self.assertIn("semantic_hash", ";".join(domain.verify_sealed_record(first)))

    def test_canonical_json_rejects_non_finite_numbers(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(domain.WorkflowError):
                domain.seal_record({"value": value})

    def test_frozen_contract_valid_and_source_drift_rejected(self):
        payload = self.contract()
        self.assertEqual([], domain.validate_problem_contract(self.root, payload, for_freeze=True))
        self.source.write_text("Q1 changed", encoding="utf-8")
        self.assertTrue(domain.validate_problem_contract(self.root, payload, for_freeze=True))

    def test_requirement_coverage_contract_rejects_duplicate_and_wrong_question(self):
        payload = self.contract()
        payload["requirements"].append(copy.deepcopy(payload["requirements"][0]))
        self.assertIn("ReqID", ";".join(domain.validate_problem_contract(self.root, payload)))
        payload = self.contract()
        payload["requirements"][0]["question"] = "Q2"
        self.assertTrue(domain.validate_problem_contract(self.root, payload))

    def test_contract_has_no_hidden_cumcm_register_reads(self):
        payload = self.contract()
        ambiguity = {"ambiguity_id": "AMB-1", "status": "open", "severity": "high"}
        self.assertTrue(domain.validate_problem_contract(self.root, payload, for_freeze=True, ambiguities=[ambiguity]))
        self.assertFalse((self.root / ".cumcm").exists())
        self.assertEqual([], domain.validate_problem_contract(self.root, payload, for_freeze=True))

    def test_contract_source_path_cannot_escape_workspace(self):
        payload = self.contract()
        payload["source_files"][0]["path"] = "../problem.txt"
        self.assertTrue(domain.validate_problem_contract(self.root, payload))

    def test_frozen_model_cannot_skip_contract_and_verification(self):
        spec = domain.ModelSpec(question="Q1", title="model", status="frozen",
                                observation_unit="specimen", objective={"direction": "min"})
        errors = domain.validate_modelspec_structure(spec)
        self.assertTrue(any("ProblemContract" in error for error in errors))
        self.assertTrue(any("validation_plan" in error for error in errors))

    def test_original_frozen_model_contract_accepts_complete_semantics(self):
        spec = domain.ModelSpec(question="Q1", title="closed form", status="frozen",
            objective={"formula_id": "OBJ-Q1-001", "direction": "calculate"}, observation_unit="item",
            inputs=[{"name": "known lengths"}], outputs=[{"name": "sum"}],
            data_contract={"mode": "given constants"}, solver={"method": "closed-form addition"},
            randomness={"seed_policy": "deterministic"},
            not_applicable_reasons={"constraints": "This deterministic identity has no feasibility constraints."},
            validation_plan=[{"check_id": "known_solution"}], failure_conditions=["sum differs from five"],
            required_outputs=["result.csv"], problem_contract_id="PC-Q1-1",
            problem_contract_semantic_hash="A"*64, requirement_ids=["REQ-Q1-001"],
            method_decision={"selected_route": "closed form", "candidates": [
                {"route": "closed form", "decision": "selected", "reason": "all terms known"}]})
        self.assertEqual([], domain.validate_modelspec_structure(spec))

    def test_human_parameter_cannot_be_relabelled_estimated_or_unchecked(self):
        parameter = domain.ParameterEntry(parameter_id="P1", symbol="w", meaning="weight", category="estimated",
                                           estimation_method="human_set manually")
        self.assertTrue(domain.validate_parameter_entries([parameter], formal=True))
        parameter.category = "human_set"
        parameter.basis = "prior range"
        parameter.candidate_range = [0, 1]
        parameter.affects_core_conclusion = True
        parameter.sensitivity_required = True
        parameter.sensitivity_plan = "vary the entire declared interval"
        self.assertTrue(domain.validate_parameter_entries([parameter], formal=True))

    def test_parameter_values_may_change_but_semantics_require_model_revision(self):
        expected = domain.ParameterEntry(parameter_id="P1", symbol="t", meaning="duration",
            unit="seconds", category="external", external_source="official paragraph 1", current_value=5)
        changed = copy.deepcopy(expected)
        changed.current_value = 6
        self.assertEqual([], domain.validate_parameter_contract([expected], [changed]))
        changed.unit = "minutes"
        self.assertTrue(domain.validate_parameter_contract([expected], [changed]))

    def test_parameter_and_run_roundtrip_keep_original_fields(self):
        p = domain.ParameterEntry(parameter_id="P1", symbol="c", meaning="given constant",
                                  category="external", external_source="problem paragraph 1")
        source = domain.ParameterSet(question="Q1", spec_id="M1", modelspec_semantic_hash="A"*64,
            modelspec_record_hash="B"*64, version=1, entries=[p]).to_dict()
        self.assertEqual(source, domain.ParameterSet.from_dict(source).to_dict())
        run = self.run_payload()
        self.assertEqual(run, domain.RunRecord.from_dict(run).to_dict())

    def test_unexecuted_run_template_never_defaults_to_completed(self):
        record = domain.RunRecord.from_dict({"question": "Q1"})
        self.assertEqual("not_executed", record.status)
        template = Path(__file__).resolve().parents[1] / "templates/copilot/formal_run.yaml"
        self.assertEqual("not_executed", domain.load_structured(template)["status"])

    def test_data_contract_is_valid_then_detects_file_drift(self):
        inv, passport, split = self.dataset()
        self.assertEqual([], domain.validate_data_contract(self.root, inv, passport, split))
        self.output.write_text("value\n6\n", encoding="utf-8")
        self.assertTrue(domain.validate_data_contract(self.root, inv, passport, split))

    def test_repeated_subject_leakage_and_full_data_preprocessing_are_rejected(self):
        inv, passport, split = self.dataset()
        split.update(train_entities=["A"], test_entities=["A"], strategy="random_row", split_unit="row",
                     preprocessing_scope="full data")
        errors = domain.validate_data_contract(self.root, inv, passport, domain.seal_record(split))
        self.assertGreaterEqual(len(errors), 3)

    def test_no_data_requires_explicit_reasons_and_no_false_generalization(self):
        passport = domain.seal_record({"applicability": "not_applicable", "not_applicable_reason": "pure symbolic derivation without observations"})
        split = domain.seal_record({"applicability": "not_applicable", "not_applicable_reason": "there are no fitted or evaluated data"})
        self.assertEqual([], domain.validate_data_contract(self.root, None, passport, split))
        split = domain.seal_record({**split, "test_entities": ["A"]})
        self.assertTrue(domain.validate_data_contract(self.root, None, passport, split))

    def test_data_inventory_outside_path_is_rejected_even_if_file_exists(self):
        inv, passport, split = self.dataset()
        inv = domain.seal_record({"entries": [{"path": str(self.output), "sha256": domain.sha256_file(self.output)}]})
        self.assertTrue(domain.validate_data_contract(self.root, inv, passport, split))

    def test_future_observations_do_not_claim_new_entities(self):
        plan = {"strategy": "temporal_holdout", "time_order_field": "time", "split_unit": "time",
                "claims_new_entity_generalization": False, "claim_boundary": "known entities only",
                "final_evaluation_reused": False, "train_time_range": [1, 5], "test_time_range": [6, 8],
                "preprocessing_time_range": [1, 5], "selection_time_range": [1, 5]}
        self.assertEqual([], semantic.temporal_split_errors(plan, {"A"}, {"A"}))
        plan["selection_time_range"] = [1, 8]
        self.assertTrue(semantic.temporal_split_errors(plan, {"A"}, {"A"}))

    def test_validation_plan_rejects_empty_and_duplicate_checks(self):
        self.assertTrue(domain.validate_validation_plan({"checks": []}))
        check = {"check_id": "x", "method": "independent replay"}
        self.assertTrue(domain.validate_validation_plan({"checks": [check, check]}))

    def test_requirement_scalar_outputs_cannot_masquerade_as_a_list(self):
        payload = self.contract()
        payload["requirements"][0]["outputs"] = "result.csv"
        self.assertTrue(domain.validate_problem_contract(self.root, payload))

    def test_valid_report_is_bound_to_run_and_actual_output(self):
        report = self.report()
        run = self.run_payload()
        self.assertEqual([], domain.validate_run_report(self.root, report, run, {"known_solution"}))
        self.output.write_text("value\n100\n", encoding="utf-8")
        self.assertTrue(domain.validate_run_report(self.root, report, run, {"known_solution"}))

    def test_unknown_or_unexecuted_check_is_not_passing_report(self):
        report = self.report()
        report["checks"][0]["status"] = "not_executed"
        self.assertTrue(domain.validate_run_report(self.root, domain.seal_record(report), self.run_payload(), {"known_solution"}))
        report = self.report()
        report["checks"][0]["status"] = "not_applicable"
        report["checks"][0]["reason"] = "not required for this model"
        self.assertTrue(domain.validate_run_report(self.root, domain.seal_record(report), self.run_payload(), {"known_solution"}))

    def test_report_cannot_hide_failure_or_missing_planned_check(self):
        report = self.report()
        report["checks"][0]["status"] = "fail"
        self.assertTrue(domain.validate_run_report(self.root, domain.seal_record(report), self.run_payload(), {"known_solution"}))
        self.assertTrue(domain.validate_run_report(self.root, self.report(), self.run_payload(), {"other"}))

    def test_duplicate_report_check_cannot_mask_identity_collision(self):
        report = self.report()
        report["checks"].append(copy.deepcopy(report["checks"][0]))
        self.assertTrue(domain.validate_run_report(self.root, domain.seal_record(report), self.run_payload(), {"known_solution"}))

    def test_failure_report_remains_valid_record_but_not_pass(self):
        report = self.report("fail")
        self.assertEqual([], domain.validate_run_report(self.root, report, self.run_payload(), {"known_solution"}))
        self.assertEqual("fail", report["status"])

    def test_code_manifest_binds_actual_source_and_snapshot(self):
        manifest = domain.seal_record({"record_type": "code_manifest", "question": "Q1", "spec_id": "M1",
            "modelspec_semantic_hash": "A"*64, "revision_id": "snapshot-1",
            "files": [{"path": "solver.py", "sha256": domain.sha256_file(self.code)}]})
        kwargs = dict(expected_question="Q1", expected_spec_id="M1", expected_modelspec_hash="A"*64, expected_revision="snapshot-1")
        self.assertEqual([], domain.validate_code_manifest(self.root, manifest, **kwargs))
        self.code.write_text("print(6)\n", encoding="utf-8")
        self.assertTrue(domain.validate_code_manifest(self.root, manifest, **kwargs))

    def test_repeat_ledger_retains_failed_repeats(self):
        ledger = domain.seal_record({"record_type": "repeat_ledger", "root_seed": "0",
                                    "entries": [{"repeat_index": 1, "seed": "0", "status": "failed"}]})
        self.assertTrue(domain.validate_repeat_ledger(ledger, expected_count=1, expected_seed="0"))

    def test_impact_is_transitive_cycle_safe_and_does_not_touch_other_branch(self):
        edges = [dict(from_id=a, to_id=b, to_type="artifact", relation="uses", stable_id=a+b, invalidates=active)
                 for a, b, active in [("P1", "R1", True), ("R1", "C1", True), ("C1", "P1", True),
                                     ("P1", "independent", False), ("P2", "R2", True)]]
        before = copy.deepcopy(edges)
        result = domain.impact_analysis(edges, "P1")
        self.assertEqual({"R1", "C1"}, {item["id"] for item in result["impacted"]})
        self.assertEqual(before, edges)

    def test_unsupported_claim_cannot_use_own_pass_or_noncurrent_run(self):
        claim = domain.EvidenceMapEntry(claim_id="C1", claim="value is five", paper_anchor="section-1",
            formal_run_id="RUN-1", data_sources=["data-v1"], code_locations=["solver.py"],
            tables=["result.csv"], validation_evidence=["Q1.run.formal"], status="pass")
        self.assertEqual([], domain.validate_evidence_entry(self.root, claim, self.run_payload(), run_is_current_verified=True))
        self.assertTrue(domain.validate_evidence_entry(self.root, claim, self.run_payload(), run_is_current_verified=False))
        claim.tables = ["missing.csv"]
        self.assertTrue(domain.validate_evidence_entry(self.root, claim, self.run_payload(), run_is_current_verified=True))

    def test_semantic_reference_cannot_copy_same_implementation_as_independent_truth(self):
        payload = {"checks": [{"kind": "formula_equivalence", "reference_values": [5], "actual_values": [5],
                               "reference_basis": "same solver", "implementation_basis": "same solver"}]}
        self.assertTrue(semantic.check_semantic_evidence(payload))

    def test_no_checker_creates_second_state_or_modifies_inputs(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        domain.validate_problem_contract(self.root, self.contract())
        domain.validate_run_report(self.root, self.report(), self.run_payload(), {"known_solution"})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertFalse((self.root / ".cumcm").exists())


class MigratedDocumentChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="copilot-document-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_zip_rejects_undeclared_members_and_pack_size_limit(self):
        path = self.root / "support.zip"
        payload = {"schema_version": "cumcm.supporting_materials_manifest/v1", "mode": "package", "files": []}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("supporting_materials_manifest.yaml", json.dumps(payload))
            archive.writestr("unlisted.txt", "extra")
        from migrated.supporting_materials import audit_supporting_zip
        result = audit_supporting_zip(path, max_zip_bytes=1)
        self.assertFalse(result["passed"])
        self.assertGreaterEqual(len(result["errors"]), 2)

    def test_manifest_rejects_authoritative_state_as_supporting_material(self):
        (self.root / "state").mkdir()
        state = self.root / "state/decision_log.json"
        state.write_text("{}", encoding="utf-8")
        from migrated.supporting_materials import _path_policy_error
        self.assertIsNotNone(_path_policy_error("state/decision_log.json", "data"))

    def test_valid_zip_for_different_manifest_snapshot_is_rejected(self):
        instructions = self.root / "instructions.txt"
        instructions.write_text("No program was needed; inspect the algebraic derivation.", encoding="utf-8")
        payload = {"schema_version": "cumcm.supporting_materials_manifest/v1", "mode": "package",
            "run_instructions": "instructions.txt", "program": {"mode": "no_program",
            "official_no_program_statement": "No program was used in this derivation."},
            "files": [{"path": "instructions.txt", "kind": "run_instructions", "purpose": "reproduction",
                "questions": ["Q1"], "evidence_ids": ["C1"], "submit": True,
                "bytes": instructions.stat().st_size, "sha256": domain.sha256_file(instructions)}]}
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        archive_path = self.root / "support.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("supporting_materials_manifest.yaml", json.dumps(payload))
            archive.writestr("instructions.txt", instructions.read_bytes())
        result = documents.audit_supporting_materials(self.root, manifest, zip_path=archive_path, policy={})
        self.assertTrue(result["passed"], result)
        payload["notes"] = "new selected snapshot"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        result = documents.audit_supporting_materials(self.root, manifest, zip_path=archive_path, policy={})
        self.assertFalse(result["passed"])
        self.assertIn("differs", ";".join(result["checks"]["zip"]["errors"]))

    def test_document_policy_does_not_use_cumcm_defaults_for_generic_pack(self):
        self.assertEqual({}, documents._policy({}))
        with self.assertRaises(ValueError):
            documents.audit_pdf(self.root / "missing.pdf", policy={"profile": "cumcm"})
        with self.assertRaises(ValueError):
            documents._policy({"paper_max_bytes": True})

    @unittest.skipUnless(importlib.util.find_spec("lxml"), "lxml is optional")
    def test_docx_source_read_only_detects_missing_metadata_and_formula_failure(self):
        path = self.root / "paper.docx"
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Evidence-backed content.</w:t></w:r></w:p></w:body></w:document>'
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", xml)
        original = path.read_bytes()
        result = documents.audit_docx(path, policy={"profile": "generic", "require_visual_qa": True})
        self.assertFalse(result["passed"])
        self.assertEqual(original, path.read_bytes())
        self.assertEqual([path], list(self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
