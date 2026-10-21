"""Isolation, chronology, D2, tamper and repeatability acceptance tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.ssq_dlt_v46_harness.__main__ import smoke, synthetic_history
from research.ssq_dlt_v46_harness.core import (
    ROLES, MODELS, Ledger, HarnessBlocked, generate, score_research, validate_candidate
)


class HarnessTests(unittest.TestCase):
    def make(self, game="SSQ"):
        return generate(game, "00066", synthetic_history(game),
                        asof="2026-03-15T00:00:00Z",
                        target_draw_at="2026-03-17T00:00:00Z")

    def test_ten_roles(self):
        self.assertEqual(len(ROLES), 10)
        self.assertEqual(ROLES["test9"], "08-INDEPENDENT-AUDIT")

    def test_synthetic_two_games(self):
        receipt = smoke()
        self.assertEqual(receipt["status"], "PASS_SYNTHETIC_SMOKE_NOT_LIVE")
        self.assertEqual(set(receipt["games"]), {"SSQ", "DLT"})

    def test_deterministic_six_streams(self):
        for game in ("SSQ", "DLT"):
            a, b = self.make(game), self.make(game)
            self.assertEqual(a, b)
            self.assertEqual(tuple(a["models"]), MODELS)
            self.assertEqual(a["formal_A"], 0)
            self.assertFalse(a["external_tsa"])
            for candidate in a["models"].values():
                validate_candidate(game, candidate)
                self.assertEqual(candidate["primary_d2"], candidate["ordered_dan"][:2])

    def test_no_short_history(self):
        with self.assertRaisesRegex(HarnessBlocked, "60"):
            generate("SSQ", "00066", synthetic_history("SSQ")[:59],
                     asof="2026-03-15T00:00:00Z",
                     target_draw_at="2026-03-17T00:00:00Z")

    def test_future_leak_blocked(self):
        with self.assertRaisesRegex(HarnessBlocked, "FUTURE_OR_UNSORTED"):
            rows = synthetic_history("SSQ")
            rows[-1]["draw_at"] = "2026-03-16T00:00:00Z"
            generate("SSQ", "00066", rows, asof="2026-03-15T00:00:00Z",
                     target_draw_at="2026-03-17T00:00:00Z")

    def test_duplicate_period_blocked(self):
        rows = synthetic_history("SSQ")
        rows[-1]["issue"] = rows[-2]["issue"]
        with self.assertRaises(HarnessBlocked):
            generate("SSQ", "00066", rows, asof="2026-03-15T00:00:00Z",
                     target_draw_at="2026-03-17T00:00:00Z")

    def test_d2_rewrite_blocked(self):
        p = self.make("DLT")["models"]["02-HOT60"]
        p["primary_d2"] = [1, 2] if p["primary_d2"] != [1, 2] else [3, 4]
        with self.assertRaisesRegex(HarnessBlocked, "POST_HOC"):
            validate_candidate("DLT", p)

    def test_score_research_only(self):
        p = self.make("DLT")
        draw = synthetic_history("DLT")[-1]
        x = score_research(p, draw["front"], draw["back"])
        self.assertEqual(x["formal_A"], 0)
        self.assertEqual(len(x["same_period_vs_null"]), 5)
        p["admission"] = "FORMAL_A"
        with self.assertRaisesRegex(HarnessBlocked, "FORMAL_ADMISSION"):
            score_research(p, draw["front"], draw["back"])

    def test_ledger_idempotence_and_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            db = Ledger(Path(root) / "ledger.sqlite3")
            self.assertEqual(db.append("r1", "FORECAST", {"n": 1}),
                             db.append("r1", "FORECAST", {"n": 1}))
            self.assertEqual(db.verify(), 1)
            with self.assertRaisesRegex(HarnessBlocked, "CONFLICTING"):
                db.append("r1", "FORECAST", {"n": 2})
            with self.assertRaises(sqlite3.DatabaseError):
                db.db.execute("UPDATE events SET sha256='forged'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.db.execute("DELETE FROM events")
            db.close()

    def test_untrusted_time_blocked(self):
        with self.assertRaisesRegex(HarnessBlocked, "AWARE_TIMESTAMP"):
            generate("SSQ", "00066", synthetic_history("SSQ"),
                     asof="2026-03-15T00:00:00",
                     target_draw_at="2026-03-17T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
