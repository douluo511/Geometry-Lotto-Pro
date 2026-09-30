from __future__ import annotations

import hashlib
import json
import os
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


def write_updater_proof(root: Path, mode: str, payload: dict, parent_pid: int = 4242) -> None:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bootloader_pid = parent_pid + 50
    report = {
        "schema": "ssq-independent-updater-v2",
        "status": "PASS",
        "mode": mode,
        "pid": parent_pid + 100,
        "parent_pid": bootloader_pid,
        "ancestor_pids": [bootloader_pid, parent_pid],
        "expected_parent_pid": parent_pid,
        "parent_pid_match": True,
        "data_dir": str(root.resolve()),
        "updater_exe_sha256": "a" * 64,
        "service_result": payload,
        "service_result_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    (root / "updater_last_run.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )


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
            blocked = {
                "gate": {
                    "status": "FAIL",
                    "hard_fail_count": 2,
                    "checks": {
                        "source_freshness": False,
                        "data_integrity": True,
                        "evidence_hash_binding": False,
                    },
                    "gate_hash": "blocked-gate",
                },
                "auto_update_error": "SourceError: injected diagnostic failure",
            }
            with closing(make_db(root)) as db:
                event(db, "prediction_blocked", "FAIL", blocked)
            proof = inspect_effect(root, "predict")
            self.assertEqual(proof["status"], "FAIL")
            self.assertEqual(proof["kind"], "prediction_blocked")
            self.assertEqual(proof["failure_detail"]["gate_status"], "FAIL")
            self.assertEqual(proof["failure_detail"]["hard_fail_count"], 2)
            self.assertEqual(
                proof["failure_detail"]["failed_checks"],
                ["evidence_hash_binding", "source_freshness"],
            )
            self.assertEqual(proof["failure_detail"]["gate_hash"], "blocked-gate")
            self.assertIn("injected diagnostic failure", proof["failure_detail"]["auto_update_error"])

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

    def test_updater_process_requires_expected_gui_pid_in_ancestor_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                "canonical_hash": "canonical",
            }
            (root / "source_evidence.json").write_text("{}", encoding="utf-8")
            with closing(make_db(root)) as db:
                event(db, "official_update", "PASS", payload)
            write_updater_proof(root, "update", payload, parent_pid=4242)
            proof_path = root / "updater_last_run.json"
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            proof["ancestor_pids"] = [proof["parent_pid"], 9999]
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            result = inspect_effect(root, "update", parent_pid=4242)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["updater_process"]["status"], "FAIL")

    def test_update_requires_persisted_quorum_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                "canonical_hash": "canonical",
            }
            with closing(make_db(root)) as db:
                event(db, "official_update", "PASS", payload)
            missing_evidence = inspect_effect(root, "update")
            self.assertEqual(missing_evidence["status"], "FAIL")
            self.assertFalse(missing_evidence["contract_checks"]["source_evidence_file"])
            (root / "source_evidence.json").write_text("{}", encoding="utf-8")
            self.assertEqual(inspect_effect(root, "update", parent_pid=4242)["status"], "FAIL")
            write_updater_proof(root, "update", payload)
            proof = inspect_effect(root, "update", parent_pid=4242)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["updater_process"]["child_pid"], 4342)
            self.assertTrue(all(proof["contract_checks"].values()))
            self.assertEqual(proof["updater_process"]["updater_exe_sha256"], "a" * 64)

    def test_repair_and_audit_require_operation_specific_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with closing(make_db(root)) as db:
                event(db, "repair", "PASS", {"status": "PASS", "repaired": False})
                self.assertEqual(inspect_effect(root, "repair")["status"], "FAIL")
                repair_payload = {
                    "status": "PASS", "repaired": False, "integrity": {"ok": True},
                    "detail": "integrity OK; no repair required",
                }
                event(db, "repair", "PASS", repair_payload)
                event(db, "audit", "FAIL", {
                    "software_verdict": "FAIL", "formal_freeze_written": False,
                })
            self.assertEqual(inspect_effect(root, "repair", parent_pid=4242)["status"], "FAIL")
            write_updater_proof(root, "repair", repair_payload)
            self.assertEqual(inspect_effect(root, "repair", parent_pid=4242)["status"], "PASS")
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
            first_payload = {
                "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                "canonical_hash": "first",
            }
            second_payload = {
                "crosscheck_status": "PASS", "persisted_integrity": {"ok": True},
                "canonical_hash": "second",
            }
            with closing(make_db(root)) as db:
                event(db, "official_update", "PASS", first_payload)
                first_id = db.execute("SELECT MAX(id) FROM experiments").fetchone()[0]
                event(db, "official_update", "PASS", second_payload)
            write_updater_proof(root, "update", second_payload)
            latest = inspect_effect(root, "update", parent_pid=4242)
            self.assertEqual(latest["status"], "PASS")
            self.assertEqual(latest["display_token"], "second")
            write_updater_proof(root, "update", first_payload)
            exact = inspect_effect(root, "update", experiment_id=int(first_id), parent_pid=4242)
            self.assertEqual(exact["status"], "PASS")
            self.assertEqual(exact["experiment_id"], first_id)
            self.assertEqual(exact["display_token"], "first")


    def test_relative_data_dir_replays_read_only_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            with closing(make_db(data)) as db:
                event(db, "repair", "PASS", {
                    "status": "PASS", "repaired": False, "integrity": {"ok": True},
                    "detail": "integrity OK; no repair required",
                })
            write_updater_proof(data, "repair", {
                "status": "PASS", "repaired": False, "integrity": {"ok": True},
                "detail": "integrity OK; no repair required",
            })
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                proof = inspect_effect(Path("data"), "repair", parent_pid=4242)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["kind"], "repair")

if __name__ == "__main__":
    unittest.main()
