from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_gui_effect import inspect_effect  # noqa: E402


def make_db(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(root / "ledger.sqlite3")
    db.executescript("""
        CREATE TABLE experiments(id INTEGER PRIMARY KEY, kind TEXT, status TEXT,
                                 created_at TEXT, payload_json TEXT);
        CREATE TABLE final_gate_decisions(gate_hash TEXT, status TEXT);
        CREATE TABLE freezes(prediction_id TEXT, freeze_hash TEXT);
    """)
    return db


def event(db: sqlite3.Connection, kind: str, status: str, payload: dict) -> None:
    db.execute(
        "INSERT INTO experiments(kind,status,created_at,payload_json) VALUES(?,?,?,?)",
        (kind, status, "2026-09-28T00:00:00Z", json.dumps(payload)),
    )
    db.commit()


class GuiBackendEffectTests(unittest.TestCase):
    def test_missing_ledger_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(inspect_effect(Path(td), "predict")["status"], "PENDING")

    def test_unrelated_row_or_stale_row_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with closing(make_db(root)) as db:
                event(db, "repair", "PASS", {"status": "PASS", "integrity": {"ok": True}})
            self.assertEqual(inspect_effect(root, "update")["status"], "PENDING")
            self.assertEqual(inspect_effect(root, "repair", after_id=1)["status"], "PENDING")

    def test_visual_only_or_failed_backend_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with closing(make_db(root)) as db:
                event(db, "prediction_blocked", "FAIL", {"gate": {"status": "FAIL"}})
            proof = inspect_effect(root, "predict")
            self.assertEqual(proof["status"], "FAIL")
            self.assertEqual(proof["kind"], "prediction_blocked")

    def test_predict_requires_persisted_freeze_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {"prediction_id": "P", "freeze_hash": "F", "gate_hash": "G"}
            with closing(make_db(root)) as db:
                event(db, "prediction_freeze", "PASS", payload)
                self.assertEqual(inspect_effect(root, "predict")["status"], "FAIL")
                db.execute("INSERT INTO freezes VALUES('P','F')")
                db.execute("INSERT INTO final_gate_decisions VALUES('G','PASS')")
                db.commit()
            self.assertEqual(inspect_effect(root, "predict")["status"], "PASS")

    def test_update_requires_persisted_quorum_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                "canonical_hash": "canonical",
            }
            with closing(make_db(root)) as db:
                event(db, "official_update", "PASS", payload)
            self.assertEqual(inspect_effect(root, "update")["status"], "FAIL")
            (root / "source_evidence.json").write_text("{}", encoding="utf-8")
            self.assertEqual(inspect_effect(root, "update")["status"], "PASS")

    def test_repair_and_audit_require_operation_specific_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with closing(make_db(root)) as db:
                event(db, "repair", "PASS", {"status": "PASS", "repaired": False})
                self.assertEqual(inspect_effect(root, "repair")["status"], "FAIL")
                event(db, "repair", "PASS", {
                    "status": "PASS", "repaired": False, "integrity": {"ok": True},
                    "detail": "integrity OK; no repair required",
                })
                event(db, "audit", "FAIL", {
                    "software_verdict": "FAIL", "formal_freeze_written": False,
                })
            self.assertEqual(inspect_effect(root, "repair")["status"], "PASS")
            self.assertEqual(inspect_effect(root, "audit")["status"], "FAIL")

    def test_audit_pass_requires_court_hash_for_display_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with closing(make_db(root)) as db:
                event(db, "audit", "PASS", {
                    "software_verdict": "PASS", "formal_freeze_written": False,
                    "court": {"court_hash": "court-proof"},
                })
            proof = inspect_effect(root, "audit")
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["display_token"], "court-proof")


    def test_exact_experiment_id_replay_ignores_later_same_kind_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "source_evidence.json").write_text("{}", encoding="utf-8")
            with closing(make_db(root)) as db:
                event(db, "official_update", "PASS", {
                    "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                    "canonical_hash": "first",
                })
                first_id = db.execute("SELECT MAX(id) FROM experiments").fetchone()[0]
                event(db, "official_update", "PASS", {
                    "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                    "canonical_hash": "second",
                })
            latest = inspect_effect(root, "update")
            exact = inspect_effect(root, "update", experiment_id=int(first_id))
            self.assertEqual(latest["display_token"], "second")
            self.assertEqual(exact["status"], "PASS")
            self.assertEqual(exact["experiment_id"], first_id)
            self.assertEqual(exact["display_token"], "first")

if __name__ == "__main__":
    unittest.main()
