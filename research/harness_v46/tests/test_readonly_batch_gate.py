"""Synthetic-only adversarial checks for independent V4.6 evidence inspection."""
import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46 import core, readonly_batch_gate as gate


def _snapshot(lottery):
    rules = core.RULES[lottery]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    draws = []
    for i in range(125):
        stamp = start + timedelta(days=i)
        # Deliberately invented and repetitive data, never evidence of skill.
        draws.append({
            "issue": str(26001 + i),
            "front": list(range(1, rules["front"] + 1)),
            "back": list(range(1, rules["back"] + 1)),
            "drawn_at": stamp.isoformat(),
            "published_at": (stamp + timedelta(hours=1)).isoformat(),
        })
    return {
        "lottery": lottery, "draws": draws,
        "as_of": "2026-10-20T00:00:00+00:00",
        "sales_cutoff": "2026-10-23T12:00:00+08:00",
        "target_draw_at": "2026-10-23T21:00:00+08:00",
        "target_issue": "29999",
        "provenance": {"status": "SYNTHETIC_NOT_OFFICIAL"},
    }


class LocalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "read_only.sqlite"
        self.run_id = "SYNTHETIC-COMPLETE-BATCH"
        db = sqlite3.connect(self.path)
        try:
            core.init_ledger(db)
            with db:
                for game in ("SSQ", "DLT"):
                    snapshot = _snapshot(game)
                    for model in core.MODELS:
                        core.freeze_shadow(
                            db, self.run_id, snapshot, core.forecast(snapshot, model),
                            "2026-10-21T00:00:00+00:00"
                        )
        finally:
            db.close()

    def _edit(self, sql, args=()):
        # A SQLite connection context manager commits but does NOT close.
        # Windows keeps the database file locked until close() is explicit.
        db = sqlite3.connect(self.path)
        try:
            with db:
                db.execute(sql, args)
        finally:
            db.close()

    def test_complete_dual_lottery_batch_passes_local_only(self):
        original = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = gate.inspect_run(self.path, self.run_id)
        self.assertEqual(report["complete_model_rows"], 12)
        self.assertEqual(report["status"], "LOCAL_INTEGRITY_PASS_SHADOW_ONLY")
        self.assertEqual(set(report["games"]), {"SSQ", "DLT"})
        self.assertFalse(report["formal_a_eligible"])
        self.assertFalse(report["external_tsa_verified"])
        self.assertFalse(report["predictive_edge_proven"])
        self.assertEqual(original, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_missing_model_blocks_comparison(self):
        self._edit("DROP TRIGGER prevent_prediction_delete")
        self._edit("DELETE FROM predictions WHERE model='challenger' AND lottery='DLT'")
        with self.assertRaisesRegex(gate.EvidenceGateError, "incomplete 12/12"):
            gate.inspect_run(self.path, self.run_id)

    def test_payload_corruption_blocks(self):
        self._edit("DROP TRIGGER prevent_prediction_update")
        self._edit("UPDATE predictions SET payload='{}' WHERE model='hot60' AND lottery='SSQ'")
        with self.assertRaisesRegex(gate.EvidenceGateError, "SHA mismatch"):
            gate.inspect_run(self.path, self.run_id)

    def test_after_cutoff_timestamp_blocks(self):
        self._edit("DROP TRIGGER prevent_prediction_update")
        self._edit(
            "UPDATE predictions SET frozen_at='2026-10-25T00:00:00+08:00' "
            "WHERE model='ewma' AND lottery='SSQ'"
        )
        with self.assertRaisesRegex(gate.EvidenceGateError, "outside as-of"):
            gate.inspect_run(self.path, self.run_id)

    def test_context_tamper_blocks(self):
        self._edit("DROP TRIGGER prevent_context_update")
        self._edit(
            "UPDATE run_context SET snapshot_sha256=? WHERE lottery='DLT'",
            ("f" * 64,)
        )
        with self.assertRaisesRegex(gate.EvidenceGateError, "mixed snapshot SHA"):
            gate.inspect_run(self.path, self.run_id)

    def test_audit_event_mismatch_blocks(self):
        self._edit("DROP TRIGGER prevent_audit_update")
        self._edit("UPDATE audit_events SET payload='{}' WHERE event_id=1")
        with self.assertRaisesRegex(gate.EvidenceGateError, "unknown/duplicate freeze event"):
            gate.inspect_run(self.path, self.run_id)

    def test_present_sidecar_blocks(self):
        wal = Path(str(self.path) + "-wal")
        wal.write_bytes(b"synthetic sidecar placeholder")
        with self.assertRaisesRegex(gate.EvidenceGateError, "sidecar present"):
            gate.inspect_run(self.path, self.run_id)

    def test_nonexistent_database_not_created(self):
        path = Path(self.tmp.name) / "not_found.sqlite"
        with self.assertRaisesRegex(gate.EvidenceGateError, "missing database"):
            gate.inspect_run(path, self.run_id)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
