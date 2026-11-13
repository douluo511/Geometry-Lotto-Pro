"""Two independent ingestion ticks, persisted prefixes and failure evidence."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.physical_tick import tick, REL
from research.supercompute.automation.dlt_physical_source import collect as dlt_collect
from research.supercompute.automation.physical_ledger_db import sync
from research.supercompute.automation.physical_transport import TransportExhausted


def ssq_html():
    items = ['<table class="lottery-history-table lottery-history-table--ssq">']
    for i in range(10):
        items.append(f"<tr><td>{2026130-i}</td><td>2026-11-12(四)</td>"
                     "<td>010206162028</td><td>02</td></tr>")
    return ("".join(items)+"</table>").encode()


def dlt_html(issue):
    return (f"<html><body>第{issue}期开奖公告 开奖日期：2026年1月1日 "
            "本期使用第1套摇奖球 本期出球顺序：33 10 14 34 30 09 12 "
            "本期开奖号码：10 14 30 33 34 09 12 本期中奖情况</body></html>").encode()


def mock_dlt(issue, ledger):
    return dlt_collect(issue, ledger,
                       fetcher=lambda url: (200, url, dlt_html(issue)))


class LiveTickOfflineContract(unittest.TestCase):
    def test_sequential_ticks_recover_and_append_new_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
            ssq = lambda url: (200, url, ssq_html(), [])
            one = tick(root, max_ssq_new=2, now=now,
                       ssq_network=ssq, dlt_collector=mock_dlt)
            self.assertEqual(2, one["counts"]["SSQ"]["draws"])
            self.assertEqual(1, one["counts"]["DLT"]["draws"])
            self.assertEqual(1, len(list((root/REL/"ticks").glob("*.json"))))
            two = tick(root, max_ssq_new=2, now=now,
                       ssq_network=ssq, dlt_collector=mock_dlt)
            self.assertEqual(4, two["counts"]["SSQ"]["draws"])
            self.assertEqual(2, two["counts"]["DLT"]["draws"])
            self.assertTrue((root/REL/"DLT"/"draws"/"26001.json").is_file())
            self.assertTrue((root/REL/"DLT"/"draws"/"26002.json").is_file())
            self.assertEqual(2, len(list((root/REL/"ticks").glob("*.json"))))
            self.assertEqual(2, sync(root/REL, root/REL/"physical_history.sqlite3")
                             ["counts"]["DLT"]["draws"])

    def test_failed_discovery_keeps_blocker_and_does_not_fabricate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
            attempts = [{"attempt": i+1, "url": "https://www.swlc.net.cn", 
                         "reason": "NETWORK_URLError"} for i in range(4)]
            def blocked(url):
                raise TransportExhausted(attempts)
            def dlt_fail(issue, ledger):
                return dlt_collect(issue, ledger,
                    fetcher=lambda url: (567, url, b"issuer unavailable"))
            result = tick(root, now=now, ssq_network=blocked,
                          dlt_collector=dlt_fail)
            self.assertEqual(0, result["counts"]["SSQ"]["draws"])
            self.assertEqual(0, result["counts"]["DLT"]["draws"])
            self.assertEqual(1, result["counts"]["SSQ"]["attempts"])
            self.assertEqual(1, result["counts"]["DLT"]["attempts"])
            self.assertEqual("NO_EDGE", result["edge"])
            # Still verifies a persisted, honest failure-only database.
            self.assertEqual(1, sync(root/REL, root/REL/"physical_history.sqlite3")
                             ["counts"]["SSQ"]["attempts"])

    def test_invalid_batch_bound_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "BATCH_OUT_OF_RANGE"):
                tick(Path(tmp), max_ssq_new=51, ssq_network=lambda url: None)


if __name__ == "__main__":
    unittest.main()
