"""Synthetic real Windows caller-to-ledger checks; never install a task."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46 import official_intake
from research.harness_v46.tests.test_core import fixture

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Actual Windows operational caller")
class WindowsOperationalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.exe = shutil.which("powershell.exe")
        if not self.exe:
            self.skipTest("Windows PowerShell unavailable")
        # Extended cleanup namespace avoids a test-only Windows path limit.
        self.tmp = tempfile.TemporaryDirectory(
            dir=official_intake._physical_root(tempfile.gettempdir()))
        self.addCleanup(self.tmp.cleanup)
        name = str(self.tmp.name)
        if name.startswith("\\\\?\\UNC\\"):
            name = "\\\\" + name[8:]
        elif name.startswith("\\\\?\\"):
            name = name[4:]
        self.base = Path(name)
        self.workspace = self.base / "state with spaces"
        self.config = {
            "repository_root": str(ROOT.parents[1]),
            "python_exe": sys.executable,
            "workspace": str(self.workspace),
            "log_path": str(self.base / "bot.log"),
            "operational_tick": True,
            "intake_timeout_seconds": 0.001,
        }

    def snapshot(self, game):
        now = datetime.now(timezone.utc)
        snap = fixture(game)
        snap.update(
            as_of=(now - timedelta(minutes=10)).isoformat(),
            sales_cutoff=(now + timedelta(hours=3)).isoformat(),
            target_draw_at=(now + timedelta(hours=4)).isoformat(),
        )
        path = self.base / (game + " future snapshot.json")
        path.write_text(json.dumps(snap), encoding="utf-8")
        return str(path)

    def invoke(self):
        cfg = self.base / "bot config.json"
        cfg.write_text(json.dumps(self.config), encoding="utf-8")
        # No execution-policy override: exercise the actual default entrypoint.
        return subprocess.run(
            [self.exe, "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "invoke_closed_loop.ps1"), "-ConfigFile", str(cfg)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=75,
        )

    def state(self):
        with closing(sqlite3.connect(self.workspace / "ledger.sqlite3")) as con:
            events = con.execute(
                "SELECT event_type,lottery,event_payload FROM operational_events "
                "ORDER BY event_id").fetchall()
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("game_predictions", tables,
                          "Explicit synthetic snapshots never reached the freeze entrypoint")
            predictions = dict(con.execute(
                "SELECT r.lottery,count(*) FROM game_predictions p "
                "JOIN game_runs r ON r.run_id=p.run_id GROUP BY r.lottery"))
            frozen = (
                con.execute("SELECT * FROM game_runs ORDER BY run_id").fetchall(),
                con.execute("SELECT * FROM game_predictions "
                            "ORDER BY run_id,model").fetchall(),
            )
        return events, predictions, frozen

    def test_explicit_paths_freeze_both_synthetic_games_and_retry_reuses_cards(self):
        self.config.update(ssq_snapshot_path=self.snapshot("SSQ"),
                           dlt_snapshot_path=self.snapshot("DLT"))
        before = None
        original_frozen = None
        for count in (1, 2):
            run = self.invoke()
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            events, predictions, frozen = self.state()
            self.assertEqual(predictions, {"SSQ": 6, "DLT": 6})
            self.assertEqual(len(events), count * 4)
            if before is not None:
                self.assertEqual(events[:len(before)], before)
                self.assertEqual(frozen, original_frozen)
            before = events
            original_frozen = frozen
            end = json.loads(events[-1][2])["result"]
            self.assertEqual(end["local_frozen_issue_count"], 2)
            self.assertEqual(end["new_frozen_issue_count"], 2 if count == 1 else 0)
            self.assertEqual(end["formal_A"], 0)
            self.assertEqual(end["formal_future_denominator"], "NOT_VERIFIED")
            self.assertEqual(end["decision"], "NO_EDGE")

    def test_bad_ssq_snapshot_still_freezes_only_valid_synthetic_dlt(self):
        bad = self.base / "broken SSQ.json"
        bad.write_text('{"truncated":', encoding="utf-8")
        self.config.update(ssq_snapshot_path=str(bad),
                           dlt_snapshot_path=self.snapshot("DLT"))
        run = self.invoke()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        events, predictions, _ = self.state()
        self.assertEqual(predictions, {"DLT": 6})
        self.assertEqual([r[0] for r in events],
                         ["STARTED", "GAME_RESULT", "GAME_RESULT", "FINISHED"])
        result = json.loads(events[-1][2])["result"]
        self.assertEqual(result["games"]["SSQ"]["target_gate"],
                         "BLOCKED_NO_EXPLICIT_SNAPSHOT")
        self.assertIn("target_error", result["games"]["SSQ"])
        self.assertEqual(result["new_frozen_issue_count"], 1)
        self.assertEqual(result["formal_A"], 0)

    def test_new_paths_reject_wrong_mode_and_preserve_legacy_conflict(self):
        self.config["ssq_snapshot_path"] = self.snapshot("SSQ")
        for index, (fields, message) in enumerate((
            ({"operational_tick": False},
             "CLOSED_LOOP_SNAPSHOT_PATH_REQUIRES_OPERATIONAL_MODE"),
            ({"operational_tick": False, "ssq_snapshot_path": ""},
             "CLOSED_LOOP_SNAPSHOT_PATH_REQUIRES_OPERATIONAL_MODE"),
            ({"operational_tick": False, "ssq_snapshot_path": None},
             "CLOSED_LOOP_SNAPSHOT_PATH_REQUIRES_OPERATIONAL_MODE"),
            ({"operational_tick": True, "dlt_snapshot_bundle": "old.json"},
             "CLOSED_LOOP_OPERATIONAL_MODE_INPUTS_CONFLICT"),
        )):
            with self.subTest(fields=fields):
                workspace = self.base / ("mode-" + str(index))
                log = self.base / ("mode-" + str(index) + ".log")
                self.config.update(workspace=str(workspace), log_path=str(log))
                self.config.update(fields)
                run = self.invoke()
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(message, run.stdout + run.stderr)
                self.assertFalse(workspace.exists())
                self.assertFalse(log.exists())

    def test_timeout_above_host_budget_rejects_before_python_or_log_start(self):
        # If validation regresses, Python exits immediately on the file workspace;
        # this test does not spend the invalid120.001-second source budget.
        self.workspace.write_text("not a directory", encoding="utf-8")
        self.config["intake_timeout_seconds"] = 120.001
        run = self.invoke()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("CLOSED_LOOP_OPERATIONAL_TIMEOUT_INVALID",
                      run.stdout + run.stderr)
        self.assertFalse((self.base / "bot.log").exists())


if __name__ == "__main__":
    unittest.main()

