from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from glp.maintenance import (
    BACKUP_SCHEMA,
    create_backup,
    maintenance_acceptance,
    restore_backup,
    source_health,
    verify_export,
)
from glp.storage import Store
from glp.util import atomic_json, atomic_write, sha256_bytes, sha256_json


class MaintenanceTests(unittest.TestCase):
    def make_store(self, root: Path, *, include_baseline: bool = True) -> Store:
        store = Store(root)
        draws = [{
            "issue": "2026113",
            "draw_date": "2026-09-29",
            "front": [3, 4, 20, 24, 29, 30],
            "back": [11],
        }]
        canonical_hash = sha256_json(draws)
        history = {
            "schema": 4,
            "game": "SSQ",
            "canonical_hash": canonical_hash,
            "commit_id": None,
            "draws": draws,
        }
        atomic_json(store.history_path, history)

        current_raw = b"current-official-response"
        current_digest = sha256_bytes(current_raw)
        atomic_write(store.raw_root / f"{current_digest}.bin", current_raw)
        current_row = {
            "source": "official_shanghai_L1",
            "requested_url": "https://example.invalid/current",
            "url": "https://example.invalid/current",
            "http_status": 200,
            "sha256": current_digest,
            "bytes": len(current_raw),
            "artifact": f"raw_responses/{current_digest}.bin",
            "fetched_at": "2026-10-01T12:00:00Z",
        }

        baseline_lineage = None
        if include_baseline:
            baseline_raw = b"baseline-official-response"
            baseline_digest = sha256_bytes(baseline_raw)
            atomic_write(store.raw_root / f"{baseline_digest}.bin", baseline_raw)
            baseline_lineage = {
                "raw_responses": [{
                    "source": "official_cwl_L0",
                    "requested_url": "https://example.invalid/baseline",
                    "url": "https://example.invalid/baseline",
                    "http_status": 200,
                    "sha256": baseline_digest,
                    "bytes": len(baseline_raw),
                    "artifact": f"raw_responses/{baseline_digest}.bin",
                    "fetched_at": "2026-10-01T12:00:00Z",
                }]
            }

        evidence = {
            "schema": "official-source-evidence-v8.5",
            "canonical_hash": canonical_hash,
            "crosscheck_status": "PASS",
            "crosscheck_count": 1,
            "draw_count": 1,
            "latest": draws[-1],
            "raw_response_status": "PASS",
            "raw_responses": [current_row],
            "source_receipts": [
                {
                    "source": "official_cwl_L0", "status": "FAIL",
                    "http_status": 403, "detail": "HTTP 403",
                    "latest_issue": None, "draw_count": 0,
                },
                {
                    "source": "official_shanghai_L1", "status": "PASS",
                    "http_status": 200, "detail": "verified",
                    "latest_issue": "2026113", "draw_count": 1,
                },
                {
                    "source": "official_hebei_L2", "status": "PASS",
                    "http_status": 200, "detail": "verified",
                    "latest_issue": "2026113", "draw_count": 1,
                },
            ],
        }
        if baseline_lineage is not None:
            evidence["baseline_lineage"] = baseline_lineage
        atomic_json(store.evidence_path, evidence)

        db = store._connect()
        try:
            db.execute(
                "INSERT INTO experiments(created_at,kind,status,input_hash,code_hash,payload_json) "
                "VALUES(?,?,?,?,?,?)",
                ("2026-10-01T12:00:00Z", "maintenance-fixture", "PASS",
                 "input", "code", "{}"),
            )
            db.commit()
        finally:
            db.close()
        return store

    def test_backup_restore_migration_and_tamper_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.make_store(root / "data")
            result = maintenance_acceptance(store, root / "维护 空间")
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(result["backup"]["raw_response_count"], 2)
            self.assertEqual(result["migration"]["status"], "PASS")
            self.assertIn("迁移恢复目标", result["migration"]["target"])
            self.assertEqual(result["tamper_result"]["status"], "FAIL")
            self.assertEqual(
                result["original_identity"]["sqlite"]["counts"],
                result["migrated_identity"]["sqlite"]["counts"],
            )

    def test_backup_manifest_includes_baseline_raw_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.make_store(root / "data", include_baseline=True)
            backup_dir = root / "backup"
            proof = create_backup(store, backup_dir)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["raw_response_count"], 2)
            raw_files = list((backup_dir / "raw_responses").glob("*.bin"))
            self.assertEqual(len(raw_files), 2)
            self.assertEqual(
                verify_export(backup_dir, expected_schema=BACKUP_SCHEMA)["status"],
                "PASS",
            )

    def test_restore_rejects_nonempty_target_and_tampered_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.make_store(root / "data")
            backup_dir = root / "backup"
            create_backup(store, backup_dir)

            nonempty = root / "occupied"
            nonempty.mkdir()
            (nonempty / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                restore_backup(backup_dir, nonempty)
            self.assertEqual((nonempty / "keep.txt").read_text(encoding="utf-8"), "do not overwrite")

            tampered = root / "tampered"
            shutil.copytree(backup_dir, tampered)
            history = tampered / "canonical_history.json"
            history.write_bytes(history.read_bytes() + b"x")
            self.assertEqual(
                verify_export(tampered, expected_schema=BACKUP_SCHEMA)["status"],
                "FAIL",
            )
            with self.assertRaisesRegex(ValueError, "backup verification failed"):
                restore_backup(tampered, root / "restore-target")

    def test_source_health_preserves_partial_official_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td) / "data")
            health = source_health(store)
            self.assertEqual(health["status"], "PASS")
            self.assertEqual(health["pass_count"], 2)
            failures = [x for x in health["alerts"] if x["kind"] == "official_source_failure"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["source"], "official_cwl_L0")
            self.assertEqual(failures[0]["http_status"], 403)

            evidence = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            evidence["source_receipts"][2]["status"] = "FAIL"
            atomic_json(store.evidence_path, evidence)
            self.assertEqual(source_health(store)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
