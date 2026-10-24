"""Invented transport bodies exercise the actual recent DLT parser subprocess.

Only HTTP is doubled. The publication-versus-draw admission decision, complete
row parsing, raw preservation and failure to create a manifest are real.
"""
import hashlib
import html
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from research.harness_v46 import recent_observation as ro
from research.harness_v46.tests.test_recent_observation import rows


def header(label="开奖日期", tag="th"):
    return (f'<tr><{tag} style="background-color:#efefef;font-weight:bold;'
            f'text-align:center;">{label}</{tag}>'
            f'<{tag} style="font-weight:bold">期号</{tag}>'
            f'<{tag} style="font-weight:bold">开奖号码</{tag}>'
            f'<{tag} style="font-weight:bold">详细</{tag}></tr>')


def body(records):
    return "".join(
        f'<tr><td>{row["draw_date"]}</td><td>{row["issue"]}</td>'
        '<td>01 02 03 04 05 06 07</td><td>synthetic</td></tr>'
        for row in reversed(records)
    )


def page(records, label="开奖日期", tag="th"):
    return "<table>" + header(label, tag) + body(records) + "</table>"


class RecentObservationDateSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "observation"
        self.records = rows("DLT")

    def capture(self, pages):
        encoded = [text.encode("utf-8") for text in pages]
        seen = []

        def get(url, **kwargs):
            self.assertIs(kwargs.get("allow_redirects"), False)
            self.assertIs(kwargs.get("stream"), True)
            raw = encoded[len(seen)]
            seen.append(url)
            return SimpleNamespace(status_code=200, url=url,
                                   iter_content=lambda chunk_size: iter([raw]),
                                   close=lambda: None,
                                   headers={"Content-Type": "text/html; charset=utf-8"})

        with patch("requests.get", side_effect=get):
            result = ro.capture("DLT", self.output)
        return result, seen

    def assert_blocked(self, first, *, reason="JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"):
        second = page(self.records[:100])
        with self.assertRaisesRegex(Exception, reason):
            self.capture([first, second])
        first_bytes = first.encode("utf-8")
        saved = self.output / "raw" / (hashlib.sha256(first_bytes).hexdigest() + ".bin")
        self.assertEqual(saved.read_bytes(), first_bytes)
        self.assertEqual(len(list((self.output / "raw").glob("*.bin"))), 1)
        self.assertFalse((self.output / "manifest.json").exists())
        with self.assertRaises(FileNotFoundError):
            ro.make_observation_metadata(self.output)

    def test_publication_th_header_is_rejected_in_real_worker_before_success(self):
        self.assert_blocked(page(self.records[100:], "发布日期"),
                            reason="JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_actual_styled_td_publication_header_is_rejected_in_real_worker(self):
        self.assert_blocked(page(self.records[100:], "发布日期", "td"),
                            reason="JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_unknown_header_is_rejected_even_when_all_100_rows_are_calendar_clean(self):
        self.assert_blocked(page(self.records[100:], "日期"))

    def test_headerless_data_cannot_infer_draw_semantics(self):
        self.assert_blocked("<table>" + body(self.records[100:]) + "</table>")

    def test_shifted_date_issue_schema_is_rejected(self):
        shifted = "<tr><th>期号</th><th>开奖日期</th><th>开奖号码</th></tr>"
        self.assert_blocked("<table>" + shifted + body(self.records[100:]) + "</table>")

    def test_safe_empty_decoy_table_does_not_authorize_publication_table(self):
        self.assert_blocked(page([]) + page(self.records[100:], "发布日期"),
                            reason="JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")

    def test_hidden_wrapper_cannot_promote_nonvisible_table_to_draw_evidence(self):
        self.assert_blocked("<div hidden>" + page(self.records[100:]) + "</div>")

    def test_escaped_safe_header_is_not_an_actual_schema(self):
        self.assert_blocked("<table>" + html.escape(header(), quote=False) +
                            body(self.records[100:]) + "</table>")

    def test_malformed_unsafe_end_token_does_not_release_table_evidence(self):
        self.assert_blocked("<textarea></ textarea>" + page(self.records[100:]) + "</textarea>")

    def test_good_first_bad_second_preserves_both_raw_bodies_without_manifest(self):
        first = page(self.records[100:])
        for label in ("发布日期", "日期"):
            with self.subTest(second_page_header=label):
                self.output = Path(self.temp.name) / label
                second = page(self.records[:100], label, "td")
                reason = ("JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE" if label == "发布日期"
                          else "JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED")
                with self.assertRaisesRegex(Exception, reason):
                    self.capture([first, second])
                expected = {hashlib.sha256(text.encode()).hexdigest() + ".bin": text.encode()
                            for text in (first, second)}
                actual = {path.name: path.read_bytes() for path in (self.output / "raw").glob("*.bin")}
                self.assertEqual(actual, expected)
                self.assertFalse((self.output / "manifest.json").exists())
                with self.assertRaises(FileNotFoundError):
                    ro.make_observation_metadata(self.output)

    def test_explicit_draw_date_and_draw_time_headers_keep_real_parser_positive(self):
        for label, tag in (("开奖日期", "th"), ("开奖时间", "td")):
            with self.subTest(label=label, tag=tag):
                self.output = Path(self.temp.name) / label
                _, seen = self.capture([page(self.records[100:], label, tag),
                                        page(self.records[:100], label, tag)])
                manifest = ro.verify_observation(self.output)
                self.assertEqual(manifest["all_rows"], self.records)
                self.assertEqual(len(seen), 2)
                self.assertEqual(len(manifest["selected_rows"]), 120)
                self.assertEqual(manifest["formal_A"], 0)
                self.assertEqual(manifest["decision"], "NO_EDGE")
                self.assertEqual(manifest["official_G01"], "BLOCKED")
                self.assertNotIn("target_issue", manifest)


if __name__ == "__main__":
    unittest.main()
