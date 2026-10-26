"""TEST_ONLY_SYNTHETIC singleton seal regression; never formal evidence."""
import hashlib
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

from research.harness_v46 import closed_loop, core, predraw_seal
from research.harness_v46.tests import test_predraw_seal as dual_tests
from research.harness_v46.tests.test_core import fixture


class IndependentGameSealTests(unittest.TestCase):
    setUpClass = classmethod(dual_tests.PredrawSealTests.setUpClass.__func__)
    tearDownClass = classmethod(dual_tests.PredrawSealTests.tearDownClass.__func__)
    _cmd = classmethod(dual_tests.PredrawSealTests._cmd.__func__)

    def test_each_singleton_exports_only_six_original_cards_and_makes_real_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            for game in ("SSQ", "DLT"):
                with self.subTest(game=game):
                    snapshot = fixture(game)
                    snapshot.update(as_of=(now-timedelta(hours=1)).isoformat(),
                                    sales_cutoff=(now+timedelta(days=1)).isoformat(),
                                    target_draw_at=(now+timedelta(days=2)).isoformat())
                    workspace = home / game
                    frozen = closed_loop.advance_game_workspace(
                        workspace, snapshot=snapshot, observed_at=now-timedelta(seconds=10))
                    db, run = workspace / "ledger.sqlite3", frozen["run_ids"][0]
                    before = db.read_bytes()
                    with closing(sqlite3.connect(db)) as conn:
                        rows = conn.execute("SELECT model,payload,prediction_sha256 "
                                            "FROM game_predictions ORDER BY model").fetchall()
                        self.assertEqual({r[0] for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'")},
                            {"game_runs", "game_predictions"})
                    try:
                        payload = predraw_seal.frozen_seal_payload(db, run, self.pin)
                    except core.GateError as exc:
                        self.fail("valid original six-card freeze must seal: " + str(exc))
                    self.assertEqual(payload["schema"], "V47G-FROZEN-SEAL-PAYLOAD-1")
                    self.assertNotIn("manifest", payload)
                    self.assertEqual(payload["registration"]["evidence_class"], "DERIVED")
                    self.assertEqual(payload["registration"]["lottery"], game)
                    self.assertEqual(payload["snapshots"], {game: snapshot})
                    self.assertEqual(set(payload["games"]), {game})
                    self.assertEqual([p["payload"] for p in payload["games"][game]["predictions"]],
                                     [json.loads(raw) for _, raw, _ in rows])
                    self.assertEqual([p["prediction_sha256"] for p in payload["games"][game]["predictions"]],
                                     [sha for _, _, sha in rows])
                    self.assertEqual(payload["formal_A"], 0)
                    self.assertEqual(payload["decision"], "NO_EDGE")
                    destination = home / ("seal_" + game)
                    request = predraw_seal.prepare_request(
                        db, run, destination, trust_root_sha256=self.pin,
                        openssl=self.openssl, now=now)
                    self.assertEqual(request["payload_sha256"],
                                     hashlib.sha256((destination/"payload.json").read_bytes()).hexdigest())
                    self.assertEqual(request["external_tsa"], "REQUEST_ONLY_NOT_VERIFIED")
                    response = destination.with_suffix(".tsr")
                    self._cmd("ts", "-reply", "-config", "tsa.cnf", "-queryfile",
                              str(destination/"request.tsq"), "-out", str(response))
                    receipt = predraw_seal.verify_response(
                        db, run, destination, response, self.root/"ca.pem",
                        trust_root_sha256=self.pin, openssl=self.openssl)
                    self.assertEqual(receipt["predraw_time_bound"], "BEFORE_CLAIMED_GAME_CUTOFF")
                    self.assertEqual(receipt["cryptographic_verification"], "PASS_UNDER_CALLER_PIN")
                    self.assertEqual(receipt["official_target_admission"], "BLOCKED")
                    self.assertEqual(receipt["formal_A"], 0)
                    self.assertEqual(receipt["decision"], "NO_EDGE")
                    self.assertEqual(db.read_bytes(), before)


    def freeze_fixture(self, game="SSQ"):
        self.sequence = getattr(self, "sequence", 0) + 1
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = fixture(game)
        snapshot.update(as_of=(now-timedelta(hours=1)).isoformat(),
                        sales_cutoff=(now+timedelta(days=1)).isoformat(),
                        target_draw_at=(now+timedelta(days=2)).isoformat())
        report = closed_loop.advance_game_workspace(
            home/"workspace", snapshot=snapshot, observed_at=now-timedelta(seconds=10))
        return home/"workspace"/"ledger.sqlite3", report["run_ids"][0], snapshot, now

    def mutate(self, database, operation):
        # Only TEMP synthetic fixtures are modified; production readers stay read-only.
        with closing(sqlite3.connect(database)) as conn:
            for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            operation(conn)
            conn.commit()

    def assert_rejected_unchanged(self, database, run, expected):
        before = {p: p.read_bytes() for p in database.parent.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(core.GateError, expected):
            predraw_seal.frozen_seal_payload(database, run, self.pin)
        self.assertEqual({p: p.read_bytes() for p in database.parent.rglob("*") if p.is_file()},
                         before)

    def test_exact_identity_missing_ambiguous_and_wrong_game_reject(self):
        database, run, snapshot, now = self.freeze_fixture()
        for invalid in (None, 47, "", "V47G-", run.upper(), run+"x", run+"\n",
                        "x"+run, run[:-1]):
            with self.subTest(invalid=invalid):
                self.assert_rejected_unchanged(database, invalid, "REQUIRED")
        self.assert_rejected_unchanged(database, "V47G-"+"0"*32, "GAME_RUN_NOT_REGISTERED")
        for game, expected in (("UNKNOWN", "GAME_RUN_INVALID_LOTTERY"),
                               ("DLT", "GAME_SNAPSHOT_REPLAY_MISMATCH")):
            database, run, _, _ = self.freeze_fixture()
            self.mutate(database, lambda c: c.execute("UPDATE game_runs SET lottery=?", (game,)))
            self.assert_rejected_unchanged(database, run, expected)
        database, run, _, _ = self.freeze_fixture()
        def duplicate(conn):
            conn.execute("CREATE TABLE copied_runs AS SELECT * FROM game_runs")
            conn.execute("DROP TABLE game_runs")
            conn.execute("ALTER TABLE copied_runs RENAME TO game_runs")
            conn.execute("INSERT INTO game_runs SELECT * FROM game_runs")
        self.mutate(database, duplicate)
        self.assert_rejected_unchanged(database, run, "GAME_RUN_ID_AMBIGUOUS")

    def test_unrelated_other_game_cannot_block_or_enter_singleton_payload(self):
        for game, other in (("SSQ", "DLT"), ("DLT", "SSQ")):
            with self.subTest(game=game):
                database, run, _, _ = self.freeze_fixture(game)
                original = predraw_seal.frozen_seal_payload(database, run, self.pin)
                self.mutate(database, lambda c: c.execute(
                    "INSERT INTO game_runs VALUES(?,?,?,?,?,?)",
                    (other, "99999", "V47G-"+"f"*32, "0"*64, "{}", "invalid")))
                before = database.read_bytes()
                self.assertEqual(predraw_seal.frozen_seal_payload(database, run, self.pin), original)
                self.assertEqual(database.read_bytes(), before)

    def test_card_roster_and_rehashed_seed_parameter_target_source_substitution_reject(self):
        cases = (
            ("missing", "GAME_INCOMPLETE_SIX_ARM_FREEZE"),
            ("extra", "GAME_INCOMPLETE_SIX_ARM_FREEZE"),
            ("noncanonical", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("null_seed", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("seed", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("parameters", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("target", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("ticket", "GAME_FROZEN_PREDICTION_REPLAY_MISMATCH"),
            ("mixed_source", "REPLAY_MIXED_MODEL_SOURCES"),
            ("unknown_source", "REPLAY_SOURCE_NOT_REGISTERED"))
        for attack, expected in cases:
            with self.subTest(attack=attack):
                database, run, _, _ = self.freeze_fixture()
                def corrupt(conn):
                    if attack == "missing":
                        conn.execute("DELETE FROM game_predictions WHERE model='hot60'")
                        return
                    if attack == "extra":
                        conn.execute("INSERT INTO game_predictions SELECT run_id,'extra',payload,"
                                     "prediction_sha256 FROM game_predictions WHERE model='hot60'")
                        return
                    models = core.MODELS if attack == "unknown_source" else (
                        "random_null" if attack in ("seed", "null_seed") else "hot60",)
                    for model in models:
                        card = json.loads(conn.execute(
                            "SELECT payload FROM game_predictions WHERE model=?", (model,)).fetchone()[0])
                        if attack == "null_seed": card["null_seed_id"] = None
                        if attack == "seed": card["null_seed_id"] = "TEST_ONLY_CHANGED_SEED"
                        if attack == "parameters": card["parameters_sha256"] = "0"*64
                        if attack == "target": card["target_issue"] = "30000"
                        if attack == "ticket": card["ticket"]["unregistered"] = True
                        if attack in ("mixed_source", "unknown_source"):
                            card["model_source_sha256"] = "0"*64
                        raw = json.dumps(card) if attack == "noncanonical" else core.canon(card)
                        conn.execute("UPDATE game_predictions SET payload=?,prediction_sha256=? WHERE model=?",
                                     (raw, core.digest(card), model))
                self.mutate(database, corrupt)
                self.assert_rejected_unchanged(database, run, expected)

    def test_snapshot_hash_canonical_target_run_identity_and_freeze_time_reject(self):
        for attack, expected in (
                ("hash", "GAME_SNAPSHOT_SHA_MISMATCH"),
                ("noncanonical", "GAME_SNAPSHOT_REPLAY_MISMATCH"),
                ("target", "GAME_SNAPSHOT_REPLAY_MISMATCH|GAME_RUN_IDENTITY_MISMATCH"),
                ("run", "GAME_RUN_IDENTITY_MISMATCH"),
                ("before_asof", "GAME_FROZEN_LOCAL_TIME_INVALID"),
                ("at_cutoff", "GAME_FROZEN_LOCAL_TIME_INVALID"),
                ("naive", "timezone|aware")):
            with self.subTest(attack=attack):
                database, run, snapshot, now = self.freeze_fixture("DLT")
                selected_run = "V47G-"+"e"*32 if attack == "run" else run
                def corrupt(conn):
                    if attack == "hash":
                        conn.execute("UPDATE game_runs SET snapshot_sha256=?", ("0"*64,))
                    elif attack in ("noncanonical", "target"):
                        changed = json.loads(json.dumps(snapshot))
                        if attack == "target": changed["target_issue"] = "30000"
                        raw = json.dumps(changed) if attack == "noncanonical" else core.canon(changed)
                        conn.execute("UPDATE game_runs SET snapshot_payload=?,snapshot_sha256=?",
                                     (raw, core.digest(changed)))
                    elif attack == "run":
                        conn.execute("UPDATE game_runs SET run_id=?", (selected_run,))
                        conn.execute("UPDATE game_predictions SET run_id=?", (selected_run,))
                    else:
                        stamp = {"before_asof": core.dt(snapshot["as_of"])-timedelta(microseconds=1),
                                 "at_cutoff": core.dt(snapshot["sales_cutoff"]),
                                 "naive": now.replace(tzinfo=None)}[attack]
                        conn.execute("UPDATE game_runs SET frozen_at_local_untrusted=?", (stamp.isoformat(),))
                self.mutate(database, corrupt)
                self.assert_rejected_unchanged(database, selected_run, expected)

    def test_request_clock_boundaries_reject_before_output_and_freeze_equality_passes(self):
        database, run, snapshot, now = self.freeze_fixture()
        frozen_at = now-timedelta(seconds=10)
        before = database.read_bytes()
        for clock, expected in (
                (core.dt(snapshot["as_of"])-timedelta(microseconds=1), "BEFORE_ASOF"),
                (frozen_at-timedelta(microseconds=1), "BEFORE_LOCAL_FREEZE"),
                (core.dt(snapshot["sales_cutoff"]), "AFTER_CUTOFF"),
                (now.replace(tzinfo=None), "AWARE_CLOCK")):
            with self.subTest(clock=clock):
                destination = database.parent.parent / "bad_clock"
                with self.assertRaisesRegex(core.GateError, expected):
                    predraw_seal.prepare_request(
                        database, run, destination, trust_root_sha256=self.pin,
                        openssl=self.openssl, now=clock)
                self.assertFalse(destination.exists())
                self.assertEqual(database.read_bytes(), before)
        predraw_seal.prepare_request(
            database, run, database.parent.parent/"at_freeze", trust_root_sha256=self.pin,
            openssl=self.openssl, now=frozen_at)
        self.assertEqual(database.read_bytes(), before)

    def test_v47g_clean_wal_live_wal_and_existing_sidecars_reject_before_sqlite_open(self):
        for mode in ("clean_wal", "live_wal", "wal_sidecar", "shm_sidecar"):
            with self.subTest(mode=mode):
                database, run, _, _ = self.freeze_fixture()
                writer = None
                if mode in ("clean_wal", "live_wal"):
                    writer = sqlite3.connect(database)
                    self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                    if mode == "clean_wal":
                        writer.close()
                        writer = None
                    else:
                        writer.execute("CREATE TABLE pending_test_data(value)")
                        writer.commit()
                else:
                    Path(str(database)+("-wal" if mode == "wal_sidecar" else "-shm")).write_bytes(
                        b"TEST_ONLY_EXISTING_SIDECAR")
                try:
                    self.assert_rejected_unchanged(database, run, "V47G_READ_ONLY_WAL_UNSUPPORTED")
                finally:
                    if writer is not None:
                        writer.close()

    def test_singleton_cli_request_and_verify_keep_formal_admission_blocked(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                database, run, _, _ = self.freeze_fixture(game)
                before = database.read_bytes()
                destination = database.parent.parent / "cli_seal"
                common = ["--database", str(database), "--run-id", run,
                          "--seal-dir", str(destination), "--trust-root-sha256",
                          self.pin, "--openssl", self.openssl]
                command = [sys.executable, "-B", "-m",
                           "research.harness_v46.predraw_seal"]
                requested = subprocess.run(command + ["request"] + common,
                                           capture_output=True, timeout=30)
                self.assertEqual(requested.returncode, 0,
                                 requested.stderr.decode("ascii", "backslashreplace"))
                self.assertEqual(json.loads(requested.stdout.decode("utf-8"))["formal_A"], 0)
                response = destination.with_suffix(".tsr")
                self._cmd("ts", "-reply", "-config", "tsa.cnf", "-queryfile",
                          str(destination / "request.tsq"), "-out", str(response))
                verified = subprocess.run(
                    command + ["verify"] + common +
                    ["--response", str(response), "--ca-file", str(self.root / "ca.pem")],
                    capture_output=True, timeout=30)
                self.assertEqual(verified.returncode, 0,
                                 verified.stderr.decode("ascii", "backslashreplace"))
                receipt = json.loads(verified.stdout.decode("utf-8"))
                self.assertEqual(receipt["predraw_time_bound"], "BEFORE_CLAIMED_GAME_CUTOFF")
                self.assertEqual(receipt["external_tsa_formal_admission"], "BLOCKED")
                self.assertEqual(receipt["formal_A"], 0)
                self.assertEqual(receipt["decision"], "NO_EDGE")
                self.assertEqual(database.read_bytes(), before)

    def test_singleton_replays_original_source_after_copied_install_upgrade_and_rejects_tamper(self):
        worker = """
import json, sys
from datetime import datetime
from research.harness_v46 import closed_loop, predraw_seal
mode, workspace, snapshot_file, pin, argument = sys.argv[1:]
if mode == "freeze":
    snapshot = json.load(open(snapshot_file, encoding="utf-8"))
    report = closed_loop.advance_game_workspace(
        workspace, snapshot=snapshot, observed_at=datetime.fromisoformat(argument))
    run = report["run_ids"][0]
else:
    run = argument
value = predraw_seal.frozen_seal_payload(
    workspace + "/ledger.sqlite3", run, pin)
print(json.dumps({"run_id":run, "payload":value}, ensure_ascii=True))
"""
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                repository = home / "installed"
                package = repository / "research" / "harness_v46"
                package.parent.mkdir(parents=True)
                (package.parent / "__init__.py").write_text("", encoding="utf-8")
                shutil.copytree(Path(core.__file__).parent, package,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
                now = datetime.now(timezone.utc).replace(microsecond=0)
                snapshot = fixture(game)
                snapshot.update(as_of=(now-timedelta(hours=1)).isoformat(),
                                sales_cutoff=(now+timedelta(days=1)).isoformat(),
                                target_draw_at=(now+timedelta(days=2)).isoformat())
                source = home / "snapshot.json"
                source.write_text(json.dumps(snapshot), encoding="utf-8")
                workspace = home / "workspace"
                env = dict(os.environ, PYTHONPATH=str(repository),
                           PYTHONDONTWRITEBYTECODE="1")
                def run_child(mode, argument):
                    return subprocess.run(
                        [sys.executable, "-B", "-c", worker, mode, str(workspace),
                         str(source), self.pin, argument], cwd=repository, env=env,
                        capture_output=True, timeout=30)
                original = run_child("freeze", (now-timedelta(seconds=10)).isoformat())
                self.assertEqual(original.returncode, 0,
                                 original.stderr.decode("ascii", "backslashreplace"))
                original_value = json.loads(original.stdout.decode("utf-8"))
                database = workspace / "ledger.sqlite3"
                before = database.read_bytes()
                live = package / "core.py"
                live.write_bytes(live.read_bytes() +
                    b'\ndef forecast(*args, **kwargs):\n    raise AssertionError("UPGRADED_MODEL_MUST_NOT_REPLACE_FROZEN_CARD")\n')
                replayed = run_child("seal", original_value["run_id"])
                self.assertEqual(replayed.returncode, 0,
                                 replayed.stderr.decode("ascii", "backslashreplace"))
                self.assertEqual(json.loads(replayed.stdout.decode("utf-8")), original_value)
                self.assertEqual(database.read_bytes(), before)
                archive = package / "model_versions" / "core_lf.source"
                self.assertTrue(archive.resolve().is_relative_to(home.resolve()))
                archive.write_bytes(archive.read_bytes() + b"\n# TEST_ONLY_TAMPER\n")
                rejected = run_child("seal", original_value["run_id"])
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(b"REPLAY_SOURCE_ARTIFACT_HASH_MISMATCH", rejected.stderr)
                self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
