"""Current declaration output must satisfy the existing official-form checker."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_ai_usage import render_cumcm_use_statement, render_cumcm_no_use_statement
from migrated.cumcm_ai_declaration import classify_ai_declaration


class OfficialDeclarationTests(unittest.TestCase):
    def test_used_statement_roundtrips_through_independent_migrated_checker(self):
        entry = SimpleNamespace(tool="Codex", model="recorded-model", version="recorded-version", purpose="检查章节装配与图表引用")
        statement = render_cumcm_use_statement([entry], official=True)
        kind, purpose = classify_ai_declaration("AI 工具使用声明\n" + statement + "参考文献\n")
        self.assertEqual(kind, "used")
        self.assertEqual(purpose, entry.purpose)

    def test_unused_statement_roundtrips_and_does_not_claim_human_review(self):
        text = render_cumcm_no_use_statement(official=True)
        kind, _ = classify_ai_declaration("AI 工具使用声明\n" + text + "参考文献\n")
        self.assertEqual(kind, "not_used")
        self.assertNotIn("人工核验通过", text)

    def test_empty_used_ledger_cannot_emit_official_use_statement(self):
        with self.assertRaises(ValueError):
            render_cumcm_use_statement([], official=True)

    def test_legacy_wording_is_compatible_but_not_relabelled_official(self):
        text = render_cumcm_no_use_statement()
        kind, _ = classify_ai_declaration("AI 工具使用声明\n" + text + "参考文献\n")
        self.assertEqual(kind, "invalid")


if __name__ == "__main__":
    unittest.main()
