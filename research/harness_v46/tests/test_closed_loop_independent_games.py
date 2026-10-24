"""RED: independent real-weekday SSQ+DLT issue lifecycle in SAME V4.7 runner.

Invented data, local clock, caller-supplied result only; never formal A.
"""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture


def at(s):
    return datetime.fromisoformat(s)


class AlternatingGameLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "one-workspace"
        self.dlt_sat = fixture("DLT")
        self.dlt_sat.update(as_of="2026-10-24T09:00:00+08:00",
                            sales_cutoff="2026-10-24T21:00:00+08:00",
                            target_draw_at="2026-10-24T21:25:00+08:00",
                            target_issue="26250")
        self.ssq_sun = fixture("SSQ")
        self.ssq_sun.update(as_of="2026-10-24T09:00:00+08:00",
                            sales_cutoff="2026-10-25T20:00:00+08:00",
                            target_draw_at="2026-10-25T21:15:00+08:00",
                            target_issue="26251")
        self.dlt_mon = fixture("DLT")
        self.dlt_mon.update(as_of="2026-10-25T09:00:00+08:00",
                            sales_cutoff="2026-10-26T21:00:00+08:00",
                            target_draw_at="2026-10-26T21:25:00+08:00",
                            target_issue="26252")

    def tick(self, snapshot=None, game=None, clock="2026-10-24T10:00:00+08:00"):
        return closed_loop.advance_game_workspace(
            self.ws, snapshot=snapshot, game=game, observed_at=at(clock)
        )

    def outcome(self, snapshot):
        game = snapshot["lottery"]
        d = snapshot["draws"][-2]
        return {"lottery": game, "issue": snapshot["target_issue"],
                "front": list(d["front"]), "back": list(d["back"]),
                "drawn_at": snapshot["target_draw_at"]}

    def publish(self, snapshot):
        p = self.ws / "outcomes_by_game" / snapshot["lottery"]
        p.mkdir(parents=True, exist_ok=True)
        (p / (snapshot["target_issue"] + ".json")).write_text(
            json.dumps(self.outcome(snapshot)), encoding="utf-8")

    def test_saturday_dlt_scored_while_sunday_ssq_pending_then_monday_dlt_freezes(self):
        # Three different real draw weekdays; no fabricated second-game result.
        sat = self.tick(self.dlt_sat)
        self.assertEqual(sat["status"], "WAITING_FOR_OUTCOME")
        self.assertEqual(sat["lottery"], "DLT")
        self.assertEqual(len(sat["frozen_issues"]), 1)
        self.assertEqual(len(sat["frozen_cards"]), 6)
        self.assertEqual(set(x["model"] for x in sat["frozen_cards"]), set(core.MODELS))
        self.assertEqual(sat["formal_A"], 0)
        sun = self.tick(self.ssq_sun, clock="2026-10-24T11:00:00+08:00")
        self.assertEqual(sun["pending_issues"], ["26251"])
        self.publish(self.dlt_sat)
        scored_sat = self.tick(game="DLT", clock="2026-10-24T22:30:00+08:00")
        self.assertEqual(scored_sat["completed_issues"], ["26250"])
        self.assertEqual(scored_sat["status"], "LOCAL_ROSTER_SHADOW_SCORED")
        self.assertEqual(len(scored_sat["scores_by_issue"][0]["models"]), 6)
        self.assertEqual(scored_sat["official_results_authenticated"], False)
        # Monday new DLT must not re-create the already-frozen Sunday SSQ.
        monday = self.tick(self.dlt_mon, clock="2026-10-25T10:00:00+08:00")
        self.assertEqual(monday["frozen_issues"], ["26250", "26252"])
        self.assertEqual(monday["pending_issues"], ["26252"])
        still_sun = self.tick(game="SSQ", clock="2026-10-25T10:00:00+08:00")
        self.assertEqual(still_sun["pending_issues"], ["26251"])
        self.assertEqual(len(still_sun["frozen_cards"]), 6)
        self.publish(self.ssq_sun)
        scored_sun = self.tick(game="SSQ", clock="2026-10-25T22:30:00+08:00")
        self.assertEqual(scored_sun["completed_issues"], ["26251"])
        self.assertEqual(monday["decision"], "NO_EDGE")

    def test_retries_do_not_replace_issue_or_frozen_random_null(self):
        first = self.tick(self.dlt_sat)
        replay = self.tick(self.dlt_sat, clock="2026-10-25T01:00:00+08:00")
        self.assertEqual(first["frozen_cards"], replay["frozen_cards"])
        changed = dict(self.dlt_sat)
        changed["draws"] = list(self.dlt_sat["draws"][:-1])
        with self.assertRaisesRegex(core.GateError, "GAME_TARGET_ALREADY_FROZEN_DIFFERENT_SNAPSHOT"):
            self.tick(changed, clock="2026-10-24T11:00:00+08:00")
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 6)

    def test_too_late_new_issuance_cannot_be_backfilled(self):
        with self.assertRaisesRegex(core.GateError, "GAME_FREEZE_AFTER_CUTOFF"):
            self.tick(self.dlt_sat, clock="2026-10-24T21:00:00+08:00")
        if (self.ws / "ledger.sqlite3").exists():
            with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as c:
                self.assertEqual(c.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 0)

    def test_invalid_or_early_outcome_does_not_create_receipt(self):
        first = self.tick(self.dlt_sat)
        self.publish(self.dlt_sat)
        with self.assertRaisesRegex(core.GateError, "GAME_RESULT_NOT_YET_DRAWN"):
            self.tick(game="DLT", clock="2026-10-24T20:30:00+08:00")
        out = self.ws / "receipts_by_game" / "DLT" / "26250.json"
        self.assertFalse(out.exists())
        value = self.outcome(self.dlt_sat)
        value["issue"] = "26251"
        (self.ws / "outcomes_by_game" / "DLT" / "26250.json").write_text(
            json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(core.GateError, "GAME_RESULT_ISSUE_MISMATCH"):
            self.tick(game="DLT", clock="2026-10-24T22:30:00+08:00")
        self.assertFalse(out.exists())

    def test_multiple_bot_ticks_same_issue_only_six_cards(self):
        def tick(_):
            return self.tick(self.dlt_sat, clock="2026-10-24T10:00:00+08:00")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(tick, range(2)))
        self.assertEqual(results[0]["run_ids"], results[1]["run_ids"])
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 6)

    def test_legacy_combined_runs_are_preserved_and_not_in_new_study(self):
        # Independent game workflow shares existing workspace without
        # re-writing or promoting legacy 12-card run.
        from research.harness_v46 import prospective_cycle
        legacy = {g: fixture(g) for g in ("SSQ", "DLT")}
        old = closed_loop.advance_workspace(
            self.ws, snapshots=legacy, observed_at=at("2026-10-20T08:00:00+00:00"))
        db = self.ws / "ledger.sqlite3"
        import hashlib
        with closing(sqlite3.connect(db)) as c:
            before_rows = c.execute("SELECT count(*) FROM predictions").fetchone()[0]
        game = self.tick(self.dlt_sat)
        with closing(sqlite3.connect(db)) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM predictions").fetchone()[0], before_rows)
            self.assertEqual(c.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 6)
        self.assertNotIn(old["run_ids"][0], game["run_ids"])
        self.assertFalse(game["official_results_authenticated"])

    def test_cli_game_snapshot_opt_in_keeps_existing_dual_entrypoint(self):
        import subprocess, sys
        snap = Path(self.tmp.name) / "dlt.json"
        snap.write_text(json.dumps(self.dlt_sat), encoding="utf-8")
        # Use a genuine subprocess with synthetic future cutoffs? The fixture
        # target may be historical at runtime; instead test the public parser
        # with a CLI future snapshot derived from the current clock.
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        future = dict(self.dlt_sat)
        future["as_of"] = (now - timedelta(minutes=4)).isoformat()
        future["sales_cutoff"] = (now + timedelta(hours=3)).isoformat()
        future["target_draw_at"] = (now + timedelta(hours=4)).isoformat()
        snap.write_text(json.dumps(future), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "research.harness_v46.closed_loop",
             "--workspace", str(self.ws),
             "--game-snapshot", str(snap)], capture_output=True, text=True, timeout=50)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["lottery"], "DLT")
        self.assertEqual(result["pending_issues"], ["26250"])
        self.assertEqual(result["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
