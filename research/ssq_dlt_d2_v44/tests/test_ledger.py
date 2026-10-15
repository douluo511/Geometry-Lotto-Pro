"""Synthetic storage faults and independent per-D identity oracle."""
import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from research.ssq_dlt_d2_v44.ledger import Ledger, SLOTS
from research.ssq_dlt_d2_v44.runtime import check
from research.ssq_dlt_d2_v44.scoring import AdmissionBlocked

NOW = "2026-01-01T00:00:00Z"
DEADLINE = "2026-01-02T00:00:00Z"
LATE = "2026-01-03T00:00:00Z"
VERSIONS = {slot: "synthetic-v1" for slot in SLOTS}
# These independently selected dans intentionally are NOT a single ranking.
DANS = {"D1": [7], "D2": [1, 2], "D3": [7, 8, 9],
        "D4": [1, 2, 3, 4], "D5": [7, 8, 9, 10, 11]}


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "research.sqlite3"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def register(self, game="SSQ", issue="SYNTH-01"):
        return self.ledger.register(game, issue, VERSIONS, DEADLINE, "M05-2", now=NOW)

    def freeze(self, slot="M04", game="SSQ", issue="SYNTH-01", dans=None, now=NOW):
        return self.ledger.freeze(game, issue, slot, VERSIONS[slot], DANS if dans is None else dans, now=now)

    def complete(self, game="SSQ", issue="SYNTH-01"):
        self.register(game, issue)
        for slot in SLOTS:
            self.freeze(slot, game, issue)
        self.ledger.record_research_draw(game, issue, [1,2,3,4,5,6] if game == "SSQ" else [1,2,3,4,5],
                                         {"kind": "SYNTHETIC", "formal": False})

    def test_idempotency_across_restart_and_after_deadline(self):
        self.assertTrue(self.register())
        self.assertFalse(self.register())
        self.assertTrue(self.freeze())
        self.ledger = Ledger(self.path)
        self.assertFalse(self.freeze(now=LATE))
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM candidates").fetchone()[0], 1)

    def test_candidate_conflict_preserves_original(self):
        self.register()
        self.freeze()
        changed = dict(DANS, D2=[3,4])
        with self.assertRaisesRegex(AdmissionBlocked, "IMMUTABLE_CONFLICT"):
            self.freeze(dans=changed)
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(json.loads(db.execute("SELECT payload FROM candidates").fetchone()[0])["dans"], DANS)

    def test_foreign_database_is_refused_without_mutation(self):
        foreign=Path(self.temp.name)/"original-R1.sqlite"
        with closing(sqlite3.connect(foreign)) as db:
            db.execute("CREATE TABLE original_evidence (value TEXT)")
            db.execute("INSERT INTO original_evidence VALUES ('preserve')")
            db.commit()
        before=foreign.read_bytes()
        with self.assertRaisesRegex(AdmissionBlocked,"FOREIGN_DATABASE"):
            Ledger(foreign)
        self.assertEqual(foreign.read_bytes(),before)

    def test_update_delete_replace_all_rejected_by_database(self):
        self.complete()
        self.ledger.heartbeat("test", {"status": "SYNTHETIC"})
        for table in ("registrations", "candidates", "draws", "heartbeats"):
            for query in (f"UPDATE {table} SET sha256='tampered'", f"DELETE FROM {table}",
                          f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"):
                with self.subTest(query=query), self.ledger.connect() as db:
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(query)

    def test_duplicate_jobs_concurrent_connections(self):
        self.register()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            inserted = list(pool.map(lambda _: self.freeze(), range(16)))
        self.assertEqual(sum(inserted), 1)

    def test_transaction_failure_rolls_back_all_writes(self):
        def operation(db):
            self.ledger._insert(db, "heartbeats", {"run_id":"rolled-back"}, {"run_id":"rolled-back"})
            raise RuntimeError("simulated crash before commit")
        with self.assertRaises(RuntimeError):
            self.ledger._transaction(operation)
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM heartbeats").fetchone()[0], 0)

    def test_late_registration_candidate_and_post_draw_rejected(self):
        with self.assertRaisesRegex(AdmissionBlocked, "LATE_REGISTRATION"):
            self.ledger.register("SSQ", "LATE", VERSIONS, DEADLINE, "M05-2", now=LATE)
        self.register()
        with self.assertRaisesRegex(AdmissionBlocked, "LATE_CANDIDATE"):
            self.freeze(now=LATE)
        self.ledger.record_research_draw("SSQ", "SYNTH-01", [1,2,3,4,5,6], {"kind":"SYNTHETIC"})
        with self.assertRaisesRegex(AdmissionBlocked, "POST_DRAW_CANDIDATE"):
            self.freeze()

    def test_missing_issue_suppresses_comparison(self):
        self.complete()
        self.register(issue="SYNTH-02")
        result = self.ledger.replay()
        self.assertEqual(result["status"], "NOT_SCORABLE")
        self.assertEqual(result["expected_issues"], 2)
        self.assertEqual(result["comparisons"], [])

    def test_version_or_m05_primary_change_requires_separate_trial(self):
        self.register()
        for versions, primary in ((dict(VERSIONS, M04="v2"),"M05-2"), (VERSIONS,"M05-3")):
            with self.assertRaisesRegex(AdmissionBlocked, "SEPARATE_TRIAL_LEDGER"):
                self.ledger.register("SSQ", "SYNTH-02", versions, DEADLINE, primary, now=NOW)

    def test_non_nested_dans_and_games_scored_independently(self):
        self.complete()
        self.complete("DLT")
        result = self.ledger.replay()
        self.assertEqual(len(result["scores"]), 80)
        for game in ("SSQ", "DLT"):
            scored = [r["full"] for r in result["scores"] if r["game"] == game and r["slot"] == "M04"]
            self.assertEqual(scored, [0,1,0,1,0])
        self.assertEqual(len(result["comparisons"]), 14)
        self.assertTrue(all(r["ties"] == 1 and r["paired_delta"] == 0 for r in result["comparisons"]))
        self.assertEqual((result["formal_A"], result["R2"], result["decision"]), (0,"BLOCKED","NO_EDGE"))

    def test_replay_connection_is_read_only(self):
        self.complete()
        with self.ledger.connect(readonly=True) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO heartbeats VALUES ('{}','x','read-only')")
        first = self.path.read_bytes()
        self.ledger.replay()
        self.assertEqual(self.path.read_bytes(), first)

    def test_runtime_checks_do_not_create_predictions_or_replace_reports(self):
        self.complete()
        for _ in range(2):
            result, folder = check(self.path, Path(self.temp.name)/"status")
            self.assertTrue((folder/"status.json").exists())
            self.assertTrue((folder/"scores.csv").exists())
            self.assertTrue((folder/"status.html").exists())
            self.assertEqual(result["prediction_calls"], 0)
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM candidates").fetchone()[0], 8)
            self.assertEqual(db.execute("SELECT count(*) FROM heartbeats").fetchone()[0], 2)

    def test_unregistered_versions_missing_slots_naive_time(self):
        with self.assertRaises(AdmissionBlocked):
            self.ledger.register("SSQ", "bad", {"M04":"v1"}, DEADLINE, "M05-2", now=NOW)
        with self.assertRaises(AdmissionBlocked):
            self.ledger.register("SSQ", "bad", VERSIONS, "2026-01-02", "M05-2", now=NOW)
        self.register()
        with self.assertRaises(AdmissionBlocked):
            self.ledger.freeze("SSQ", "SYNTH-01", "M04", "future-v2", DANS, now=NOW)
        with self.assertRaises(AdmissionBlocked):
            self.freeze(dans={"D2":[1,2]})


if __name__ == "__main__":
    unittest.main()
