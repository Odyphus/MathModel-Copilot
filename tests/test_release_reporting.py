"""Release reports must not turn environment gaps into product passes/failures."""
import unittest
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_release as reporting
from verify_release import classify_outcome


class ReleaseReportingTests(unittest.TestCase):
    def test_missing_external_package_is_distinct_from_bad_product_import(self):
        self.assertEqual(classify_outcome("error", "ModuleNotFoundError: No module named 'unidiff'", ["unidiff"]), "dependency_missing")
        self.assertEqual(classify_outcome("error", "ImportError: cannot import name 'missing_api' from copilot_context", []), "code_error")
        self.assertEqual(classify_outcome("error", "ModuleNotFoundError: No module named 'misspelled_local_module'", ["unidiff"]), "code_error")
        self.assertEqual(classify_outcome("error", "RuntimeError: No module named 'unidiff'", ["unidiff"]), "code_error")

    def test_external_tools_missing_dependencies_and_explicit_skips_are_distinct(self):
        self.assertEqual(classify_outcome("skip", "XeLaTeX with ctexart.cls is not installed"), "external_tool_missing")
        self.assertEqual(classify_outcome("skip", "2018B requires optional xlrd and xlwt", ["xlrd", "xlwt"]), "dependency_missing")
        self.assertEqual(classify_outcome("skip", "xlrd is not installed", ["xlrd"]), "dependency_missing")
        self.assertEqual(classify_outcome("skip", "Explicitly disabled costly optional experiment"), "explicit_skip")

    def test_missing_historical_fixture_is_explicit_without_masking_code_errors(self):
        reason = "historical_fixture_missing: official_parameters.json"
        self.assertEqual(classify_outcome("skip", reason), "fixture_missing")
        self.assertEqual(classify_outcome("error", reason), "code_error")
        self.assertEqual(classify_outcome("fail", reason), "assertion_failure")

    def test_assertions_do_not_become_passes_or_dependency_errors(self):
        self.assertEqual(classify_outcome("fail", "AssertionError: mismatch", ["unidiff"]), "assertion_failure")
        self.assertEqual(classify_outcome("pass", None, ["unidiff"]), "passed")

    def test_assertion_text_cannot_impersonate_an_import_error(self):
        reason = "AssertionError: expected No module named 'unidiff'"
        self.assertEqual(classify_outcome("fail", reason, ["unidiff"]), "assertion_failure")
        self.assertEqual(classify_outcome("subtest_fail", reason, ["unidiff"]), "assertion_failure")

    def test_mentioning_a_module_does_not_make_an_explicit_skip_a_dependency_gap(self):
        self.assertEqual(classify_outcome("skip", "Explicitly disabled xlrd stress experiment", ["xlrd"]), "explicit_skip")
        self.assertEqual(classify_outcome("skip", "Explicitly disabled compilation experiment", ["PIL"]), "explicit_skip")
        self.assertEqual(classify_outcome("skip", "dependency_missing: xlrd is unavailable", ["xlrd"]), "dependency_missing")

    def test_recorded_subtests_keep_assertion_and_code_error_distinct(self):
        class MixedSubtests(unittest.TestCase):
            def runTest(self):
                with self.subTest(kind="assertion"):
                    self.fail("expected No module named 'unidiff'")
                with self.subTest(kind="exception"):
                    raise RuntimeError("broken operation")
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=reporting.RecordedResult).run(MixedSubtests())
        self.assertEqual(["fail", "error"], [item["status"] for item in result.records])
        self.assertEqual(["assertion_failure", "code_error"], [
            classify_outcome(item["status"], item["reason"], ["unidiff"]) for item in result.records])
        self.assertEqual(1, len(result.failures))
        self.assertEqual(1, len(result.errors))
        self.assertFalse(result.wasSuccessful())


class ReleaseStatusTests(unittest.TestCase):
    def result(self, outcome="pass"):
        class Fixture(unittest.TestCase):
            def runTest(self):
                if outcome == "skip":
                    self.skipTest("historical_fixture_missing: omitted.pdf")
                elif outcome == "fail":
                    self.fail("ordinary assertion failure")
                elif outcome == "error":
                    raise ModuleNotFoundError("No module named 'unidiff'")
        return unittest.TextTestRunner(stream=io.StringIO(), resultclass=reporting.RecordedResult).run(Fixture())

    def test_passing_selected_checks_never_claims_complete_release_acceptance(self):
        report = reporting.verification_outcome(self.result(), [], [{"returncode": 0}])
        self.assertEqual("pass", report["status"])
        self.assertTrue(report["success"])
        self.assertFalse(report["full_acceptance"])

    def test_missing_fixture_is_partial_success_and_preserves_zero_passes(self):
        result = self.result("skip")
        report = reporting.verification_outcome(result, [], [{"returncode": 0}])
        self.assertEqual("partial_pass", report["status"])
        self.assertTrue(report["success"])
        self.assertFalse(report["full_acceptance"])
        self.assertEqual(0, sum(item["status"] == "pass" for item in result.records))
        self.assertEqual(1, len(result.skipped))

    def test_optional_environment_gap_is_partial_without_suppressing_real_errors(self):
        report = reporting.verification_outcome(self.result(), ["xlrd"], [{"returncode": 0}])
        self.assertEqual("partial_pass", report["status"])
        self.assertTrue(report["success"])
        for outcome in ("fail", "error"):
            with self.subTest(outcome=outcome):
                report = reporting.verification_outcome(self.result(outcome), ["unidiff"], [{"returncode": 0}])
                self.assertEqual("fail", report["status"])
                self.assertFalse(report["success"])

    def test_command_failure_or_timeout_remains_failure(self):
        for code in (1, None):
            with self.subTest(returncode=code):
                report = reporting.verification_outcome(self.result("skip"), [], [{"returncode": code}])
                self.assertEqual("fail", report["status"])
                self.assertFalse(report["success"])

    def test_no_selected_tests_is_partial_not_complete(self):
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=reporting.RecordedResult).run(unittest.TestSuite())
        self.assertEqual("partial_pass", reporting.verification_outcome(result, [], [{"returncode": 0}])["status"])


if __name__ == "__main__":
    unittest.main()
