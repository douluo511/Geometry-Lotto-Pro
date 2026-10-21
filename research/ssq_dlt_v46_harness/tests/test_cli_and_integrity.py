"""Additional P0 probes for actual CLI artifact generation and SQL REPLACE."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.ssq_dlt_v46_harness.__main__ import predict, synthetic_history
from research.ssq_dlt_v46_harness.core import HarnessBlocked, Ledger


class EndToEndTests(unittest.TestCase):
    def snapshot(self, date="2030-01-01T12:00:00Z"):
        return {
            "asof": "2026-03-15T00:00:00Z",
            "targets": {
                game: {"issue": "00066", "draw_at": date} for game in ("SSQ", "DLT")
            },
            "history": {game: synthetic_history(game) for game in ("SSQ", "DLT")},
        }

    def test_cli_two_game_file_ledger_and_no_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            snap, out, db = root / "snapshot.json", root / "out.json", root / "ledger.sqlite3"
            snap.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            receipt = predict(snap, db, out)
            self.assertEqual(receipt["status"], "SHADOW_ONLY")
            self.assertTrue(out.exists())
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["forecasts"]), {"SSQ", "DLT"})
            self.assertEqual(saved["formal_A"], 0)
            ledger = Ledger(db)
            self.assertEqual(ledger.verify(), 2)
            ledger.close()
            with self.assertRaisesRegex(HarnessBlocked, "OUTPUT_MUST_BE_NEW"):
                predict(snap, db, out)

    def test_expired_target_fails_no_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            snap, out, db = root / "snapshot.json", root / "out.json", root / "ledger.sqlite3"
            snap.write_text(json.dumps(self.snapshot("2020-01-01T00:00:00Z")), encoding="utf-8")
            with self.assertRaisesRegex(HarnessBlocked, "TARGET_ALREADY_DRAWN"):
                predict(snap, db, out)
            self.assertFalse(out.exists())
            self.assertFalse(db.exists())

    def test_sql_replace_also_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            db = Ledger(Path(root) / "ledger.sqlite3")
            db.append("x", "FORECAST", {"frozen": 1})
            with self.assertRaises(sqlite3.DatabaseError):
                db.db.execute("INSERT OR REPLACE INTO events VALUES ('x','FORECAST','x','{}')")
            self.assertEqual(db.verify(), 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
