"""Superpowers adversarial check: challenger diagnostic never promotes frozen arms."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture


class ClosedLoopChallengerTests(unittest.TestCase):
    def test_single_runner_exposes_exploratory_lab_without_replacing_six_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            history = {game: fixture(game, size=145) for game in core.RULES}
            report = closed_loop.advance_workspace(
                workspace, snapshots=history, research_history=history,
                observed_at=datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
            )
            self.assertEqual(report["status"], "WAITING_FOR_OUTCOME")
            lab = report["research_diagnostic"]
            self.assertEqual(lab["model"], "RECENCY_PAIR_H45_120_V1")
            self.assertEqual(lab["draws_by_game"], {"SSQ": 25, "DLT": 25})
            self.assertEqual(lab["evidence_class"],
                             "RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE")
            self.assertFalse(lab["qualified_prospective"])
            self.assertEqual(lab["formal_A"], 0)
            self.assertEqual(report["formal_A"], 0)
            self.assertEqual(report["decision"], "NO_EDGE")
            with closing(sqlite3.connect(workspace / "ledger.sqlite3")) as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)
                names={v[0] for v in c.execute("SELECT DISTINCT model FROM predictions")}
                self.assertEqual(names, set(core.MODELS))

    def test_absent_optional_history_does_not_forge_experimental_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = closed_loop.advance_workspace(
                Path(tmp) / "workspace",
                snapshots={game: fixture(game) for game in core.RULES},
                observed_at=datetime(2026, 10, 20, 8, tzinfo=timezone.utc))
            self.assertNotIn("research_diagnostic", report)
            self.assertEqual(report["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
