"""A shared appendix page must not hide a body-page limit violation."""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from migrated.pdf_audit import _paper_segments, audit_pdf

ABSTRACT = "历史复现报告\n摘要\n这里描述真实运行及结论边界。\n关键词 调度 验证"


class PdfSegmentsV011Tests(unittest.TestCase):
    def test_body_and_appendix_share_one_page(self):
        pages = [ABSTRACT, "1 问题与数据\n正文", "7 结论\n已核验结果。\n参考文献\n真实来源。\n附录 复核材料\n附录正文。"]
        result = _paper_segments(pages)
        self.assertEqual((result["body_start_page"], result["body_end_page"], result["body_pages"]), (2, 3, 2))

    def test_separate_appendix_page_without_prefix_is_excluded(self):
        result = _paper_segments([ABSTRACT, "1 问题与数据\n正文", "\n 附录 A 程序\n附录正文"])
        self.assertEqual((result["body_end_page"], result["body_pages"]), (2, 1))

    def test_paper_without_appendix_counts_last_page(self):
        result = _paper_segments([ABSTRACT, "1 问题与数据\n正文", "2 结果\n结论和参考文献"])
        self.assertEqual((result["body_end_page"], result["body_pages"]), (3, 2))

    def test_ambiguous_header_or_footer_prefix_is_counted_conservatively(self):
        for prefix in ("3\n", "论文页眉\n", "已核验结果\n"):
            with self.subTest(prefix=prefix):
                result = _paper_segments([ABSTRACT, "1 问题与数据\n正文", prefix + "附录 A 程序\n附录正文"])
                self.assertEqual(result["body_pages"], 2)

    def test_thirty_page_limit_cannot_be_bypassed_by_shared_appendix(self):
        thirty = [ABSTRACT, "1 问题与数据\n正文"] + ["正文继续"] * 29
        separate = _paper_segments(thirty + ["附录 A 程序\n程序清单"])
        self.assertEqual(separate["body_pages"], 30)
        shared = _paper_segments(thirty + ["结论仍属于正文。\n附录 A 程序\n程序清单"])
        self.assertEqual(shared["body_pages"], 31)
        self.assertGreater(shared["body_pages"], 30)

    def test_public_audit_rejects_shared_thirty_first_body_page(self):
        """Stub only PDF extraction; exercise the real audit finding and limit."""
        thirty = [ABSTRACT, "1 问题与数据\n正文"] + ["正文继续"] * 29
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reader-fixture.pdf"
            path.write_bytes(b"test input; page extraction is stubbed")
            for appendix, expected in (("附录 A 程序\n程序清单", "pass"),
                                       ("结论仍属于正文。\n附录 A 程序\n程序清单", "fail")):
                pages = [SimpleNamespace(
                    extract_text=lambda value=value: value,
                    mediabox=SimpleNamespace(width=595.276, height=841.890),
                    get=lambda key: None,
                ) for value in thirty + [appendix]]
                reader = SimpleNamespace(pages=pages, is_encrypted=False, metadata={})
                with self.subTest(expected=expected), patch("migrated.pdf_audit.PdfReader", return_value=reader):
                    report = audit_pdf(path, require_visual_qa=False, body_max_pages=30)
                    finding = next(item for item in report["findings"] if item["check_id"] == "pdf.paper_segments")
                    self.assertEqual(finding["status"], expected)


if __name__ == "__main__":
    unittest.main()
