"""SSQ physical-source boundary tests: synthetic issuer table, zero network."""
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.ssq_physical_source import (
    Blocked, collect, parse_public_table, source_url, verify, URL,
)


def fixture(*, first=2026130, count=10, mutate=None):
    rows = ['<table class="lottery-history-table lottery-history-table--ssq">']
    for i in range(count):
        issue = str(first - i)
        day = (date(2026, 11, 12) - timedelta(days=2*i)).isoformat()
        front = [1, 2, 6, 16, 20, 28]
        blue = 2
        if mutate and i == 0:
            front, blue = mutate
        red_html = "".join(f"<span class='red'>{n:02d}</span>" for n in front)
        rows.append(f"<tr><td>{issue}</td><td>{day}(四)</td>"
                    f"<td>{red_html}</td><td><b>{blue:02d}</b></td>"
                    "<td>415,319,170.00</td></tr>")
    rows.append("</table>")
    return ("<html><body>" + "".join(rows) + "</body></html>").encode("utf-8")


def http(raw, status=200, redirect=None):
    return lambda url: (status, redirect or url, raw)


class SSQIssuerTest(unittest.TestCase):
    def test_issuer_parsing_sorted_balls_are_not_order_or_group(self):
        x = parse_public_table(fixture(), "2026130")
        self.assertEqual("2026-11-12", x["draw_date"])
        self.assertEqual([1, 2, 6, 16, 20, 28], x["red_sorted"])
        self.assertEqual(2, x["blue_number"])
        self.assertIsNone(x["red_order"])
        self.assertIsNone(x["red_ball_group"])
        self.assertIsNone(x["blue_ball_group"])
        self.assertEqual("SORTED_ONLY", x["observation_class"])

    def test_issue_validation_and_not_in_window(self):
        for issue in ("../2026130", "2026130/", "20261301", "026130", "2026130\n", ""):
            with self.subTest(issue=repr(issue)):
                with self.assertRaisesRegex(Blocked, "ISSUE_FORMAT"):
                    source_url(issue)
        with self.assertRaisesRegex(Blocked, "ISSUE_ABSENT"):
            parse_public_table(fixture(), "2026100")

    def test_malformed_table_out_of_order_duplicate_blocks(self):
        with self.assertRaisesRegex(Blocked, "ISSUER_TABLE_INVALID"):
            parse_public_table(b"<html>no data</html>", "2026130")
        with self.assertRaisesRegex(Blocked, "ISSUER_TABLE_INVALID"):
            parse_public_table(fixture(first=2026130, count=4), "2026130")
        with self.assertRaisesRegex(Blocked, "ISSUER_TABLE_INVALID"):
            parse_public_table(fixture(mutate=([1, 2, 6, 16, 20, 20], 2)), "2026130")
        with self.assertRaisesRegex(Blocked, "ISSUER_TABLE_INVALID"):
            parse_public_table(fixture(mutate=([1, 2, 6, 16, 20, 34], 2)), "2026130")
        with self.assertRaisesRegex(Blocked, "ISSUER_TABLE_INVALID"):
            parse_public_table(fixture(mutate=([1, 2, 6, 16, 20, 28], 17)), "2026130")

    def test_success_repeat_and_verified_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            a = collect("2026130", ledger, fetcher=http(fixture()))
            b = collect("2026130", ledger, fetcher=http(fixture()))
            self.assertEqual("RECORDED_SORTED_ONLY", a["status"])
            self.assertEqual("MATCHED_EXISTING_SORTED_ONLY", b["status"])
            v = verify(ledger)
            self.assertEqual(1, v["draws_verified"])
            self.assertEqual(2, v["attempts_verified"])
            self.assertEqual(0, v["physical_order_verified"])
            draw = json.loads((ledger/"draws"/"2026130.json").read_text())
            self.assertEqual(URL, draw["source_url"])
            self.assertIsNone(draw["red_order"])

    def test_conflicting_new_issuer_row_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            collect("2026130", ledger, fetcher=http(fixture()))
            previous = (ledger/"draws"/"2026130.json").read_bytes()
            altered = fixture(mutate=([1, 2, 6, 16, 20, 29], 2))
            second = collect("2026130", ledger, fetcher=http(altered))
            self.assertEqual("BLOCKED", second["status"])
            self.assertEqual("DRAW_OBSERVATION_CONFLICT", second["reason"])
            self.assertEqual(previous, (ledger/"draws"/"2026130.json").read_bytes())
            self.assertEqual(2, verify(ledger)["attempts_verified"])

    def test_network_failure_http_567_and_redirect_preserve_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            a = collect("2026130", ledger, fetcher=http(b"blocked", status=567))
            b = collect("2026130", ledger, fetcher=http(fixture(),
                       redirect="https://example.com/lottery/ssq.html?limit=50&view=previous"))
            def fail(url):
                raise TimeoutError("blocked")
            c = collect("2026130", ledger, fetcher=fail)
            self.assertEqual("OFFICIAL_HTTP_NON_200", a["reason"])
            self.assertEqual(567, a["http_status"])
            self.assertEqual("UNTRUSTED_SOURCE_REDIRECT", b["reason"])
            self.assertEqual("NETWORK_OR_IO_FAILURE:TimeoutError", c["reason"])
            self.assertEqual(3, verify(ledger)["attempts_verified"])
            self.assertEqual(0, verify(ledger)["draws_verified"])

    def test_raw_tampering_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            a = collect("2026130", ledger, fetcher=http(fixture()))
            self.assertEqual("RECORDED_SORTED_ONLY", a["status"])
            raw_path = ledger/"raw"/(a["response_sha256"] + ".bin")
            raw_path.write_bytes(b"corrupted")
            with self.assertRaisesRegex(Blocked, "TAMPERED_SOURCE_BYTES"):
                verify(ledger)

    def test_cannot_backfill_unknown_fields_and_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            collect("2026130", ledger, fetcher=http(fixture()))
            path = ledger/"draws"/"2026130.json"
            row = json.loads(path.read_text())
            row["red_order"] = row["red_sorted"]
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(Blocked, "TAMPERED_DRAW_RECORD"):
                verify(ledger)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            collect("2026130", ledger, fetcher=http(fixture()))
            path = ledger/"draws"/"2026130.json"
            body = path.read_text()
            path.write_text(body.replace('"game": "SSQ",', '"game": "SSQ", "game": "DLT",'))
            with self.assertRaisesRegex(Blocked, "DUPLICATE_LEDGER_JSON_KEY"):
                verify(ledger)


if __name__ == "__main__":
    unittest.main()
