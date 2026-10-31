"""Synthetic local-clock boundary attacks; no official draw or TSA evidence."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture


class GameFreezeDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "persistent"
        self.snap = fixture("DLT")
        self.snap.update(as_of="2026-10-24T09:00:00+00:00",
                         sales_cutoff="2026-10-24T13:00:00+00:00",
                         target_draw_at="2026-10-24T13:25:00+00:00",
                         target_issue="26250")

    def clock(self, *values):
        """Replace only the wall clock; real model computation and SQLite run."""
        stamps = iter(datetime.fromisoformat(x) for x in values)
        last = None

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                nonlocal last
                last = next(stamps, last)
                if last is None:
                    raise AssertionError("test wall clock exhausted")
                return cls.fromisoformat(last.isoformat()).astimezone(tz or timezone.utc)

        return patch.object(closed_loop, "datetime", Clock)

    def assert_empty_freeze(self):
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM game_runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 0)

    def test_elapsed_prediction_or_lock_wait_cannot_use_entry_time_to_freeze_late(self):
        # Removing the post-lock clock check would admit six late forecasts.
        with self.clock("2026-10-24T12:59:59+00:00", "2026-10-24T13:00:00+00:00"):
            with self.assertRaisesRegex(core.GateError, "GAME_FREEZE_AFTER_CUTOFF"):
                closed_loop.advance_game_workspace(self.ws, snapshot=self.snap)
        self.assert_empty_freeze()

    def test_cutoff_crossed_during_inserts_rolls_back_entire_six_arm_transaction(self):
        # Removing the pre-commit check would publish an entire late batch.
        with self.clock("2026-10-24T12:59:57+00:00", "2026-10-24T12:59:58+00:00",
                        "2026-10-24T13:00:00+00:00"):
            with self.assertRaisesRegex(core.GateError, "GAME_FREEZE_AFTER_CUTOFF"):
                closed_loop.advance_game_workspace(self.ws, snapshot=self.snap)
        self.assert_empty_freeze()

    def test_local_freeze_timestamp_records_precommit_observation_not_tick_entry(self):
        # A stale stored timestamp would conceal time spent computing/waiting.
        with self.clock("2026-10-24T12:59:55+00:00", "2026-10-24T12:59:56+00:00",
                        "2026-10-24T12:59:57+00:00"):
            first = closed_loop.advance_game_workspace(self.ws, snapshot=self.snap)
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            frozen = conn.execute("SELECT frozen_at_local_untrusted FROM game_runs").fetchone()[0]
        self.assertEqual(frozen, "2026-10-24T12:59:57+00:00")
        self.assertEqual(len(first["frozen_cards"]), 6)
        self.assertEqual(first["formal_A"], 0)
        with self.clock("2026-10-24T14:00:00+00:00"):
            replay = closed_loop.advance_game_workspace(self.ws, snapshot=self.snap)
        self.assertEqual(replay["frozen_cards"], first["frozen_cards"])


if __name__ == "__main__":
    unittest.main()
