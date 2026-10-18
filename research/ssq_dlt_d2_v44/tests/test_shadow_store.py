"""Storage fault injection against an independently reconstructed two-row oracle."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_v44.shadow_snapshot import verify_snapshot_archive
from research.ssq_dlt_d2_v44.shadow_store import ShadowStore, ShadowStoreError, APPLICATION_ID, SCHEMA_VERSION
from research.ssq_dlt_d2_v44 import shadow_store as storage
from research.ssq_dlt_d2_v44.tests.test_shadow_snapshot import SyntheticSnapshot, encoded, digest


class TestShadowStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = SyntheticSnapshot()
        self.verified = self.fixture.verify(self.root)
        self.path = self.root/"shadow.sqlite3"

    def store(self):
        return ShadowStore(self.path)

    def test_exact_restart_retry_and_read_scope(self):
        store = self.store()
        self.assertTrue(store.append_snapshot(self.verified))
        self.assertFalse(self.store().append_snapshot(self.verified))
        rows = store.read_rows(self.verified["snapshot_sha256"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["scope"] == "SHADOW_ARCHIVE_ONLY" and r["formal_A"] == 0
                            and r["available_at"] is None for r in rows))
        self.assertEqual(store.summary(self.verified["snapshot_sha256"])["counts"], {"SSQ": 1, "DLT": 1})
        with store.connect(readonly=True) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {"snapshots", "artifacts", "rows"})

    def test_nonempty_unmarked_database_unchanged(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE original (data TEXT)")
            db.execute("INSERT INTO original VALUES ('preserve')")
            db.commit()
        before = self.path.read_bytes()
        with self.assertRaises(ShadowStoreError):
            self.store()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path)+"-wal").exists())
        self.assertFalse(Path(str(self.path)+"-shm").exists())

    def test_existing_empty_file_is_preserved(self):
        self.path.touch()
        with self.assertRaises(ShadowStoreError):
            self.store()
        self.assertEqual(self.path.read_bytes(), b"")

    def test_foreign_wal_even_with_colliding_application_id_has_no_side_effect(self):
        source = self.root/"foreign-source.sqlite3"
        owner = sqlite3.connect(source)
        self.addCleanup(owner.close)
        owner.execute("PRAGMA journal_mode=WAL")
        owner.execute(f"PRAGMA application_id={APPLICATION_ID}")
        owner.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        owner.execute("CREATE TABLE foreign_data (v TEXT)")
        owner.commit()
        owner.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        owner.execute("INSERT INTO foreign_data VALUES ('keep WAL')")
        owner.commit()
        shutil.copyfile(source, self.path)
        wal = Path(str(self.path)+"-wal")
        shutil.copyfile(Path(str(source)+"-wal"), wal)
        before = (self.path.read_bytes(), wal.read_bytes())
        with self.assertRaises(ShadowStoreError):
            self.store()
        self.assertEqual((self.path.read_bytes(), wal.read_bytes()), before)
        self.assertFalse(Path(str(self.path)+"-shm").exists())

    def test_path_replaced_after_construction_is_refused(self):
        store = self.store()
        foreign = self.root/"foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as db:
            db.execute("CREATE TABLE original (v TEXT)")
            db.commit()
        self.path.unlink()
        shutil.copyfile(foreign, self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ShadowStoreError):
            store.summary(self.verified["snapshot_sha256"])
        self.assertEqual(before, self.path.read_bytes())

    def test_concurrent_initialization_and_import(self):
        def import_one(_):
            return self.store().append_snapshot(self.verified)
        for round_number in range(4):
            self.path = self.root/f"concurrent-{round_number}.sqlite3"
            with self.subTest(round=round_number), ThreadPoolExecutor(max_workers=8) as workers:
                results = list(workers.map(import_one, range(8)))
                self.assertEqual(results.count(True), 1)
                self.assertEqual(results.count(False), 7)
        self.assertFalse(list(self.root.glob(".shadow-init-*")))

    def test_preflight_reopens_after_transient_checkpoint_view(self):
        store = self.store()
        check = storage._check_schema
        calls = []
        def checkpoint_view(db):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.DatabaseError("injected concurrent checkpoint view")
            return check(db)
        with patch.object(storage, "_check_schema", side_effect=checkpoint_view):
            with store.connect(readonly=True) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 0)
        self.assertGreaterEqual(len(calls), 3)

    def test_cross_process_initialization_and_import(self):
        archive = self.root/"fixture.zip"
        script = ("import sys; from research.ssq_dlt_d2_v44.shadow_snapshot import verify_snapshot_archive; "
                  "from research.ssq_dlt_d2_v44.shadow_store import ShadowStore; "
                  "v=verify_snapshot_archive(sys.argv[1],sys.argv[2],sys.argv[3],expected_counts={'SSQ':1,'DLT':1}); "
                  "print(ShadowStore(sys.argv[4]).append_snapshot(v))")
        command = [sys.executable, "-c", script, str(archive), digest(archive.read_bytes()),
                   self.verified["snapshot_sha256"], str(self.path)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        results = [process.communicate(timeout=30) for process in processes]
        self.assertEqual([p.returncode for p in processes], [0]*4, results)
        self.assertEqual(sorted(out.strip() for out, _ in results), ["False"]*3+["True"])

    def test_raw_sql_update_delete_replace_guards(self):
        store = self.store()
        store.append_snapshot(self.verified)
        with store.connect() as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            for table in ("snapshots", "artifacts", "rows"):
                row = db.execute(f'SELECT * FROM "{table}" LIMIT 1').fetchone()
                before = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                column = "scope" if table == "snapshots" else "sha256"
                for statement, params in ((f'UPDATE "{table}" SET {column}={column}', ()),
                                          (f'DELETE FROM "{table}"', ()),
                                          (f'INSERT OR REPLACE INTO "{table}" VALUES ({",".join("?" for _ in row)})', row)):
                    with self.subTest(table=table, statement=statement), self.assertRaises(sqlite3.IntegrityError):
                        db.execute(statement, params)
                self.assertEqual(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0], before)

    def test_atomic_rollback_after_partial_rows(self):
        store = self.store()
        original = store._insert_row
        calls = []
        def fail_second(db, snapshot_hash, row):
            calls.append(row)
            if len(calls) == 2:
                raise RuntimeError("injected interruption")
            original(db, snapshot_hash, row)
        with patch.object(store, "_insert_row", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                store.append_snapshot(self.verified)
        with store.connect(readonly=True) as db:
            self.assertEqual([db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                              for t in ("snapshots", "artifacts", "rows")], [0,0,0])
        self.assertTrue(store.append_snapshot(self.verified))

    def test_same_snapshot_different_archive_conflicts(self):
        store = self.store()
        store.append_snapshot(self.verified)
        changed = dict(self.verified, archive_sha256="f"*64)
        with self.assertRaisesRegex(ShadowStoreError, "IMMUTABLE_SNAPSHOT_CONFLICT"):
            store.append_snapshot(changed)
        self.assertEqual(store.summary(self.verified["snapshot_sha256"])["archive_sha256"], self.verified["archive_sha256"])

    def test_snapshot_isolation_and_no_latest_fallback(self):
        store = self.store()
        store.append_snapshot(self.verified)
        other_folder = self.root/"other"
        other_folder.mkdir()
        self.fixture.mapper += b"# another snapshot\n"
        other = self.fixture.verify(other_folder)
        self.assertTrue(store.append_snapshot(other))
        self.assertEqual(len(store.read_rows(other["snapshot_sha256"])), 2)
        self.assertEqual(len(store.read_rows(self.verified["snapshot_sha256"])), 2)
        with self.assertRaisesRegex(ShadowStoreError, "SNAPSHOT_NOT_FOUND"):
            store.read_rows("0"*64)

    def test_metadata_and_artifact_tamper_refused_before_insert(self):
        for kind in ("row", "artifact", "manifest", "scope", "counts"):
            value = copy.deepcopy(self.verified)
            if kind == "row":
                value["rows"][0]["front"] = [1,2,3,4,5,9]
            elif kind == "artifact":
                value["files"]["code/mapper.py"] += b"tamper"
            elif kind == "manifest":
                value["manifest_bytes"] += b" "
            elif kind == "scope":
                value["verification_scope"] = "FORMAL"
            else:
                value["counts"] = {"SSQ":2,"DLT":1}
            with self.subTest(kind=kind), self.assertRaises(ShadowStoreError):
                self.store().append_snapshot(value)

    def test_direct_api_available_at_backfill_is_refused(self):
        value = copy.deepcopy(self.verified)
        value["rows"][0]["available_at"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(ShadowStoreError):
            self.store().append_snapshot(value)

    def test_read_rechecks_artifact_bytes_after_sql_attacker_restores_trigger(self):
        store = self.store()
        store.append_snapshot(self.verified)
        with store.connect() as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='immutable_artifacts_UPDATE'").fetchone()[0]
            db.execute("DROP TRIGGER immutable_artifacts_UPDATE")
            db.execute("UPDATE artifacts SET raw=? WHERE file='code/mapper.py'", (b"attacker",))
            db.execute(trigger)
        with self.assertRaisesRegex(ShadowStoreError, "ARTIFACT_HASH_OR_SIZE_MISMATCH"):
            store.read_rows(self.verified["snapshot_sha256"])

    def test_read_rechecks_row_binding_even_with_recomputed_hash(self):
        store = self.store()
        store.append_snapshot(self.verified)
        with store.connect() as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='immutable_rows_UPDATE'").fetchone()[0]
            db.execute("DROP TRIGGER immutable_rows_UPDATE")
            row = json.loads(db.execute("SELECT payload FROM rows WHERE game='SSQ'").fetchone()[0])
            row["date"] = "2026-01-02"
            raw = encoded(row)
            db.execute("UPDATE rows SET payload=?,sha256=? WHERE game='SSQ'", (raw.decode(), digest(raw)))
            db.execute(trigger)
        with self.assertRaisesRegex(ShadowStoreError, "ORIGINAL_ROW_BINDING_MISMATCH"):
            store.summary(self.verified["snapshot_sha256"])


if __name__ == "__main__":
    unittest.main()
