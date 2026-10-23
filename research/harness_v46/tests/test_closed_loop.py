"""Single-entry SHADOW lifecycle integration: synthetic fixtures only.

No test data may be treated as an actual lottery prediction or a formal A trial.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46 import core, prospective_cycle
from research.harness_v46.tests.test_core import fixture


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "workspace"
        self.before = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
        self.after = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
        self.snapshots = {game: fixture(game) for game in core.RULES}

    def runner(self):
        from research.harness_v46 import closed_loop
        return closed_loop

    def outcome(self, issue="29999"):
        return {
            game: {
                "lottery": game, "issue": issue,
                "front": list(self.snapshots[game]["draws"][-2]["front"]),
                "back": list(self.snapshots[game]["draws"][-2]["back"]),
                "drawn_at": "2026-10-23T21:05:00+08:00",
            } for game in core.RULES
        }

    def write_outcome(self, run_id, value):
        root = self.workspace / "outcomes"
        root.mkdir(parents=True, exist_ok=True)
        (root / (run_id + ".json")).write_text(
            json.dumps(value), encoding="utf-8")

    def test_single_entrypoint_freeze_score_study_and_idempotent_replay(self):
        app = self.runner()
        first = app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)
        self.assertEqual(first["status"], "WAITING_FOR_OUTCOME")
        self.assertEqual(first["pending_run_count"], 1)
        self.assertEqual(first["formal_A"], 0)
        self.assertEqual(first["decision"], "NO_EDGE")
        run_id = first["run_ids"][0]
        db = self.workspace / "ledger.sqlite3"
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)
        original_db = hashlib.sha256(db.read_bytes()).hexdigest()
        self.write_outcome(run_id, self.outcome())
        second = app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertEqual(second["status"], "STUDY_SHADOW_READY")
        self.assertEqual(second["pending_run_count"], 0)
        self.assertEqual(second["study"]["draws_by_game"], {"SSQ": 1, "DLT": 1})
        self.assertEqual(second["study"]["statistical_analysis"]["family_size"], 12)
        self.assertEqual(second["formal_A"], 0)
        self.assertEqual(second["decision"], "NO_EDGE")
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), original_db)
        score_file = self.workspace / "receipts" / (run_id + ".json")
        before_bytes = score_file.read_bytes()
        third = app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertEqual(second, third)
        self.assertEqual(score_file.read_bytes(), before_bytes)

    def test_missing_input_does_not_make_fictional_future_run(self):
        with self.assertRaisesRegex(core.GateError, "NO_REGISTERED_RUN_OR_SNAPSHOT"):
            self.runner().advance_workspace(self.workspace, observed_at=self.before)
        self.assertFalse((self.workspace / "ledger.sqlite3").exists())

    def test_unscored_freeze_forbids_selective_study(self):
        app = self.runner()
        first = app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)
        other = {g: dict(s, target_issue="30000") for g, s in self.snapshots.items()}
        app.advance_workspace(self.workspace, snapshots=other, observed_at=self.before)
        # A real later outcome must not be presented while the draw is still
        # in the future. Add it only after the second pre-draw freeze completes.
        self.write_outcome(first["run_ids"][0], self.outcome())
        report = app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertEqual(report["status"], "WAITING_FOR_OUTCOME")
        self.assertEqual(report["pending_run_count"], 1)
        self.assertNotIn("study", report)
        self.assertEqual(report["completed_run_count"], 1)

    def test_wrong_result_rejected_without_receipt_or_frozen_mutation(self):
        app = self.runner()
        run_id = app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)["run_ids"][0]
        wrong = self.outcome()
        wrong["SSQ"]["issue"] = "30000"
        self.write_outcome(run_id, wrong)
        db = self.workspace / "ledger.sqlite3"
        original_db = hashlib.sha256(db.read_bytes()).hexdigest()
        with self.assertRaisesRegex(core.GateError, "RESULT_ISSUE_DIFFERS"):
            app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertFalse((self.workspace / "receipts" / (run_id + ".json")).exists())
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), original_db)

    def test_changed_caller_outcome_does_not_rewrite_score_receipt(self):
        app = self.runner()
        run_id = app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)["run_ids"][0]
        self.write_outcome(run_id, self.outcome())
        app.advance_workspace(self.workspace, observed_at=self.after)
        receipt = self.workspace / "receipts" / (run_id + ".json")
        before = receipt.read_bytes()
        changed = self.outcome()
        changed["SSQ"]["front"] = [1, 2, 3, 4, 5, 6]
        self.write_outcome(run_id, changed)
        with self.assertRaisesRegex(core.GateError, "SCORE_RECEIPT_CONFLICT"):
            app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertEqual(receipt.read_bytes(), before)

    def test_unknown_outcome_file_is_not_silently_ignored(self):
        app = self.runner()
        app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)
        self.write_outcome("V47-unknown", self.outcome())
        with self.assertRaisesRegex(core.GateError, "UNKNOWN_OUTCOME_RUN"):
            app.advance_workspace(self.workspace, observed_at=self.after)

    def test_recovers_original_freeze_without_reforecast(self):
        app = self.runner()
        self.workspace.mkdir(parents=True)
        ledger = self.workspace / "ledger.sqlite3"
        run_id = prospective_cycle.forecast_on_demand(
            self.snapshots, ledger, now=self.before)["run_id"]
        before = ledger.read_bytes()
        self.write_outcome(run_id, self.outcome())
        report = app.advance_workspace(self.workspace, observed_at=self.after)
        self.assertEqual(report["status"], "STUDY_SHADOW_READY")
        self.assertEqual(ledger.read_bytes(), before)

    def test_real_subprocess_cli_runs_predraw_and_postdraw_paths(self):
        # Genuine Python subprocess invocations; ONLY invented test numbers.
        now = datetime.now(timezone.utc)
        future = {g: dict(s) for g, s in self.snapshots.items()}
        for snap in future.values():
            snap["as_of"] = (now - timedelta(minutes=5)).isoformat()
            snap["sales_cutoff"] = (now + timedelta(hours=2)).isoformat()
            snap["target_draw_at"] = (now + timedelta(hours=3)).isoformat()
        source = Path(self.tmp.name) / "synthetic_snapshots.json"
        source.write_text(json.dumps(future), encoding="utf-8")
        cmd = [sys.executable, "-m", "research.harness_v46.closed_loop",
               "--workspace", str(self.workspace)]
        early = subprocess.run(cmd + ["--snapshot-bundle", str(source)],
                               capture_output=True, text=True, timeout=45)
        self.assertEqual(early.returncode, 0, early.stderr)
        frozen = json.loads(early.stdout)
        self.assertEqual(frozen["status"], "WAITING_FOR_OUTCOME")
        self.assertEqual(frozen["formal_A"], 0)
        with sqlite3.connect(self.workspace / "ledger.sqlite3") as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)

        # Independent later CLI invocation against a historical synthetic
        # frozen ledger. Never time-travel the runtime to create a forecast.
        older = Path(self.tmp.name) / "older"
        older.mkdir()
        ledger = older / "ledger.sqlite3"
        run_id = prospective_cycle.forecast_on_demand(
            self.snapshots, ledger, now=self.before)["run_id"]
        originals = ledger.read_bytes()
        (older / "outcomes").mkdir()
        (older / "outcomes" / (run_id + ".json")).write_text(
            json.dumps(self.outcome()), encoding="utf-8")
        later = subprocess.run(
            [sys.executable, "-m", "research.harness_v46.closed_loop",
             "--workspace", str(older)],
            capture_output=True, text=True, timeout=45)
        self.assertEqual(later.returncode, 0, later.stderr)
        report = json.loads(later.stdout)
        self.assertEqual(report["status"], "STUDY_SHADOW_READY")
        self.assertEqual(report["study"]["draws_by_game"], {"SSQ": 1, "DLT": 1})
        self.assertEqual(ledger.read_bytes(), originals)

    def test_cannot_score_target_draw_in_future(self):
        app = self.runner()
        run_id = app.advance_workspace(
            self.workspace, snapshots=self.snapshots, observed_at=self.before)["run_ids"][0]
        self.write_outcome(run_id, self.outcome())
        with self.assertRaisesRegex(core.GateError, "SCORE_BEFORE_LOCKED_TARGET_DRAW_TIME"):
            app.advance_workspace(self.workspace, observed_at=self.before)
        self.assertFalse((self.workspace / "receipts" / (run_id + ".json")).exists())


if __name__ == "__main__":
    unittest.main()
