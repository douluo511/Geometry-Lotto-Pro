"""Synthetic histories exercise real DLT parsing; never official draw evidence."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import unittest
from datetime import date, timedelta

from research.harness_v46 import official_intake as oi


CHILD = r"""
import base64, copy, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'DLT' / 'src'))
from glp import sources
from research.harness_v46 import official_intake as oi
pages = json.loads(sys.stdin.read())
artifacts = [{'http_status': 200, 'raw_base64': raw} for raw in pages]
before = copy.deepcopy(artifacts)
try:
    rows = oi._reparse_raw_history('DLT', sources, 'jiangsu', artifacts)
    result = {'status': 'PARSED', 'count': len(rows),
              'first': rows[0], 'last': rows[-1]}
except Exception as exc:
    result = {'status': 'BLOCKED', 'exception': type(exc).__name__,
              'error': str(exc)}
result['artifacts_unchanged'] = artifacts == before
print(json.dumps(result, ensure_ascii=True))
"""


def synthetic_rows(start=0, count=120):
    """Invented, valid 5+2 rows, with 120 monotonically increasing dates."""
    rows = []
    for index in range(start, start + count):
        day = (date(2025, 1, 1) + timedelta(days=index)).isoformat()
        rows.append(f"<tr><td>{day}</td><td>{25001 + index}</td>"
                    "<td>01 02 03 04 05 01 02</td><td>synthetic</td></tr>")
    return "".join(rows)


def header(first="开奖日期", *, tag="td"):
    # Retained Jiangsu pages use td headers, including these inline styles.
    return (f'<tr><{tag} style="background-color:#efefef;font-weight:bold;'
            f'text-align:center;">{first}</{tag}>'
            f'<{tag}>期号</{tag}><{tag}>开奖号码</{tag}><{tag}>详细</{tag}></tr>')


def table(body, first="开奖日期"):
    return "<table>" + header(first) + body + "</table>"


class JiangsuDateSemanticsTests(unittest.TestCase):
    def replay(self, *pages):
        child = subprocess.run(
            [sys.executable, "-c", CHILD], cwd=oi.REPO_ROOT,
            input=json.dumps([base64.b64encode(page.encode("utf-8")).decode("ascii")
                              for page in pages]),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertTrue(result["artifacts_unchanged"])
        return result

    def assert_blocked(self, pages, reason="JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"):
        result = self.replay(*pages)
        self.assertEqual(result["status"], "BLOCKED", result)
        self.assertEqual(result["exception"], "GateError", result)
        self.assertIn(reason, result["error"])

    def assert_synthetic_120(self, *pages):
        result = self.replay(*pages)
        self.assertEqual(result["status"], "PARSED", result)
        self.assertEqual(result["count"], 120)
        self.assertEqual(result["first"], {
            "issue": "25001", "draw_date": "2025-01-01",
            "front": [1, 2, 3, 4, 5], "back": [1, 2],
        })
        self.assertEqual(result["last"]["issue"], "25120")

    def test_retained_publication_header_cannot_define_draw_dates(self):
        self.assert_blocked([table(synthetic_rows(), "发布日期")],
                            "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_ambiguous_date_or_time_header_cannot_define_draw_dates(self):
        for label in ("日期", "时间", "Date", "发布日期/开奖日期"):
            with self.subTest(label=label):
                self.assert_blocked([table(synthetic_rows(), label)])

    def test_candidate_rows_without_table_header_are_blocked(self):
        self.assert_blocked(["<table>" + synthetic_rows() + "</table>"])

    def test_header_after_candidate_rows_cannot_authorize_earlier_rows(self):
        self.assert_blocked(["<table>" + synthetic_rows() + header() + "</table>"])

    def test_shifted_header_cannot_authorize_first_column(self):
        shifted = "<tr><td>期号</td><td>开奖日期</td><td>开奖号码</td></tr>"
        self.assert_blocked(["<table>" + shifted + synthetic_rows() + "</table>"])

    def test_shifted_issue_and_number_headers_are_blocked(self):
        shifted = "<tr><td>开奖日期</td><td>开奖号码</td><td>期号</td></tr>"
        self.assert_blocked(["<table>" + shifted + synthetic_rows() + "</table>"])

    def test_safe_header_in_decoy_table_does_not_authorize_other_table(self):
        page = table("") + table(synthetic_rows(), "发布日期")
        self.assert_blocked([page], "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_every_candidate_table_must_have_draw_date_semantics(self):
        safe = table(synthetic_rows(0, 60))
        unsafe = table(synthetic_rows(60, 60), "发布日期")
        for page in (safe + unsafe, unsafe + safe):
            with self.subTest(unsafe_first=page.startswith(unsafe)):
                self.assert_blocked([page], "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_every_nonempty_candidate_page_must_have_verified_headers(self):
        self.assert_blocked([table(synthetic_rows(0, 60)),
                             table(synthetic_rows(60, 60), "日期")])

    def test_conflicting_headers_in_same_table_block(self):
        for extra, reason in ((header("发布日期"), "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE"),
                              (header("日期"), "JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED")):
            with self.subTest(extra=extra):
                self.assert_blocked(["<table>" + header() + extra +
                                     synthetic_rows() + "</table>"], reason)

    def test_conflicting_header_after_rows_blocks_entire_table(self):
        self.assert_blocked(["<table>" + header() + synthetic_rows() +
                             header("发布日期") + "</table>"],
                            "JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_nested_header_in_foreign_table_cannot_authorize_outer_rows(self):
        nested = "<tr><td>" + table("") + "</td></tr>"
        self.assert_blocked(["<table>" + nested + synthetic_rows() + "</table>"])

    def test_orphan_rows_cannot_borrow_header_from_closed_table(self):
        self.assert_blocked([table("") + synthetic_rows()])

    def test_header_in_comment_or_script_does_not_authorize_table(self):
        for decoy in ("<!--" + header() + "-->", "<script>" + header() + "</script>"):
            with self.subTest(decoy=decoy):
                self.assert_blocked(["<table>" + decoy + synthetic_rows() + "</table>"])

    def test_unclosed_or_nested_candidate_markup_is_blocked(self):
        good = table(synthetic_rows())
        malformed = (
            good.removesuffix("</table>"),
            good.replace("</tr>", "", 1),
            good.replace("</td>", "", 1),
            "<table><tr><td>" + good + "</td></tr></table>",
        )
        for page in malformed:
            with self.subTest(page=page[:160]):
                self.assert_blocked([page])

    def test_spanning_header_or_data_cells_are_not_positionally_verified(self):
        pages = (table(synthetic_rows()).replace("<td style=", '<td colspan="2" style=', 1),
                 table(synthetic_rows()).replace("<td>2025", '<td rowspan="2">2025', 1))
        for page in pages:
            with self.subTest(page=page[:160]):
                self.assert_blocked([page])

    def test_explicit_draw_date_header_uses_actual_existing_dlt_parser(self):
        self.assert_synthetic_120(table(synthetic_rows()))

    def test_inline_tags_entities_and_explicit_draw_time_header_are_supported(self):
        for label in ("<span>开奖</span>&#26085;&#26399;&nbsp;", "<b>开奖</b> 时间"):
            with self.subTest(label=label):
                self.assert_synthetic_120("<table>" + header(label, tag="th") +
                                          synthetic_rows() + "</table>")

    def test_detail_links_in_extra_column_preserve_verified_date_binding(self):
        body = synthetic_rows().replace("synthetic</td>",
                                        '<a href="/synthetic-detail">synthetic</a></td>')
        self.assert_synthetic_120(table(body))

    def test_void_linebreak_in_header_preserves_explicit_draw_date_label(self):
        self.assert_synthetic_120(table(synthetic_rows(), "开奖<br/>日期"))

    def test_double_encoded_header_is_not_an_explicit_draw_date_label(self):
        label = "&amp;#24320;&amp;#22870;&amp;#26085;&amp;#26399;"
        self.assert_blocked([table(synthetic_rows(), label)])

    def test_each_valid_table_or_page_keeps_its_own_header(self):
        first = table(synthetic_rows(0, 60))
        last = table(synthetic_rows(60, 60))
        self.assert_synthetic_120(first + last)
        self.assert_synthetic_120(first, last)

    def test_no_candidate_terminal_response_does_not_invent_draws(self):
        self.assert_synthetic_120(table(synthetic_rows()),
                                  "<table>" + header("发布日期") + "</table>")


if __name__ == "__main__":
    unittest.main()
