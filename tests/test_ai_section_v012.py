"""AI disclosure boundaries use actual headings, not prose reference mentions."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from docx import Document
from copilot_delivery import _ai_checks
import copilot_document_checks as documents
from migrated.office_common import docx_structural_facts
from render_ai_usage import render_cumcm_no_use_statement


class ActualAISectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.statement = render_cumcm_no_use_statement(official=True)

    def audit(self, paragraphs):
        document = Document()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        path = self.root / "paper.docx"
        document.save(path)
        actual_text = docx_structural_facts(path)["text"]
        report, _ = _ai_checks(self.root, {"compliance":{"ai_usage":[]}},
            {"id":"cumcm", "rules":{"ai_declaration_position":{"value":"before_references"}},
                "required_checks":["ai_disclosure_passed"]},
            {"paper_source":{"version":"0.1"}}, actual_text, [])
        return report

    def test_real_docx_prose_reference_mentions_do_not_end_declaration(self):
        report = self.audit(["输入说明见参考文献[1]。", "AI 工具使用声明", "披露说明见参考文献[1]。",
            self.statement, "参考文献", "[1] Synthetic local source."])
        self.assertTrue(report["passed"], report)

    def test_reference_mention_cannot_replace_actual_heading(self):
        report = self.audit(["AI 工具使用声明", self.statement, "参考文献[1]提供更多说明。"])
        self.assertFalse(report["passed"])

    def test_declaration_after_true_references_remains_rejected(self):
        report = self.audit(["AI 工具使用声明", "披露说明见参考文献[1]。", "参考文献", self.statement])
        self.assertFalse(report["passed"])

    def test_statement_elsewhere_cannot_supply_ai_section(self):
        report = self.audit([self.statement, "AI 工具使用声明", "仅标题，不含声明。", "参考文献"])
        self.assertFalse(report["passed"])

    def test_missing_ai_section_is_not_authorized_by_global_literal(self):
        report = self.audit(["正文", self.statement, "参考文献"])
        self.assertFalse(report["passed"])

    def test_real_heading_spacing_uses_shared_migrated_rules(self):
        report = self.audit([" AI 工具 使用 声明 ", self.statement, "参 考 文 献"])
        self.assertTrue(report["passed"], report)

    def document_declaration_status(self):
        result = documents.audit_docx(self.root / "paper.docx",
            policy={"profile":"cumcm", "ai_before_references":True, "require_visual_qa":False},
            evaluation_mode="historical_benchmark")
        return next(x["status"] for x in result["findings"] if x["check_id"] == "docx.ai_statement_official_wording")

    def test_public_historical_document_accepts_prose_mention_before_unused_statement(self):
        self.audit(["AI 工具使用声明", "披露说明见参考文献[1]。", self.statement, "参考文献"])
        self.assertEqual(self.document_declaration_status(), "pass")

    def test_public_historical_document_accepts_used_statement_after_prose_mention(self):
        self.audit(["AI 工具使用声明", "工具见参考文献[1]。", "本次历史评测使用了AI工具。", "参考文献"])
        self.assertEqual(self.document_declaration_status(), "pass")

    def test_prose_mention_cannot_hide_later_conflicting_disclosure(self):
        self.audit(["AI 工具使用声明", "本次历史评测使用了AI工具。", "工具见参考文献[1]。",
            self.statement, "参考文献"])
        self.assertEqual(self.document_declaration_status(), "fail")

    def test_public_historical_document_rejects_statement_after_actual_references(self):
        self.audit(["AI 工具使用声明", "参考文献", "本次历史评测使用了AI工具。"])
        self.assertEqual(self.document_declaration_status(), "fail")


if __name__ == "__main__":
    unittest.main()
