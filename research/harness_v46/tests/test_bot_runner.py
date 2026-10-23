"""Adversarial synthetic tests for local scheduler-compatible SHADOW bot."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.harness_v46 import bot_runner as bot, core
from research.harness_v46.tests.test_core import fixture


class ShadowBotTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.db = str(self.root / "ledger.sqlite")
        self.snaps = {game: fixture(game) for game in ("SSQ", "DLT")}
        self.before = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        self.after = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()

    def _result(self):
        return {
            game: {
                "lottery": game, "issue": "29999",
                "front": core.forecast(self.snaps[game], "hot60")["ticket"]["front"],
                "back": core.forecast(self.snaps[game], "hot60")["ticket"]["back"],
                "drawn_at": "2026-10-23T21:05:00+08:00",
            }
            for game in ("SSQ", "DLT")
        }

    def _forecast(self):
        return bot.forecast_tick(self.snaps, self.db, self.evidence, now=self.before)

    def test_forecast_score_and_cumulative_all_replay_readonly(self):
        prediction = self._forecast()
        self.assertEqual(prediction, self._forecast())
        rid = prediction["run_id"]
        self.assertEqual(prediction["formal_A"], 0)
        self.assertEqual(prediction["payload"]["frozen_forecast"]["games"]["SSQ"]["models"][0]["primary_d2"],
                         core.forecast(self.snaps["SSQ"], "hot60")["primary_d2"])
        before = Path(self.db).read_bytes()
        scored = bot.score_tick(self.evidence, rid, self._result(), now=self.after)
        self.assertEqual(scored, bot.score_tick(self.evidence, rid, self._result(), now=self.after))
        cumulative = bot.cumulative_tick(self.evidence)
        self.assertEqual(Path(self.db).read_bytes(), before)
        self.assertEqual(cumulative["unique_two_game_runs"], 1)
        for game in ("SSQ", "DLT"):
            self.assertEqual(cumulative["games"][game]["models"]["hot60"]["d2_hits"], 1)
        self.assertEqual(scored["payload"]["outcome_authenticity"], "CALLER_UNVERIFIED")
        self.assertEqual(cumulative["formal_A"], 0)
        self.assertEqual(cumulative["decision"], "NO_EDGE")

    def test_before_draw_even_with_future_result_is_blocked(self):
        rid = self._forecast()["run_id"]
        with self.assertRaisesRegex(core.GateError, "BOT_REAL_CLOCK_BEFORE_TARGET_DRAW"):
            bot.score_tick(self.evidence, rid, self._result(), now=self.before)
        later = self._result()
        later["DLT"]["drawn_at"] = "2026-10-24T21:05:00+08:00"
        with self.assertRaisesRegex(core.GateError, "BOT_CLAIMED_DRAW_IN_FUTURE"):
            bot.score_tick(self.evidence, rid, later, now=self.after)
        self.assertFalse((self.evidence / "scores").exists())

    def test_conflicting_outcome_cannot_overwrite_original(self):
        rid = self._forecast()["run_id"]
        first = bot.score_tick(self.evidence, rid, self._result(), now=self.after)
        changed = self._result()
        changed["SSQ"]["front"] = [1, 2, 3, 4, 5, 6]
        with self.assertRaisesRegex(core.GateError, "BOT_CONFLICTING_EXACT_RUN_RETRY"):
            bot.score_tick(self.evidence, rid, changed, now=self.after)
        raw = (self.evidence / "scores" / (rid + ".json")).read_text()
        self.assertEqual(json.loads(raw), first)

    def test_modified_receipt_and_fake_formal_a_rejected(self):
        rid = self._forecast()["run_id"]
        path = self.evidence / "forecasts" / (rid + ".json")
        receipt = json.loads(path.read_text())
        receipt["formal_A"] = 1
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(core.GateError, "BOT_RECEIPT_CANNOT_CLAIM_AUTHORITY"):
            bot.score_tick(self.evidence, rid, self._result(), now=self.after)

    def test_receipt_checksum_corruption_rejected(self):
        rid = self._forecast()["run_id"]
        path = self.evidence / "forecasts" / (rid + ".json")
        receipt = json.loads(path.read_text())
        receipt["payload"]["frozen_forecast"]["games"]["SSQ"]["models"][0]["primary_d2"] = [1, 2]
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(core.GateError, "BOT_RECEIPT_INTEGRITY_FAIL"):
            bot.score_tick(self.evidence, rid, self._result(), now=self.after)

    def test_symlink_receipts_and_folders_blocked(self):
        rid = self._forecast()["run_id"]
        original = self.evidence / "forecasts" / (rid + ".json")
        link = self.evidence / "forecasts" / ("V47-" + "0"*32 + ".json")
        try:
            link.symlink_to(original)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation not permitted in this environment")
        with self.assertRaisesRegex(core.GateError, "BOT_SYMLINK_RECEIPT_FORBIDDEN"):
            bot._read_record(link)

    def test_late_forecast_cannot_fabricate_predraw_freeze(self):
        with self.assertRaisesRegex(core.GateError, "NO_RETROACTIVE"):
            bot.forecast_tick(self.snaps, self.db, self.evidence, now=self.after)
        self.assertFalse(Path(self.db).exists())

    def test_missing_forecast_or_forged_run_id_blocked(self):
        with self.assertRaisesRegex(core.GateError, "INVALID_BOT_RUN_ID"):
            bot.score_tick(self.evidence, "../../forge", self._result(), now=self.after)
        with self.assertRaisesRegex(core.GateError, "BOT_PERSISTENT_DIRECTORY_REQUIRED"):
            bot.score_tick(self.evidence, "V47-" + "a"*32, self._result(), now=self.after)

    def test_duplicate_outcomes_from_extraneous_score_receipt_block(self):
        rid = self._forecast()["run_id"]
        bot.score_tick(self.evidence, rid, self._result(), now=self.after)
        score_path = self.evidence / "scores" / (rid + ".json")
        tampered = json.loads(score_path.read_text())
        tampered["local_sha256_untrusted"] = "000"
        score_path.write_text(json.dumps(tampered))
        with self.assertRaisesRegex(core.GateError, "BOT_RECEIPT_INTEGRITY_FAIL"):
            bot.cumulative_tick(self.evidence)


if __name__ == "__main__":
    unittest.main()
