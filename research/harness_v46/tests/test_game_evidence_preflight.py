"""Adversarial SHADOW-only tests: invalid preexisting evidence must not leave an irreversible new game freeze."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture


class GameEvidencePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = self.root / "workspace"
        self.snapshot = fixture("DLT")
        self.snapshot.update(
            as_of="2026-10-24T09:00:00+00:00",
            sales_cutoff="2026-10-24T13:00:00+00:00",
            target_draw_at="2026-10-24T13:25:00+00:00",
            target_issue="26250",
        )
        self.observed = datetime.fromisoformat("2026-10-24T10:00:00+00:00")

    def tick(self):
        return closed_loop.advance_game_workspace(
            self.ws, snapshot=self.snapshot, observed_at=self.observed
        )

    def assert_no_new_freeze(self):
        ledger = self.ws / "ledger.sqlite3"
        if ledger.exists():
            with closing(sqlite3.connect(ledger)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM game_runs").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM game_predictions").fetchone()[0], 0)

    def test_unknown_prior_outcome_blocks_before_new_six_arm_freeze(self):
        folder = self.ws / "outcomes_by_game" / "DLT"
        folder.mkdir(parents=True)
        (folder / "99999.json").write_text('{"unverified":true}', encoding="utf-8")
        with self.assertRaisesRegex(core.GateError, "GAME_UNKNOWN_OUTCOME_ISSUE"):
            self.tick()
        self.assert_no_new_freeze()

    def test_unknown_prior_receipt_blocks_before_new_six_arm_freeze(self):
        folder = self.ws / "receipts_by_game" / "DLT"
        folder.mkdir(parents=True)
        (folder / "99999.json").write_text('{"unverified":true}', encoding="utf-8")
        with self.assertRaisesRegex(core.GateError, "GAME_UNKNOWN_SCORE_RECEIPT"):
            self.tick()
        self.assert_no_new_freeze()

    def test_non_directory_evidence_path_blocks_before_freeze(self):
        folder = self.ws / "outcomes_by_game"
        folder.mkdir(parents=True)
        (folder / "DLT").write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(core.GateError, "GAME_EVIDENCE_DIRECTORY_REQUIRED"):
            self.tick()
        self.assert_no_new_freeze()

    def test_untrusted_other_game_outcome_does_not_block_dlt_tick(self):
        other = self.ws / "outcomes_by_game" / "SSQ"
        other.mkdir(parents=True)
        (other / "99999.json").write_text('{"unverified":true}', encoding="utf-8")
        status = self.tick()
        self.assertEqual(status["lottery"], "DLT")
        self.assertEqual(status["pending_issues"], ["26250"])
        self.assertEqual(len(status["frozen_cards"]), 6)
        self.assertEqual(status["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
