"""Offline-only physical draw audit contract tests (synthetic HTML fixture)."""
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.dlt_physical_source import (
    Blocked, collect, parse_announcement, source_url, verify,
)


def fixture(issue="26105", group=3, order="33 10 14 34 30", back="09 12",
            front_sorted="10 14 30 33 34", back_sorted="09 12",
            date="2026年9月14日"):
    return (f'<html><head><script>var fake="第99999期开奖公告";</script></head>'
            f'<body><h1>第{issue}期开奖公告</h1>'
            f'<p>开奖日期：{date}</p><div>本期使用第{group}套摇奖球</div>'
            '<table><tr><td>前区</td><td>后区</td></tr>'
            f'<tr><td>本期出球顺序：</td><td>{order}</td><td>{back}</td></tr>'
            f'<tr><td>本期开奖号码：</td><td>{front_sorted}</td>'
            f'<td>{back_sorted}</td></tr></table>'
            '<p>本期中奖情况</p><p>本期兑奖截止日为2026年11月13日</p>'
            '</body></html>').encode("utf-8")


def stub(raw, status=200, final_url=None):
    return lambda url: (status, final_url or url, raw)


class PhysicalDrawTest(unittest.TestCase):
    def test_parse_preserves_order_distinct_from_sorted(self):
        item = parse_announcement(fixture(), "26105")
        self.assertEqual([33, 10, 14, 34, 30], item["front_order"])
        self.assertEqual([10, 14, 30, 33, 34], item["front_sorted"])
        self.assertEqual("2026-09-14", item["draw_date"])
        self.assertEqual(3, item["ball_group"])

    def test_bad_issue_input_and_mismatch_blocked(self):
        for issue in ("../26105", "26105?", "26105\n", "261051", "x"):
            with self.subTest(issue=repr(issue)):
                with self.assertRaises(Blocked):
                    source_url(issue)
        with self.assertRaisesRegex(Blocked, "ISSUE_MISMATCH"):
            parse_announcement(fixture(), "26106")

    def test_date_not_taken_from_redemption_deadline(self):
        with self.assertRaisesRegex(Blocked, "DRAW_DATE_MISSING"):
            parse_announcement(fixture().replace(b"2026\xe5\xb9\xb49\xe6\x9c\x8814\xe6\x97\xa5",
                                                   b"not-a-date"), "26105")

    def test_duplicate_or_mismatched_balls_blocked(self):
        with self.assertRaisesRegex(Blocked, "DRAW_DOMAIN_OR_ORDER_CONFLICT"):
            parse_announcement(fixture(order="33 10 14 34 33"), "26105")
        with self.assertRaisesRegex(Blocked, "DRAW_DOMAIN_OR_ORDER_CONFLICT"):
            parse_announcement(fixture(back_sorted="09 11"), "26105")
        with self.assertRaisesRegex(Blocked, "DRAW_BALL_COUNT_INVALID"):
            parse_announcement(fixture(order="33 10 14 34"), "26105")

    def test_single_success_repeat_and_ledger_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            first = collect("26105", ledger, fetcher=stub(fixture()))
            self.assertEqual("RECORDED", first["status"])
            second = collect("26105", ledger, fetcher=stub(fixture()))
            self.assertEqual("MATCHED_EXISTING", second["status"])
            self.assertEqual(1, verify(ledger)["draws_verified"])
            self.assertEqual(2, len(list((ledger/"attempts"/"26105").glob("*.json"))))
            stored = json.loads((ledger/"draws"/"26105.json").read_text())
            self.assertEqual("2026-09-14", stored["draw_date"])
            self.assertEqual(first["response_sha256"], stored["source_sha256"])

    def test_mismatch_preserves_original_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            collect("26105", ledger, fetcher=stub(fixture()))
            original = (ledger/"draws"/"26105.json").read_bytes()
            result = collect("26105", ledger, fetcher=stub(fixture(group=2)))
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual("DRAW_OBSERVATION_CONFLICT", result["reason"])
            self.assertEqual(original, (ledger/"draws"/"26105.json").read_bytes())
            self.assertEqual(2, len(list((ledger/"attempts"/"26105").glob("*.json"))))

    def test_http_error_and_redirect_record_failure_and_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            a = collect("26105", ledger, fetcher=stub(b"server error", 567))
            b = collect("26105", ledger, fetcher=stub(fixture(),
                    final_url="https://example.org/stolen"))
            self.assertEqual("OFFICIAL_HTTP_NON_200", a["reason"])
            self.assertEqual("UNTRUSTED_SOURCE_REDIRECT", b["reason"])
            self.assertFalse((ledger/"draws"/"26105.json").exists())
            self.assertEqual(2, len(list((ledger/"attempts"/"26105").glob("*.json"))))
            self.assertTrue((ledger/"raw"/(a["response_sha256"]+".bin")).is_file())

    def test_network_exception_creates_failure_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            def unavailable(url):
                raise TimeoutError("offline test")
            ledger = Path(tmp)
            r = collect("26105", ledger, fetcher=unavailable)
            self.assertEqual("BLOCKED", r["status"])
            self.assertEqual("NETWORK_OR_IO_FAILURE:TimeoutError", r["reason"])
            self.assertIsNone(r["response_sha256"])
            self.assertEqual(1, len(list((ledger/"attempts"/"26105").glob("*.json"))))

    def test_byte_tamper_blocks_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            result = collect("26105", ledger, fetcher=stub(fixture()))
            self.assertEqual("RECORDED", result["status"])
            (ledger/"raw"/(result["response_sha256"]+".bin")).write_bytes(b"tampered")
            with self.assertRaisesRegex(Blocked, "TAMPERED_SOURCE_BYTES"):
                verify(ledger)


if __name__ == "__main__":
    unittest.main()
