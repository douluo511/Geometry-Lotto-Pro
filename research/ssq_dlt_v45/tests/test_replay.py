"""Real temporary SQLite persistence/fault tests; synthetic outcomes only."""
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from research.ssq_dlt_v45.competition import make_plan
from research.ssq_dlt_v45.models import ModelBlocked, generate
from research.ssq_dlt_v45.replay import (
    ReplayBlocked, record_draw, record_prediction, register_plan, replay_ready,
    write_replay_report,
)
from research.ssq_dlt_v45.store import Store, digest


T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


class ReplayPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "replay.sqlite3"
        self.store = Store(self.path)
        self.issues = ["2026101", "2026102"]
        self.plan = make_plan("SSQ", self.issues, T0.isoformat(), "synthetic-prospective-series")

    def register(self):
        return register_plan(self.store, self.plan, now=T0)

    def freeze(self, trial_id, issue, when):
        prediction = generate("SSQ", issue, [])
        self.assertTrue(record_prediction(self.store, trial_id, prediction, when.isoformat(), when))
        return prediction

    def draw(self, trial_id, issue, when, evidence=None):
        return record_draw(self.store, trial_id, issue, [1, 2, 3, 4, 5, 6], [1],
                            when.isoformat(), when + timedelta(minutes=1), source_evidence=evidence)

    def test_no_trial_and_missing_issue_status_are_explicit(self):
        self.assertEqual(replay_ready(self.store)["status"], "BLOCKED_NO_REGISTERED_TRIALS")
        trial_id = self.register()
        output = replay_ready(self.store)
        self.assertEqual(output["trials"][0]["status"], "BLOCKED_MISSING_ISSUES")
        self.assertEqual(output["trials"][0]["missing_predictions"], self.issues)
        self.assertEqual(output["trials"][0]["missing_draws"], self.issues)
        self.assertEqual(output["formal_A"], 0)
        self.assertEqual(self.store.rows("r45_replay_result"), [])

    def test_true_database_restart_replay_and_duplicate_retry_are_immutable(self):
        trial_id = self.register()
        for index, issue in enumerate(self.issues):
            freeze_at = T0 + timedelta(days=index + 1)
            prediction = self.freeze(trial_id, issue, freeze_at)
            self.assertTrue(self.draw(trial_id, issue, freeze_at + timedelta(hours=13)))
            self.assertFalse(record_prediction(self.store, trial_id, prediction, freeze_at.isoformat(),
                                               freeze_at + timedelta(hours=14)))
        self.store = Store(self.path)  # New SQLite connection / process-state surrogate.
        first = replay_ready(self.store)
        self.assertEqual(first["status"], "REPLAYED_RESEARCH_ONLY")
        self.assertEqual(first["trials"][0]["evaluation"]["n"], 2)
        self.assertEqual((first["formal_A"], first["decision"]), (0, "NO_EDGE"))
        self.assertTrue(first["trials"][0]["evaluation"]["formal_12_family"].startswith("BLOCKED"))
        self.assertEqual(len(self.store.rows("r45_replay_result")), 1)
        self.store = Store(self.path)
        self.assertEqual(replay_ready(self.store), first)
        self.assertEqual(len(self.store.rows("r45_replay_result")), 1)
        with self.store.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM events WHERE kind='r45_replay_result'")

    def test_writer_process_exits_then_new_process_replays_committed_database(self):
        writer = """
from datetime import datetime, timedelta, timezone
import sys
from research.ssq_dlt_v45.store import Store
from research.ssq_dlt_v45.competition import make_plan
from research.ssq_dlt_v45.models import generate
from research.ssq_dlt_v45.replay import register_plan, record_prediction, record_draw
start = datetime(2026, 10, 1, tzinfo=timezone.utc)
store = Store(sys.argv[1])
plan = make_plan('SSQ', ['2026101'], start.isoformat(), 'separate-process-fixture')
trial = register_plan(store, plan, now=start)
freeze = start + timedelta(days=1)
record_prediction(store, trial, generate('SSQ', '2026101', []), freeze, freeze)
draw = freeze + timedelta(hours=13)
record_draw(store, trial, '2026101', [1,2,3,4,5,6], [1], draw, draw+timedelta(minutes=1))
print(trial)
"""
        reader = """
import json, sys
from research.ssq_dlt_v45.store import Store
from research.ssq_dlt_v45.replay import replay_ready
store = Store(sys.argv[1])
result = replay_ready(store)
print(json.dumps({'status': result['status'], 'formal_A': result['formal_A'],
                  'decision': result['decision'], 'results': len(store.rows('r45_replay_result'))}))
"""
        root = Path(__file__).resolve().parents[3]
        write = subprocess.run([sys.executable, "-c", writer, str(self.path)], cwd=root,
                                text=True, capture_output=True, check=True)
        self.assertEqual(len(write.stdout.strip()), 64)
        read = subprocess.run([sys.executable, "-c", reader, str(self.path)], cwd=root,
                               text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(read.stdout), {"status": "REPLAYED_RESEARCH_ONLY",
                                                   "formal_A": 0, "decision": "NO_EDGE", "results": 1})
        self.assertEqual(len(Store(self.path).rows("r45_replay_result")), 1)

    def test_missing_period_is_never_dropped_to_improve_results(self):
        trial_id = self.register()
        when = T0 + timedelta(days=1)
        self.freeze(trial_id, self.issues[0], when)
        self.draw(trial_id, self.issues[0], when + timedelta(hours=13))
        result = replay_ready(Store(self.path))["trials"][0]
        self.assertEqual(result["status"], "BLOCKED_MISSING_ISSUES")
        self.assertEqual(result["missing_predictions"], [self.issues[1]])
        self.assertEqual(self.store.rows("r45_replay_result"), [])

    def test_prediction_requires_plan_assigned_issue_and_current_clock(self):
        p = generate("SSQ", self.issues[0], [])
        with self.assertRaisesRegex(ReplayBlocked, "REGISTERED_TRIAL"):
            record_prediction(self.store, "0" * 64, p, T0.isoformat(), T0)
        trial_id = self.register()
        with self.assertRaisesRegex(ReplayBlocked, "BACKDATED"):
            record_prediction(self.store, trial_id, p, T0.isoformat(), T0 + timedelta(hours=1))
        for issue in ("UNASSIGNED", "2026199"):
            with self.subTest(issue=issue), self.assertRaisesRegex(ReplayBlocked, "ASSIGNED_ISSUE"):
                record_prediction(self.store, trial_id, generate("SSQ", issue, []), T0.isoformat(), T0)
        self.assertEqual(self.store.rows("r45_prediction"), [])

    def test_outcome_first_rejects_post_draw_prediction_after_restart(self):
        trial_id = self.register()
        draw_at = T0 + timedelta(days=1)
        self.draw(trial_id, self.issues[0], draw_at)
        self.store = Store(self.path)
        now = draw_at + timedelta(hours=1)
        with self.assertRaisesRegex(ReplayBlocked, "POST_DRAW"):
            record_prediction(self.store, trial_id, generate("SSQ", self.issues[0], []), now.isoformat(), now)
        result = replay_ready(self.store)["trials"][0]
        self.assertEqual(result["status"], "BLOCKED_MISSING_ISSUES")
        self.assertEqual(result["missing_predictions"], self.issues)

    def test_other_registered_trial_cannot_backfill_observed_outcome(self):
        trial_id = self.register()
        other_plan = make_plan("SSQ", self.issues, T0.isoformat(), "other-series")
        other_id = register_plan(self.store, other_plan, now=T0)
        draw_at = T0 + timedelta(days=1)
        self.draw(trial_id, self.issues[0], draw_at)
        now = draw_at + timedelta(hours=1)
        with self.assertRaisesRegex(ReplayBlocked, "POST_DRAW"):
            record_prediction(self.store, other_id, generate("SSQ", self.issues[0], []), now.isoformat(), now)
        later_plan = make_plan("SSQ", self.issues, T0.isoformat(), "third-series")
        with self.assertRaisesRegex(ReplayBlocked, "AFTER_OUTCOME"):
            register_plan(self.store, later_plan, now=now)

    def test_new_plan_cannot_use_claimed_old_time_to_backdate(self):
        accepted = T0 + timedelta(days=10)
        trial_id = register_plan(self.store, self.plan, now=accepted)
        with self.assertRaisesRegex(ReplayBlocked, "CLOCK_ROLLBACK"):
            record_prediction(self.store, trial_id, generate("SSQ", self.issues[0], []), T0.isoformat(), T0)
        self.assertEqual(self.store.read("r45_trial", trial_id)["accepted_at"], accepted.isoformat())

    def test_local_clock_rollback_future_draw_and_pre_freeze_draw_rejected(self):
        trial_id = self.register()
        now = T0 + timedelta(days=1)
        self.freeze(trial_id, self.issues[0], now)
        before = now - timedelta(minutes=1)
        with self.assertRaisesRegex(ReplayBlocked, "CLOCK_ROLLBACK"):
            record_prediction(self.store, trial_id, generate("SSQ", self.issues[1], []), before.isoformat(), before)
        with self.assertRaisesRegex(ReplayBlocked, "FUTURE_DRAW"):
            record_draw(self.store, trial_id, self.issues[0], [1, 2, 3, 4, 5, 6], [1], now + timedelta(days=1), now)
        with self.assertRaisesRegex(ReplayBlocked, "NOT_BEFORE_DRAW"):
            self.draw(trial_id, self.issues[0], now)

    def test_prediction_change_and_draw_source_conflict_are_rejected(self):
        trial_id = self.register()
        now = T0 + timedelta(days=1)
        p = self.freeze(trial_id, self.issues[0], now)
        p["history_size"] = 99
        with self.assertRaisesRegex(ReplayBlocked, "IMMUTABLE_PREDICTION"):
            record_prediction(self.store, trial_id, p, now.isoformat(), now)
        draw_at = now + timedelta(hours=13)
        self.draw(trial_id, self.issues[0], draw_at)
        self.assertFalse(self.draw(trial_id, self.issues[0], draw_at))
        with self.assertRaisesRegex(ReplayBlocked, "SOURCE_CONFLICT"):
            self.draw(trial_id, self.issues[0], draw_at, [{"authorized": True}])

    def test_caller_statistics_and_fake_authorization_never_grant_admission(self):
        trial_id = self.register()
        malicious_metadata = [{"authorized": True, "formal_A": 999,
                               "statistics": {"D2_full": 150, "n": 152}, "tsa_verified": True}]
        for index, issue in enumerate(self.issues):
            now = T0 + timedelta(days=index + 1)
            self.freeze(trial_id, issue, now)
            self.draw(trial_id, issue, now + timedelta(hours=13), malicious_metadata)
        result = replay_ready(self.store)
        self.assertEqual((result["formal_A"], result["decision"]), (0, "NO_EDGE"))
        self.assertTrue(result["formal_eligibility"].startswith("BLOCKED"))
        self.assertEqual(result["trials"][0]["evaluation"]["n"], 2)

    def test_changed_plan_and_null_seed_fail_before_database_write(self):
        trial_id = self.register()
        altered = dict(self.plan, alpha=1.0)
        with self.assertRaisesRegex(ReplayBlocked, "PLAN_REPLACED"):
            register_plan(self.store, altered, now=T0)
        p = generate("SSQ", self.issues[0], [], seed=123)
        with self.assertRaisesRegex(ReplayBlocked, "FIXED_SEED"):
            record_prediction(self.store, trial_id, p, T0.isoformat(), T0)
        self.assertEqual(self.store.rows("r45_prediction"), [])

    def test_blocked_report_has_verified_json_csv_html_and_exact_retry(self):
        result = replay_ready(self.store)
        directory = Path(self.folder.name) / "reports"
        folder = write_replay_report(directory, result)
        self.assertEqual(folder, write_replay_report(directory, result))
        self.assertEqual(json.loads((folder / "replay.json").read_text("utf-8")), result)
        manifest = json.loads((folder / "SHA256.json").read_text("utf-8"))
        for name, sha in manifest["files"].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), sha)
        self.assertIn("BLOCKED_NO_REGISTERED_TRIALS", (folder / "replay.html").read_text("utf-8"))
        self.assertIn("formal_A=0", (folder / "replay.html").read_text("utf-8"))
        with (folder / "replay.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["status"], "BLOCKED_NO_REGISTERED_TRIALS")
        self.assertEqual(len(list(directory.iterdir())), 1)

    def test_report_tamper_fails_closed_without_overwriting(self):
        result = replay_ready(self.store)
        directory = Path(self.folder.name) / "reports"
        folder = write_replay_report(directory, result)
        (folder / "replay.html").write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(ReplayBlocked, "FILE_SHA_MISMATCH"):
            write_replay_report(directory, result)
        self.assertEqual((folder / "replay.html").read_text("utf-8"), "modified")

    def test_complete_report_csv_contains_all_period_dk_and_paired_tests(self):
        trial_id = self.register()
        for index, issue in enumerate(self.issues):
            when = T0 + timedelta(days=index + 1)
            self.freeze(trial_id, issue, when)
            self.draw(trial_id, issue, when + timedelta(hours=13))
        result = replay_ready(self.store)
        folder = write_replay_report(Path(self.folder.name) / "reports", result)
        with (folder / "replay.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        periods = [row for row in rows if row["row_type"] == "period"]
        paired = [row for row in rows if row["row_type"] == "paired_comparison"]
        self.assertEqual(len(periods), 2 * 5 * 5)
        self.assertEqual(len(paired), 4)
        self.assertTrue(all(row["formal_A"] == "0" for row in rows))
        self.assertIn("研究 Holm", (folder / "replay.html").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
