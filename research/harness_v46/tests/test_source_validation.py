"""Synthetic parsed-row checks only; no official data or parser authenticity is asserted."""
import copy
import unittest
from research.harness_v46.tests.test_core import fixture
from research.harness_v46.source_validation import GateError, compare_source_histories


def parsed(snapshot):
    return [
        {"issue": d["issue"], "front": list(d["front"]), "back": list(d["back"]),
         "drawn_at": d["drawn_at"], "published_at": d["published_at"]}
        for d in snapshot["draws"]
    ]


def sources(game):
    if game == "SSQ":
        return (
            {"url": "https://www.swlc.net.cn/lottery/ssq.html?limit=100", "raw_sha256": "a" * 64},
            {"url": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/", "raw_sha256": "b" * 64},
        )
    return (
        {"url": "https://www.gstc.org.cn/wanfa/dlt_history", "raw_sha256": "a" * 64},
        {"url": "https://www.fjtc.com.cn/node_309522.htm?gameType=f", "raw_sha256": "b" * 64},
    )


class SourceValidationTests(unittest.TestCase):
    def test_two_allowlisted_sources_match_locked_120_plus_snapshot(self):
        snap = fixture("SSQ")
        a, b = sources("SSQ")
        report = compare_source_histories(snap, a, parsed(snap), b, parsed(snap))
        self.assertEqual(report["history_rows"], 140)
        self.assertEqual(report["semantic_agreement"], "MATCHED")
        self.assertEqual(report["source_origin_authenticity"], "NOT_VERIFIED")
        self.assertEqual(report["official_G01"], "BLOCKED")
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_source_number_disagreement_blocks(self):
        snap = fixture("DLT")
        a, b = sources("DLT")
        other = parsed(snap)
        row = other[30]
        replacement = next(n for n in range(1, 36) if n not in row["front"])
        row["front"][-1] = replacement
        row["front"].sort()
        with self.assertRaisesRegex(GateError, "SOURCE_HISTORY_CONFLICT"):
            compare_source_histories(snap, a, parsed(snap), b, other)

    def test_two_pages_from_same_official_root_are_not_independent_sources(self):
        snap = fixture("SSQ")
        a = {"url": "https://www.swlc.net.cn/a", "raw_sha256": "a" * 64}
        b = {"url": "https://appsh.swlc.net.cn/b", "raw_sha256": "b" * 64}
        with self.assertRaisesRegex(GateError, "TWO_DISTINCT_OFFICIAL_SOURCE_ROOTS"):
            compare_source_histories(snap, a, parsed(snap), b, parsed(snap))

    def test_unallowlisted_host_blocks(self):
        snap = fixture("SSQ")
        a, b = sources("SSQ")
        a["url"] = "https://example.org/ssq"
        with self.assertRaisesRegex(GateError, "SOURCE_HOST_NOT_ALLOWLISTED"):
            compare_source_histories(snap, a, parsed(snap), b, parsed(snap))

    def test_less_than_120_rows_blocks(self):
        snap = fixture("SSQ")
        a, b = sources("SSQ")
        with self.assertRaisesRegex(GateError, "AT_LEAST_120"):
            compare_source_histories(snap, a, parsed(snap)[:119], b, parsed(snap)[:119])

    def test_duplicate_issue_blocks(self):
        snap = fixture("SSQ")
        a, b = sources("SSQ")
        rows = parsed(snap)
        rows[20]["issue"] = rows[19]["issue"]
        with self.assertRaisesRegex(GateError, "DUPLICATE_OR_OUT_OF_ORDER"):
            compare_source_histories(snap, a, rows, b, parsed(snap))

    def test_source_history_must_match_snapshot_even_if_sources_agree(self):
        snap = fixture("SSQ")
        a, b = sources("SSQ")
        rows_a = parsed(snap)
        rows_b = parsed(snap)
        row = rows_a[10]
        replacement = next(n for n in range(1, 34) if n not in row["front"])
        row["front"][-1] = replacement
        row["front"].sort()
        rows_b = copy.deepcopy(rows_a)
        report_snapshot = copy.deepcopy(snap)
        with self.assertRaisesRegex(GateError, "SOURCE_HISTORY_DIFFERS"):
            compare_source_histories(report_snapshot, a, rows_a, b, rows_b)

    def test_publication_after_asof_blocks(self):
        snap = fixture("DLT")
        a, b = sources("DLT")
        rows = parsed(snap)
        rows[0]["published_at"] = "2026-10-25T00:00:00+00:00"
        with self.assertRaisesRegex(GateError, "AFTER_ASOF"):
            compare_source_histories(snap, a, rows, b, parsed(snap))


if __name__ == "__main__":
    unittest.main()
