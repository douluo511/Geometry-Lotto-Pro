"""Operational attempts are local SHADOW records, never official draw coverage.

Network collection is doubled only at its external boundary. Ledger, snapshot
validation, six-arm freezes, outcome scoring and subprocess CLI remain real.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from research.harness_v46 import closed_loop, core, official_intake
from research.harness_v46.tests.test_core import fixture


class OperationalTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ws = self.base / "persist"
        self.calls = []

    def tick(self, **kwargs):
        entry = getattr(closed_loop, "operational_tick", None)
        self.assertTrue(callable(entry), "missing operational_tick entrypoint")
        return entry(self.ws, **kwargs)

    def collect(self, game, *, timeout_seconds):
        self.calls.append((game, timeout_seconds))
        return {
            "schema": official_intake.SCHEMA, "lottery": game,
            "status": "BLOCKED", "sources": [], "consensus_draws": [],
            "errors": {"synthetic_network_boundary": "OFFLINE_TEST"},
            "official_history_admission": "BLOCKED",
            "official_target_admission": "BLOCKED", "formal_A": 0,
            "decision": "NO_EDGE",
        }

    def events(self):
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            return conn.execute(
                "SELECT tick_id,event_type,lottery,event_payload,event_sha256 "
                "FROM operational_events ORDER BY event_id"
            ).fetchall()

    def snapshot_file(self, game, *, future=False):
        snap = fixture(game)
        if future:
            now = datetime.now(timezone.utc)
            snap.update(as_of=(now - timedelta(minutes=5)).isoformat(),
                        sales_cutoff=(now + timedelta(hours=2)).isoformat(),
                        target_draw_at=(now + timedelta(hours=3)).isoformat())
        path = self.base / (game + "-snapshot.json")
        path.write_text(json.dumps(snap), encoding="utf-8")
        return snap, path

    def old_freeze(self, game="SSQ", *, outcome=True):
        snap, _ = self.snapshot_file(game)
        closed_loop.advance_game_workspace(
            self.ws, snapshot=snap, game=game,
            observed_at=datetime(2026, 10, 20, 8, tzinfo=timezone.utc))
        if outcome:
            folder = self.ws / "outcomes_by_game" / game
            folder.mkdir(parents=True, exist_ok=True)
            draw = snap["draws"][-2]
            (folder / (snap["target_issue"] + ".json")).write_text(json.dumps({
                "lottery": game, "issue": snap["target_issue"],
                "front": draw["front"], "back": draw["back"],
                "drawn_at": snap["target_draw_at"],
            }), encoding="utf-8")
        return snap

    def test_missing_targets_record_both_source_attempts_without_invented_freezes(self):
        with patch.object(official_intake, "collect_live_history", self.collect):
            result = self.tick(intake_timeout_seconds=0.25)
        self.assertEqual(self.calls, [("SSQ", 0.25), ("DLT", 0.25)])
        self.assertEqual(result["new_frozen_issue_count"], 0)
        self.assertEqual(result["local_frozen_issue_count"], 0)
        self.assertEqual(result["operational_attempt_count"], 1)
        self.assertEqual(result["formal_future_denominator"], "NOT_VERIFIED")
        self.assertEqual(result["coverage"],
                         "ATTEMPTS_AND_LOCAL_FROZEN_ROSTER_NOT_OFFICIAL_CALENDAR")
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")
        self.assertEqual([r[1] for r in self.events()],
                         ["STARTED", "GAME_RESULT", "GAME_RESULT", "FINISHED"])
        for game in ("SSQ", "DLT"):
            state = result["games"][game]
            self.assertEqual(state["target_gate"], "BLOCKED_NO_EXPLICIT_SNAPSHOT")
            manifest = Path(state["intake_manifest_path"])
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),
                             state["intake_manifest_sha256"])
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(saved["games"][game]["errors"],
                             {"synthetic_network_boundary": "OFFLINE_TEST"})

    def test_start_is_committed_before_collection_with_real_local_clock(self):
        observed = []
        earliest = datetime.now(timezone.utc)

        def check(game, *, timeout_seconds):
            events = self.events()
            self.assertEqual(events[0][1], "STARTED")
            observed.append(json.loads(events[0][3]))
            return self.collect(game, timeout_seconds=timeout_seconds)

        with patch.object(official_intake, "collect_live_history", check):
            result = self.tick()
        event = observed[0]
        when = datetime.fromisoformat(event["observed_at_local_untrusted"])
        self.assertLessEqual(earliest, when)
        self.assertLessEqual(when, datetime.now(timezone.utc))
        self.assertEqual(event["tick_id"], result["tick_id"])
        self.assertEqual(event["runner_source_sha256"], hashlib.sha256(
            Path(closed_loop.__file__).read_bytes()).hexdigest())
        self.assertNotIn("observed_at", result)

    def test_source_exception_is_retained_and_other_game_still_attempted(self):
        def collect(game, *, timeout_seconds):
            if game == "SSQ":
                self.calls.append((game, timeout_seconds))
                raise OSError("synthetic SSQ transport failure")
            return self.collect(game, timeout_seconds=timeout_seconds)

        with patch.object(official_intake, "collect_live_history", collect):
            result = self.tick()
        self.assertEqual([g for g, _ in self.calls], ["SSQ", "DLT"])
        self.assertIn("synthetic SSQ transport failure",
                      json.dumps(result["games"]["SSQ"]))
        self.assertTrue(Path(result["games"]["SSQ"]["intake_manifest_path"]).exists())
        self.assertEqual(self.events()[-1][1], "FINISHED")

    def test_bad_and_late_snapshots_keep_old_frozen_score_path_available(self):
        original = self.old_freeze()
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            cards = conn.execute("SELECT * FROM game_predictions ORDER BY model").fetchall()
        _, late = self.snapshot_file("SSQ")
        malformed = self.base / "malformed.json"
        malformed.write_text('{"lottery":"SSQ","lottery":"DLT"}', encoding="utf-8")
        for path in (malformed, late):
            with self.subTest(path=path.name), patch.object(
                    official_intake, "collect_live_history", self.collect):
                result = self.tick(snapshot_paths={"SSQ": path})
                ssq = result["games"]["SSQ"]
                self.assertTrue(ssq["target_error"])
                self.assertEqual(ssq["scoring"]["completed_issues"], [original["target_issue"]])
                self.assertEqual(result["new_frozen_issue_count"], 0)
                self.assertEqual(result["local_scored_issue_count"], 1)
                with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
                    self.assertEqual(conn.execute(
                        "SELECT * FROM game_predictions ORDER BY model").fetchall(), cards)

    def test_explicit_future_snapshot_freezes_original_six_models_only_once(self):
        _, path = self.snapshot_file("DLT", future=True)
        with patch.object(official_intake, "collect_live_history", self.collect):
            first = self.tick(snapshot_paths={"DLT": path})
            second = self.tick(snapshot_paths={"DLT": path})
        self.assertEqual(first["new_frozen_issue_count"], 1)
        self.assertEqual(second["new_frozen_issue_count"], 0)
        self.assertEqual(second["local_pending_issue_count"], 1)
        self.assertNotEqual(first["tick_id"], second["tick_id"])
        self.assertNotEqual(first["games"]["DLT"]["intake_manifest_path"],
                            second["games"]["DLT"]["intake_manifest_path"])
        self.assertEqual(first["games"]["DLT"]["scoring"]["frozen_cards"],
                         second["games"]["DLT"]["scoring"]["frozen_cards"])
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM game_predictions").fetchone()[0], 6)
            self.assertEqual({r[0] for r in conn.execute("SELECT model FROM game_predictions")},
                             set(core.MODELS))

    def test_cross_game_snapshot_never_freezes_under_wrong_input_key(self):
        _, path = self.snapshot_file("DLT", future=True)
        with patch.object(official_intake, "collect_live_history", self.collect):
            result = self.tick(snapshot_paths={"SSQ": path})
        self.assertIn("GAME_SNAPSHOT_IDENTITY_MISMATCH", result["games"]["SSQ"]["target_error"])
        self.assertEqual(result["local_frozen_issue_count"], 0)

    def test_date_only_history_is_not_transformed_into_scoring_outcome(self):
        self.old_freeze(outcome=False)

        def date_only(game, *, timeout_seconds):
            value = self.collect(game, timeout_seconds=timeout_seconds)
            value["consensus_draws"] = [{"issue": "29999", "draw_date": "2026-10-23",
                                          "front": [1, 2, 3, 4, 5, 6], "back": [1]}]
            return value

        with patch.object(official_intake, "collect_live_history", date_only):
            result = self.tick()
        self.assertEqual(result["games"]["SSQ"]["scoring"]["pending_issues"], ["29999"])
        self.assertEqual(result["local_scored_issue_count"], 0)
        self.assertFalse((self.ws / "outcomes_by_game").exists())

    def test_artifact_write_failure_still_scores_old_roster_and_attempts_other_game(self):
        self.old_freeze()
        with patch.object(official_intake, "collect_live_history", self.collect), patch.object(
                official_intake, "write_bundle", side_effect=OSError("synthetic disk error")):
            result = self.tick()
        self.assertEqual([g for g, _ in self.calls], ["SSQ", "DLT"])
        self.assertEqual(result["games"]["SSQ"]["scoring"]["completed_issues"], ["29999"])
        self.assertIn("synthetic disk error", result["games"]["SSQ"]["artifact_error"])
        self.assertIn("OFFLINE_TEST", json.dumps(self.events()))

    def test_journal_rejects_update_delete_and_detects_changed_old_payload(self):
        with patch.object(official_intake, "collect_live_history", self.collect):
            self.tick()
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE operational_events SET event_payload='{}'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM operational_events")
            conn.execute("DROP TRIGGER protect_operational_events_update")
            conn.execute("UPDATE operational_events SET event_payload='{}' WHERE event_id=1")
            conn.commit()
        with patch.object(official_intake, "collect_live_history", self.collect):
            with self.assertRaisesRegex(core.GateError, "OPERATIONAL_EVENT"):
                self.tick()
        self.assertEqual(len(self.calls), 2, "corrupt journal must fail before another source call")

    def test_interrupted_tick_survives_and_next_tick_reports_unfinished_without_rewriting(self):
        with patch.object(official_intake, "collect_live_history", side_effect=SystemExit("stop")):
            with self.assertRaises(SystemExit):
                self.tick()
        before = self.events()
        self.assertEqual([r[1] for r in before], ["STARTED"])
        with patch.object(official_intake, "collect_live_history", self.collect):
            result = self.tick()
        self.assertIn(before[0][0], result["unfinished_prior_tick_ids"])
        self.assertEqual(self.events()[0], before[0])
        self.assertEqual(result["operational_attempt_count"], 2)

    def test_concurrent_ticks_preserve_four_events_and_distinct_capture_paths_each(self):
        with patch.object(official_intake, "collect_live_history", self.collect):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.tick(), range(2)))
        ids = {r["tick_id"] for r in results}
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(self.events()), 8)
        paths = [r["games"][g]["intake_manifest_path"] for r in results for g in ("SSQ", "DLT")]
        self.assertEqual(len(set(paths)), 4)
        self.assertTrue(all(Path(p).is_file() for p in paths))

    def test_parent_traversal_snapshot_blocker_does_not_stop_other_game(self):
        _, valid = self.snapshot_file("DLT", future=True)
        traversal = self.base / "other" / ".." / "SSQ.json"
        with patch.object(official_intake, "collect_live_history", self.collect):
            result = self.tick(snapshot_paths={"SSQ": traversal, "DLT": valid})
        self.assertIn("PARENT_TRAVERSAL", result["games"]["SSQ"]["target_error"])
        self.assertEqual(result["games"]["DLT"]["scoring"]["pending_issues"], ["29999"])

    def test_real_cli_starts_bounded_workers_and_saves_their_timeout_diagnostics(self):
        command = [sys.executable, "-m", "research.harness_v46.closed_loop",
                   "--workspace", str(self.ws), "--operational-tick",
                   "--intake-timeout-seconds", "0.01"]
        run = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["new_frozen_issue_count"], 0)
        self.assertEqual(result["formal_A"], 0)
        for game in ("SSQ", "DLT"):
            manifest = Path(result["games"][game]["intake_manifest_path"])
            intake = json.loads(manifest.read_text(encoding="utf-8"))["games"][game]
            self.assertEqual(intake["status"], "WORKER_OUTPUT_QUARANTINED")
            self.assertIn("TIMEOUT", intake["errors"]["worker_output_validation"])
            self.assertFalse(intake["worker_output_capture"]["capture_complete"])
        self.assertEqual([r[1] for r in self.events()],
                         ["STARTED", "GAME_RESULT", "GAME_RESULT", "FINISHED"])


    def test_new_connection_cannot_replace_and_rehash_an_old_event(self):
        with patch.object(official_intake, "collect_live_history", self.collect):
            self.tick()
        before = self.events()
        with closing(sqlite3.connect(self.ws / "ledger.sqlite3")) as conn:
            row = list(conn.execute("SELECT * FROM operational_events WHERE event_id=1").fetchone())
            changed = json.loads(row[4])
            changed["trust"] = "TAMPERED"
            row[4], row[5] = core.canon(changed), core.digest(changed)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT OR REPLACE INTO operational_events VALUES(?,?,?,?,?,?)", row)
        self.assertEqual(self.events(), before)

    def test_concurrent_new_issue_after_game_score_marks_roster_observation_partial(self):
        self.old_freeze(outcome=False)
        future, _ = self.snapshot_file("SSQ", future=True)
        future["target_issue"] = "30000"
        def concurrent_writer(game, *, timeout_seconds):
            if game == "DLT":
                closed_loop.advance_game_workspace(self.ws, snapshot=future, game="SSQ")
            return self.collect(game, timeout_seconds=timeout_seconds)
        with patch.object(official_intake, "collect_live_history", concurrent_writer):
            result = self.tick()
        self.assertEqual(result["local_frozen_issue_count"], 2)
        self.assertEqual(result["local_pending_issue_count"], 1)
        self.assertEqual(result.get("local_scoring_roster_observation"), "PARTIAL_CHANGED_ROSTER")
        self.assertEqual(result.get("local_unobserved_issue_count"), 1)
        self.assertEqual(result["games"]["SSQ"]["scoring"]["frozen_issues"], ["29999"])

    def test_saved_operational_bundle_passes_existing_byte_auditor(self):
        from research.harness_v46.audit_intake_bundle import audit_bundle
        def valid_collection(game, *, timeout_seconds):
            return official_intake._quarantine_worker_output(
                game, "synthetic worker failure", b"preserved stdout", b"preserved stderr",
                returncode=2, capture_complete=True)
        for fail_collection in (False, True):
            with self.subTest(fail_collection=fail_collection):
                collector = (OSError("synthetic transport failure") if fail_collection else None)
                with patch.object(official_intake, "collect_live_history",
                                  side_effect=collector if collector else valid_collection):
                    result = self.tick()
                for game in ("SSQ", "DLT"):
                    directory = Path(result["games"][game]["intake_manifest_path"]).parent
                    audit = audit_bundle(directory)
                    self.assertEqual(audit["errors"],
                                     ["NO_RAW_ARTIFACT_RECORDS_FOUND"] if fail_collection else [])
                    self.assertEqual(audit["status"], "FAIL" if fail_collection else "PASS")
                    self.assertEqual(audit["purpose"], "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY")

    def test_scoring_failure_reason_survives_in_persisted_game_event(self):
        with patch.object(official_intake, "collect_live_history", self.collect), patch.object(
                closed_loop, "advance_game_workspace", side_effect=core.GateError("SYNTHETIC_SCORE_BLOCKED")):
            self.tick()
        game_events = [json.loads(r[3]) for r in self.events() if r[1] == "GAME_RESULT"]
        self.assertEqual(len(game_events), 2)
        for event in game_events:
            self.assertIn("SYNTHETIC_SCORE_BLOCKED", event.get("scoring_reason", ""))

    def test_rehashed_invalid_journal_identity_and_order_are_rejected(self):
        tick = "V47T-" + "a" * 32
        cases = [
            [(tick, "STARTED", None, {"tick_id": "V47T-" + "b" * 32})],
            [(tick, "STARTED", None, {"tick_id": tick, "event_type": "FINISHED"})],
            [(tick, "STARTED", None, {"tick_id": tick, "lottery": "SSQ"})],
            [(tick, "STARTED", None, {"tick_id": tick, "game": "SSQ"})],
            [(tick, "STARTED", None, {"tick_id": tick}),
             (tick, "GAME_RESULT", "SSQ", {"tick_id": tick, "game": "DLT"})],
            [(tick, "STARTED", None, {"tick_id": tick}),
             (tick, "FINISHED", None, {"tick_id": tick})],
            [(tick, "STARTED", None, {"tick_id": tick}),
             (tick, "STARTED", None, {"tick_id": tick})],
            [(tick, "UNKNOWN", None, {"tick_id": tick})],
        ]
        for rows in cases:
            with self.subTest(rows=rows), closing(sqlite3.connect(":memory:")) as conn:
                conn.executescript(closed_loop.OPERATIONAL_SCHEMA)
                for tid, kind, game, payload in rows:
                    conn.execute("INSERT INTO operational_events "
                                 "(tick_id,event_type,lottery,event_payload,event_sha256) VALUES(?,?,?,?,?)",
                                 (tid, kind, game, core.canon(payload), core.digest(payload)))
                with self.assertRaisesRegex(core.GateError, "OPERATIONAL_EVENT"):
                    closed_loop._operational_check_journal(conn)

    def test_both_retained_event_formats_are_read_without_rewriting(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript(closed_loop.OPERATIONAL_SCHEMA)
            for detailed in (True, False):
                tick = "V47T-" + ("a" if detailed else "b") * 32
                for kind, game in (("STARTED", None), ("GAME_RESULT", "SSQ"),
                                   ("GAME_RESULT", "DLT"), ("FINISHED", None)):
                    if detailed:
                        payload = {"schema": "V47-LOCAL-OPERATIONAL-EVENT-1", "tick_id": tick,
                                   "event_type": kind, "lottery": game, "details": {},
                                   "observed_at_local_untrusted": "2026-10-24T17:35:31+00:00",
                                   "runner_source_sha256": "c" * 64}
                    else:
                        payload = {"tick_id": tick}
                        if game:
                            payload["game"] = game
                    conn.execute("INSERT INTO operational_events "
                                 "(tick_id,event_type,lottery,event_payload,event_sha256) VALUES(?,?,?,?,?)",
                                 (tick, kind, game, core.canon(payload), core.digest(payload)))
            before = conn.execute("SELECT * FROM operational_events").fetchall()
            self.assertEqual(closed_loop._operational_check_journal(conn), ([], 2))
            self.assertEqual(conn.execute("SELECT * FROM operational_events").fetchall(), before)


if __name__ == "__main__":
    unittest.main()
