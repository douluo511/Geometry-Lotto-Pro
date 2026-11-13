"""SQLite materialization, restart, immutability and crash regression tests."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.supercompute.automation.physical_ledger_db import (
    IntegrityBlocked, sync,
)
from research.supercompute.automation.ssq_physical_source import collect as ssq_collect
from research.supercompute.automation.dlt_physical_source import collect as dlt_collect


def ssq_html():
    lines = ['<table class="lottery-history-table lottery-history-table--ssq">']
    for i in range(10):
        lines.append(f'<tr><td>{2026130-i}</td><td>2026-11-12(四)</td>'
                     '<td>010206162028</td><td>02</td></tr>')
    return ("".join(lines) + "</table>").encode()


def dlt_html():
    return ("""<html><body><h1>第26105期开奖公告</h1>
        <p>开奖日期：2026年9月14日</p>
        <p>本期使用第3套摇奖球</p>
        本期出球顺序： 33 10 14 34 30 09 12
        本期开奖号码： 10 14 30 33 34 09 12
        本期中奖情况</body></html>""").encode()


def fake(body, status=200):
    return lambda url: (status, url, body)


class DurableSqliteTest(unittest.TestCase):
    def seed(self, root):
        a = ssq_collect("2026130", root / "SSQ", fetcher=fake(ssq_html()))
        b = dlt_collect("26105", root / "DLT", fetcher=fake(dlt_html()))
        self.assertEqual("RECORDED_SORTED_ONLY", a["status"])
        self.assertEqual("RECORDED", b["status"])

    def test_two_games_crash_restart_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            db = root / "evidence.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "INJECTED_CRASH"):
                sync(root, db, inject_failure_before_commit=True)
            # New process connection has no partial committed rows.
            report = sync(root, db)
            self.assertEqual(1, report["counts"]["SSQ"]["draws"])
            self.assertEqual(1, report["counts"]["DLT"]["draws"])
            self.assertEqual(1, report["counts"]["DLT"]["attempts"])
            self.assertEqual(report["counts"], sync(root, db)["counts"])
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(2, conn.execute("SELECT count(*) FROM draws").fetchone()[0])
                self.assertEqual(2, conn.execute("SELECT count(*) FROM attempts").fetchone()[0])
                ssq = conn.execute(
                    "SELECT observation_class,ball_group FROM draws WHERE game='SSQ'"
                ).fetchone()
                dlt = conn.execute(
                    "SELECT observation_class,ball_group FROM draws WHERE game='DLT'"
                ).fetchone()
            self.assertEqual(("SORTED_ONLY", None), ssq)
            self.assertEqual(("ORDERED_PHYSICAL", 3), dlt)

    def test_append_attempt_then_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            db = root / "evidence.sqlite3"
            sync(root, db)
            ssq_collect("2026130", root / "SSQ", fetcher=fake(b"blocked", 503))
            first = sync(root, db)
            self.assertEqual(2, first["counts"]["SSQ"]["attempts"])
            with closing(sqlite3.connect(db)) as conn:
                statuses = [x[0] for x in conn.execute(
                    "SELECT status FROM attempts WHERE game='SSQ' ORDER BY receipt_path")]
            self.assertIn("BLOCKED", statuses)
            self.assertIn("RECORDED_SORTED_ONLY", statuses)

    def test_changed_canonical_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            db = root / "evidence.sqlite3"
            sync(root, db)
            file = root / "SSQ" / "draws" / "2026130.json"
            record = json.loads(file.read_text())
            record["red_order"] = record["red_sorted"]
            file.write_text(json.dumps(record))
            with self.assertRaises(Exception):
                sync(root, db)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(2, conn.execute("SELECT count(*) FROM draws").fetchone()[0])

    def test_missing_canonical_history_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            db = root / "evidence.sqlite3"
            sync(root, db)
            (root / "DLT" / "draws" / "26105.json").unlink()
            with self.assertRaisesRegex(IntegrityBlocked, "CANONICAL_LEDGER_MISMATCH"):
                sync(root, db)


if __name__ == "__main__":
    unittest.main()
