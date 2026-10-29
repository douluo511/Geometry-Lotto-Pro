"""DLT application intake must not treat Jiangsu publication dates as draw dates.

These are invented synthetic page bodies, not authentic lottery records.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from glp.sources import PARSER_VERSION, SourceError, _parse_jiangsu_html


def page(date_label="开奖日期", date_text="2026-10-28"):
    return (
        "<table><tr><td>" + date_label + "</td><td>期号</td>"
        "<td>开奖号码</td><td>详细</td></tr>"
        "<tr><td>" + date_text + "</td><td>26123</td>"
        "<td>01 02 03 04 05 06 07</td><td>synthetic</td></tr>"
        "</table>"
    )


class JiangsuApplicationDateSemanticsTests(unittest.TestCase):
    def test_behavior_change_requires_new_parser_evidence_version(self):
        self.assertEqual(PARSER_VERSION, "dlt-source-parser-v3-draw-date-guard")

    def test_publication_date_must_not_be_admitted_as_draw_date(self):
        with self.assertRaisesRegex(SourceError, "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE"):
            _parse_jiangsu_html(page("发布日期", "2026-10-29"))

    def test_headerless_candidate_must_not_be_admitted(self):
        with self.assertRaisesRegex(SourceError, "JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"):
            _parse_jiangsu_html("<table><tr><td>2026-10-29</td><td>26123</td>"
                                "<td>01 02 03 04 05 06 07</td></tr></table>")

    def test_decoy_safe_header_does_not_override_publication_table(self):
        with self.assertRaisesRegex(SourceError, "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE"):
            _parse_jiangsu_html(page().replace("<tr><td>2026-10-28", "</table><table><tr><td>发布日期"
                                               "</td><td>期号</td><td>开奖号码</td></tr>"
                                               "<tr><td>2026-10-28", 1))

    def test_explicit_draw_date_table_retains_original_number_parsing(self):
        rows = _parse_jiangsu_html(page())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].issue, "26123")
        self.assertEqual(rows[0].draw_date, "2026-10-28")
        self.assertEqual(rows[0].front, (1, 2, 3, 4, 5))
        self.assertEqual(rows[0].back, (6, 7))


if __name__ == "__main__":
    unittest.main()
