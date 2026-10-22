"""Scoped synthetic tests for Issue #428 convergence. No real predictive evidence."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.harness_v46 import core, convergence as cv, cli
from research.harness_v46.tests.test_core import fixture


class Contracts(unittest.TestCase):
    def snaps(self):
        return {game: fixture(game) for game in ("SSQ", "DLT")}

    def test_shared_run_id_and_model_registry(self):
        snaps = self.snaps()
        run = cv.manifest(snaps)
        self.assertEqual(run, cv.manifest(snaps))
        self.assertTrue(run["run_id"].startswith("V47-"))
        self.assertEqual(set(run["games"]), {"SSQ", "DLT"})
        self.assertEqual(set(run["models"]), set(core.MODELS))
        self.assertEqual(run["qualifications"]["formal_A"], 0)
        self.assertEqual(len(run["harness_source_sha256"]), 64)
        self.assertIn("schedule.py", cv.ORCHESTRATION_SOURCE_FILES)
        self.assertIn("cli.py", cv.ORCHESTRATION_SOURCE_FILES)
        self.assertIn("statistics.py", cv.ORCHESTRATION_SOURCE_FILES)
        source_root = Path(cv.__file__).parent
        expected_source_sha = core.digest({
            "contract": "V47-ORCHESTRATION-SOURCE-1",
            "files": {
                name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                for name in cv.ORCHESTRATION_SOURCE_FILES
            },
        })
        self.assertEqual(cv.orchestration_source_sha256(), expected_source_sha)
        self.assertEqual(run["harness_source_sha256"], expected_source_sha)
        for model, item in run["models"].items():
            self.assertEqual(item["parameters_sha256"], core.digest(core.parameter_contract(model)))
            self.assertEqual(item["model_source_sha256"], core.model_source_sha256())
        changed = self.snaps()
        changed["SSQ"]["provenance"]["revision"] = "changed"
        self.assertNotEqual(run["run_id"], cv.manifest(changed)["run_id"])
        original_window = core.PARAMETERS["hot60"]["window"]
        try:
            core.PARAMETERS["hot60"]["window"] = original_window + 1
            changed_registry = cv.manifest(self.snaps())
            self.assertNotEqual(run["run_id"], changed_registry["run_id"])
        finally:
            core.PARAMETERS["hot60"]["window"] = original_window

    def test_manifest_is_persisted_idempotently_and_immutable(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        run_manifest = cv.manifest(self.snaps())
        with db:
            first = cv.register_manifest(db, run_manifest)
            self.assertEqual(first, cv.register_manifest(db, run_manifest))
        stored = db.execute(
            "SELECT manifest_sha256,payload,evidence_class FROM run_manifests WHERE run_id=?",
            (run_manifest["run_id"],),
        ).fetchone()
        self.assertEqual(stored[0], hashlib.sha256(stored[1].encode("utf-8")).hexdigest())
        self.assertEqual(json.loads(stored[1]), run_manifest)
        self.assertEqual(stored[2], "SHADOW")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("INSERT OR REPLACE INTO run_manifests SELECT * FROM run_manifests")
        db.close()

    def test_snapshot_preimage_is_persisted_and_immutable(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        snapshots = self.snaps()
        run_manifest = cv.manifest(snapshots)
        with db:
            cv.register_manifest(db, run_manifest)
            for game in ("SSQ", "DLT"):
                core.register_snapshot(db, run_manifest["run_id"], snapshots[game])
        for game in ("SSQ", "DLT"):
            loaded = core.load_registered_snapshot(db, run_manifest["run_id"], game)
            self.assertEqual(loaded, snapshots[game])
            row = db.execute(
                "SELECT snapshot_sha256,payload,evidence_class FROM run_snapshots "
                "WHERE run_id=? AND lottery=?", (run_manifest["run_id"], game),
            ).fetchone()
            self.assertEqual(row[0], hashlib.sha256(row[1].encode("utf-8")).hexdigest())
            self.assertEqual(row[2], "SHADOW")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM run_snapshots").fetchone()[0], 2)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("INSERT OR REPLACE INTO run_snapshots SELECT * FROM run_snapshots")
        db.close()

    def test_v47_freeze_requires_registered_manifest(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        snap = fixture("SSQ")
        prediction = core.forecast(snap, "hot60")
        with self.assertRaisesRegex(core.GateError, "V47_RUN_MANIFEST_NOT_REGISTERED"):
            core.freeze_shadow(db, "V47-MISSING-MANIFEST", snap, prediction,
                               "2026-10-21T00:00:00+00:00")
        db.close()

    def test_handoff_no_cross_model_and_no_forged_model_role(self):
        run_id = cv.manifest(self.snaps())["run_id"]
        self.assertEqual(len(cv.ROLES), 10)
        self.assertTrue(cv.require_tool("test9", "score_readonly"))
        with self.assertRaisesRegex(core.GateError, "ROLE_TOOL_DENIED"):
            cv.require_tool("test3", "read_frozen")
        with self.assertRaisesRegex(core.GateError, "PRODUCER_TO_PRODUCER"):
            cv.handoff(run_id, "SSQ", "test3", "test4", "FROZEN_FORECAST", {"model": "hot60"})
        with self.assertRaisesRegex(core.GateError, "MODEL_ROLE_IDENTITY"):
            cv.handoff(run_id, "SSQ", "test3", "test9", "FROZEN_FORECAST", {"model": "ewma"})
        receipt = cv.handoff(run_id, "DLT", "test3", "test9", "FROZEN_FORECAST", {"model": "hot60"})
        self.assertEqual(receipt["claim"], "UNVERIFIED_EXTERNAL_HANDOFF_SHADOW_ONLY")

    def test_local_raw_sha_and_source_conflict(self):
        snap = fixture()
        with tempfile.TemporaryDirectory() as td:
            p1, p2 = Path(td) / "raw_1", Path(td) / "raw_2"
            p1.write_bytes(b"fixture-one")
            p2.write_bytes(b"fixture-two")
            specs = [
                {"url": "https://example.org/source1", "path": str(p1),
                 "sha256": hashlib.sha256(b"fixture-one").hexdigest(),
                 "published_at": "2026-10-19T00:00:00+00:00",
                 "fetched_at": "2026-10-19T01:00:00+00:00"},
                {"url": "https://example.org/source2", "path": str(p2),
                 "sha256": hashlib.sha256(b"fixture-two").hexdigest(),
                 "published_at": "2026-10-19T00:00:00+00:00",
                 "fetched_at": "2026-10-19T01:00:00+00:00"},
            ]
            got = cv.verify_local_source_bytes(snap, specs)
            self.assertEqual(got["local_byte_integrity"], "PASS")
            self.assertEqual(got["source_authenticity"], "NOT_VERIFIED")
            self.assertEqual(got["official_target_admission"], "BLOCKED")
            p1.write_bytes(b"changed")
            with self.assertRaisesRegex(core.GateError, "RAW_SHA256_MISMATCH"):
                cv.verify_local_source_bytes(snap, specs)
            p1.write_bytes(b"fixture-one")
            bad = [dict(s) for s in specs]
            bad[1]["url"] = bad[0]["url"]
            with self.assertRaisesRegex(core.GateError, "TWO_DISTINCT_HTTPS"):
                cv.verify_local_source_bytes(snap, bad)
            bad = [dict(s) for s in specs]
            bad[0]["published_at"] = "2026-10-25T00:00:00+00:00"
            with self.assertRaisesRegex(core.GateError, "SOURCE_AFTER_ASOF"):
                cv.verify_local_source_bytes(snap, bad)

    def test_raw_source_bytes_are_allowlisted_persisted_and_immutable(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        snapshot = fixture("SSQ")
        raw_a = b"<html>official-source-a synthetic test</html>"
        raw_b = b"<html>official-source-b synthetic test</html>"
        published = "2026-10-19T00:00:00+00:00"
        fetched = "2026-10-19T01:00:00+00:00"
        sources = [
            {"url": "https://www.swlc.net.cn/lottery/ssq.html?limit=100",
             "raw_sha256": hashlib.sha256(raw_a).hexdigest(),
             "published_at": published, "fetched_at": fetched,
             "content_type": "text/html"},
            {"url": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
             "raw_sha256": hashlib.sha256(raw_b).hexdigest(),
             "published_at": published, "fetched_at": fetched,
             "content_type": "text/html"},
        ]
        snapshot["provenance"]["sources"] = sources
        snapshots = self.snaps()
        snapshots["SSQ"] = snapshot
        run_manifest = cv.manifest(snapshots)
        run = run_manifest["run_id"]
        with db:
            cv.register_manifest(db, run_manifest)
            core.register_snapshot(db, run, snapshot)
            first = core.register_source_artifact(
                db, run, "SSQ", sources[0]["url"], raw_a,
                published_at=published, fetched_at=fetched, content_type="text/html")
            again = core.register_source_artifact(
                db, run, "SSQ", sources[0]["url"], raw_a,
                published_at=published, fetched_at=fetched, content_type="text/html")
            second = core.register_source_artifact(
                db, run, "SSQ", sources[1]["url"], raw_b,
                published_at=published, fetched_at=fetched, content_type="text/html")
        self.assertEqual(first, again)
        self.assertEqual(first["source_authenticity"], "NOT_VERIFIED")
        self.assertNotEqual(first["artifact_id"], second["artifact_id"])
        stored = db.execute(
            "SELECT raw_sha256,raw_bytes,source_authenticity FROM source_artifacts "
            "WHERE artifact_id=?", (first["artifact_id"],)).fetchone()
        self.assertEqual(stored[0], hashlib.sha256(raw_a).hexdigest())
        self.assertEqual(bytes(stored[1]), raw_a)
        self.assertEqual(stored[2], "NOT_VERIFIED")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("INSERT OR REPLACE INTO source_artifacts SELECT * FROM source_artifacts")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM source_artifacts")
        db.close()

    def test_raw_source_artifact_rejects_unapproved_host_and_unbound_bytes(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        snapshot = fixture("SSQ")
        raw = b"fixture raw bytes"
        published = "2026-10-19T00:00:00+00:00"
        fetched = "2026-10-19T01:00:00+00:00"
        url = "https://example.org/ssq.html"
        snapshot["provenance"]["sources"] = [{
            "url": url, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "published_at": published, "fetched_at": fetched, "content_type": "text/html"}]
        snapshots = self.snaps()
        snapshots["SSQ"] = snapshot
        manifest = cv.manifest(snapshots)
        with db:
            cv.register_manifest(db, manifest)
            core.register_snapshot(db, manifest["run_id"], snapshot)
            with self.assertRaisesRegex(core.GateError, "HOST_NOT_ALLOWLISTED"):
                core.register_source_artifact(
                    db, manifest["run_id"], "SSQ", url, raw,
                    published_at=published, fetched_at=fetched, content_type="text/html")
            with self.assertRaisesRegex(core.GateError, "NOT_BOUND_TO_SNAPSHOT"):
                core.register_source_artifact(
                    db, manifest["run_id"], "SSQ",
                    "https://www.swlc.net.cn/lottery/ssq.html", b"changed",
                    published_at=published, fetched_at=fetched, content_type="text/html")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM source_artifacts").fetchone()[0], 0)
        db.close()

    def test_raw_source_artifact_rejects_time_after_asof(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        snapshot = fixture("DLT")
        raw = b"synthetic source bytes"
        published = "2026-10-19T00:00:00+00:00"
        fetched = "2026-10-21T00:00:00+00:00"
        url = "https://www.gstc.org.cn/wanfa/dlt_history"
        snapshot["provenance"]["sources"] = [{
            "url": url, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "published_at": published, "fetched_at": fetched, "content_type": "text/html"}]
        snapshots = self.snaps()
        snapshots["DLT"] = snapshot
        manifest = cv.manifest(snapshots)
        with db:
            cv.register_manifest(db, manifest)
            core.register_snapshot(db, manifest["run_id"], snapshot)
            with self.assertRaisesRegex(core.GateError, "ARTIFACT_AFTER_ASOF"):
                core.register_source_artifact(
                    db, manifest["run_id"], "DLT", url, raw,
                    published_at=published, fetched_at=fetched, content_type="text/html")
        db.close()

    def prepare_batch(self, conn, lottery="SSQ"):
        snap = fixture(lottery)
        run_manifest = cv.manifest(self.snaps())
        run_id = run_manifest["run_id"]
        core.init_ledger(conn)
        cv.init_workflow(conn)
        frozen_at = "2026-10-21T00:00:00+00:00"
        with conn:
            cv.register_manifest(conn, run_manifest)
            core.register_snapshot(conn, run_id, snap)
            for name in core.MODELS:
                p = core.forecast(snap, name)
                core.freeze_shadow(conn, run_id, snap, p, frozen_at)
        return run_id, snap

    def test_immutable_model_replay_and_exact_freeze_retry(self):
        db = sqlite3.connect(":memory:")
        run, snap = self.prepare_batch(db)
        sample = core.forecast(snap, "hot60")
        frozen_at = "2026-10-21T00:00:00+00:00"
        with db:
            first = core.freeze_shadow(db, run, snap, sample, frozen_at)
            self.assertEqual(first, core.digest(sample))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 6)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 6)
        malicious = core.forecast(snap, "hot60")
        malicious["candidates_1_to_5"][2:4] = malicious["candidates_1_to_5"][2:4][::-1]
        with self.assertRaisesRegex(core.GateError, "ranking"):
            core.freeze_shadow(db, run, snap, malicious, frozen_at)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 6)
        # Simulate a privileged file-level rewrite that updates both payload and hash.
        # The independent audit must still reject a legal-looking substituted model output.
        db.execute("DROP TRIGGER prevent_prediction_update")
        row = db.execute(
            "SELECT payload FROM predictions WHERE run_id=? AND lottery='SSQ' AND model='hot60'",
            (run,),
        ).fetchone()
        altered = json.loads(row[0])
        altered["candidates_1_to_5"][2:4] = altered["candidates_1_to_5"][2:4][::-1]
        altered_payload = core.canon(altered)
        altered_sha = hashlib.sha256(altered_payload.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE predictions SET payload=?,prediction_sha256=? "
            "WHERE run_id=? AND lottery='SSQ' AND model='hot60'",
            (altered_payload, altered_sha, run),
        )
        with self.assertRaisesRegex(core.GateError, "ranking"):
            cv.check_complete_batch(db, run, "SSQ")
        db.close()

    def test_run_snapshot_switch_rejected(self):
        db = sqlite3.connect(":memory:")
        run, snap = self.prepare_batch(db)
        changed = fixture("SSQ")
        changed["provenance"]["revision"] = 3
        with self.assertRaisesRegex(core.GateError, "V47_FREEZE_SNAPSHOT_DIFFERS"):
            core.freeze_shadow(db, run, changed, core.forecast(changed, "hot60"),
                               "2026-10-21T00:00:00+00:00")
        db.close()

    def test_six_slot_gate_and_ordering(self):
        db = sqlite3.connect(":memory:")
        run, snap = self.prepare_batch(db)
        batch = cv.check_complete_batch(db, run, "SSQ")
        with self.assertRaisesRegex(core.GateError, "STAGE_ORDER_VIOLATION"):
            cv.append_stage(db, run, "SSQ", "FREEZE", {"batch_sha256": batch})
        with db:
            for stage in cv.STAGES:
                details = {"formal_A": 0, "status": "SHADOW"}
                if stage == "FREEZE":
                    details["batch_sha256"] = batch
                sha = cv.append_stage(db, run, "SSQ", stage, details)
                self.assertEqual(sha, cv.append_stage(db, run, "SSQ", stage, details))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM workflow_events").fetchone()[0], len(cv.STAGES))
        with self.assertRaisesRegex(core.GateError, "CONFLICTING_WORKFLOW_RETRY"):
            cv.append_stage(db, run, "SSQ", "VERIFY", {"status": "altered"})
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM workflow_events")
        db.close()

    def test_forged_authorization_rejected(self):
        db = sqlite3.connect(":memory:")
        run, _ = self.prepare_batch(db)
        cv.append_stage(db, run, "SSQ", "SYNC", {})
        with self.assertRaisesRegex(core.GateError, "FORMAL_A_FORBIDDEN"):
            cv.append_stage(db, run, "SSQ", "VERIFY", {"formal_A": 1})
        with self.assertRaisesRegex(core.GateError, "UNSUPPORTED_AUTHORITY"):
            cv.append_stage(db, run, "SSQ", "VERIFY", {"status": "TSA_VERIFIED"})
        db.close()

    def test_tsa_interface_does_not_fabricate_proof(self):
        db = sqlite3.connect(":memory:")
        run, _ = self.prepare_batch(db)
        with db:
            first = cv.tsa_request(db, run, "SSQ")
            self.assertEqual(first, cv.tsa_request(db, run, "SSQ"))
        self.assertEqual(first["external_tsa"], "NOT_VERIFIED")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM tsa_claims").fetchone()[0], 1)
        self.assertEqual(db.execute("PRAGMA recursive_triggers").fetchone()[0], 1)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("INSERT OR REPLACE INTO tsa_claims SELECT * FROM tsa_claims")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE tsa_claims SET verification='VERIFIED'")
        db.close()

    def test_missing_model_blocks_freeze(self):
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        cv.init_workflow(db)
        snap = fixture("SSQ")
        run_manifest = cv.manifest(self.snaps())
        run = run_manifest["run_id"]
        with db:
            cv.register_manifest(db, run_manifest)
            core.register_snapshot(db, run, snap)
            for name in core.MODELS[:-1]:
                core.freeze_shadow(db, run, snap, core.forecast(snap, name),
                                   "2026-10-21T00:00:00+00:00")
        with self.assertRaisesRegex(core.GateError, "INCOMPLETE_SIX_MODEL_BATCH"):
            cv.check_complete_batch(db, run, "SSQ")
        db.close()

    def test_actual_cutoff_and_future_history_guard(self):
        snap = fixture()
        predicted = core.forecast(snap, "hot60")
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        with self.assertRaisesRegex(core.GateError, "before sales cutoff"):
            core.freeze_shadow(db, "V46-TOO-LATE", snap, predicted,
                               "2026-10-25T00:00:00+00:00")
        snap["draws"][-1]["published_at"] = "2026-10-25T00:00:00+00:00"
        with self.assertRaisesRegex(core.GateError, "future data"):
            core.forecast(snap, "hot60")
        db.close()

    def test_readonly_paired_d2_not_claiming_official(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite"
            db = sqlite3.connect(path)
            run, snap = self.prepare_batch(db, lottery="DLT")
            db.commit()
            db.close()
            result = {"lottery": "DLT", "issue": snap["target_issue"],
                      "front": [1,2,3,4,5], "back": [1,2]}
            stats = cv.score_readonly(path, run, result)
            self.assertEqual(set(stats["scores"]), set(core.MODELS))
            self.assertEqual(stats["outcome_source"], "CALLER_UNVERIFIED")
            self.assertEqual(stats["formal_A"], 0)
            self.assertEqual(set(stats["same_draw_d2_delta_vs_null"]), set(core.MODELS) - {"random_null"})
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 6)
            db.close()

    def test_manifest_blocks_less_than_120_draws(self):
        snapshots = self.snaps()
        snapshots["DLT"] = fixture("DLT", size=119)
        with self.assertRaisesRegex(core.GateError, "study requires at least 120"):
            cv.manifest(snapshots)

    def test_cli_rejects_caller_supplied_v47_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            snapshot_path = Path(td) / "snapshot.json"
            db_path = Path(td) / "must_not_exist.sqlite3"
            snapshot_path.write_text(json.dumps(fixture()), encoding="utf-8")
            args = type("Args", (), {"snapshot": str(snapshot_path),
                                     "database": str(db_path), "run_id": "V47-MANUAL-ID",
                                     "model": "all"})()
            with self.assertRaisesRegex(
                core.GateError, "V47_RUN_ID_REQUIRES_DUAL_GAME_MANIFEST"
            ):
                cli.run_forecast(args)
            self.assertFalse(db_path.exists())

    def test_cli_blocks_before_creating_ledger_without_120_draws(self):
        with tempfile.TemporaryDirectory() as td:
            snapshot_path = Path(td) / "under120.json"
            db_path = Path(td) / "must_not_exist.sqlite3"
            snapshot_path.write_text(json.dumps(fixture(size=119)), encoding="utf-8")
            args = type("Args", (), {"snapshot": str(snapshot_path),
                                     "database": str(db_path), "run_id": "V47-UNDER120",
                                     "model": "all"})()
            with self.assertRaisesRegex(core.GateError, "study requires at least 120"):
                cli.run_forecast(args)
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
