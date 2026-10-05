"""Read-only proof that a physical GUI click reached the expected SSQ backend.

The click runner gives every launched EXE an empty GLP_DATA_DIR.  A newly
committed, operation-specific ledger row is therefore required; changing a
window, showing a spinner, or writing an unrelated row cannot pass this check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


EVENT_KINDS = {
    "predict": ("prediction_freeze", "prediction_blocked"),
    "update": ("official_update",),
    "repair": ("repair",),
    "audit": ("audit",),
}


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _service_payload_matches_ledger(
    operation: str, service_payload: dict[str, Any], ledger_payload: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Bind updater result to the immutable backend ledger without conflating wrapper metadata.

    For update, updater.py adds only transport-wrapper fields after LottoService.update()
    has already committed the exact business payload to the ledger.  Those explicitly
    allowed wrapper fields may differ from the immutable ledger payload; every business
    field must remain byte-for-byte JSON equivalent after canonical serialization.
    """
    if operation == "update":
        allowed_wrapper_fields = {"status", "update_attempts"}
    else:
        allowed_wrapper_fields: set[str] = set()

    service_keys = set(service_payload)
    ledger_keys = set(ledger_payload)
    unexpected = sorted(service_keys - ledger_keys - allowed_wrapper_fields)
    missing = sorted(ledger_keys - service_keys)
    service_core = {
        key: value for key, value in service_payload.items()
        if key not in allowed_wrapper_fields
    }
    core_equal = service_core == ledger_payload
    return (
        not unexpected and not missing and core_equal,
        {
            "allowed_wrapper_fields": sorted(allowed_wrapper_fields),
            "unexpected_service_fields": unexpected,
            "missing_ledger_fields": missing,
            "ledger_payload_sha256": _sha256_json(ledger_payload),
            "service_core_sha256": _sha256_json(service_core),
            "core_equal": core_equal,
        },
    )


def _verify_updater_process(
    data_dir: Path, operation: str, parent_pid: int, service_payload: dict[str, Any],
) -> dict[str, Any]:
    proof_path = data_dir / "updater_last_run.json"
    result: dict[str, Any] = {"status": "FAIL", "path": str(proof_path)}
    if operation not in {"update", "repair"} or parent_pid <= 0:
        result["reason"] = "updater operation or parent PID is invalid"
        return result
    if not proof_path.is_file():
        # The child updater commits its service ledger before the parent
        # UpdaterClient can persist updater_last_run.json after child exit.
        # This is a bounded transient state: keep polling, never promote it.
        result.update(
            status="PENDING",
            reason="updater process evidence has not been persisted yet",
        )
        return result
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
        child_pid = int(proof.get("pid") or 0)
        recorded_parent = int(proof.get("parent_pid") or 0)
        expected_parent = int(proof.get("expected_parent_pid") or 0)
        raw_ancestors = proof.get("ancestor_pids")
        ancestor_pids = (
            [int(value) for value in raw_ancestors]
            if isinstance(raw_ancestors, list)
            and all(isinstance(value, int) and value > 0 for value in raw_ancestors)
            else []
        )
        updater_hash = str(proof.get("updater_exe_sha256") or "")
        payload_hash = str(proof.get("service_result_sha256") or "")
        data_root = Path(str(proof.get("data_dir") or "")).resolve()
        process_chain_ok = bool(
            child_pid > 0
            and child_pid != parent_pid
            and recorded_parent > 0
            and ancestor_pids
            and recorded_parent == ancestor_pids[0]
            and expected_parent == parent_pid
            and parent_pid in ancestor_pids
            and child_pid not in ancestor_pids
        )
        proof_service_result = proof.get("service_result")
        payload_bound = False
        payload_binding: dict[str, Any] = {
            "core_equal": False,
            "reason": "updater service_result is not an object",
        }
        if isinstance(proof_service_result, dict):
            payload_bound, payload_binding = _service_payload_matches_ledger(
                operation, proof_service_result, service_payload,
            )
        valid = bool(
            proof.get("schema") == "ssq-independent-updater-v2"
            and proof.get("status") == "PASS"
            and proof.get("mode") == operation
            and proof.get("parent_pid_match") is True
            and process_chain_ok
            and len(updater_hash) == 64 and all(ch in "0123456789abcdef" for ch in updater_hash)
            and data_root == data_dir.resolve()
            and isinstance(proof_service_result, dict)
            and payload_hash == _sha256_json(proof_service_result)
            and payload_bound
        )
        result.update(
            status="PASS" if valid else "FAIL",
            child_pid=child_pid,
            parent_pid=recorded_parent,
            expected_parent_pid=expected_parent,
            ancestor_pids=ancestor_pids,
            updater_exe_sha256=updater_hash,
            service_result_sha256=payload_hash,
            payload_binding=payload_binding,
        )
        if not valid:
            result["reason"] = "updater process evidence does not bind to this GUI/backend effect"
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result["reason"] = f"invalid updater process evidence: {exc}"
        return result


def inspect_effect(
    data_dir: Path, operation: str, after_id: int = 0,
    experiment_id: int | None = None, parent_pid: int = 0,
) -> dict[str, Any]:
    if (operation not in EVENT_KINDS or after_id < 0
            or (experiment_id is not None and experiment_id <= 0)):
        raise ValueError("unknown operation, negative baseline ID, or invalid experiment ID")
    db_path = (data_dir / "ledger.sqlite3").resolve()
    result: dict[str, Any] = {
        "status": "PENDING", "operation": operation, "after_id": after_id,
        "latest_id": 0, "database": str(db_path),
    }
    if not db_path.is_file():
        return result
    try:
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=0.2)
        try:
            row = db.execute("SELECT COALESCE(MAX(id), 0) FROM experiments").fetchone()
            result["latest_id"] = int(row[0])
            kinds = EVENT_KINDS[operation]
            placeholders = ",".join("?" for _ in kinds)
            if experiment_id is None:
                event = db.execute(
                    f"SELECT id,kind,status,created_at,payload_json FROM experiments "
                    f"WHERE id>? AND kind IN ({placeholders}) ORDER BY id DESC LIMIT 1",
                    (after_id, *kinds),
                ).fetchone()
            else:
                event = db.execute(
                    f"SELECT id,kind,status,created_at,payload_json FROM experiments "
                    f"WHERE id=? AND id>? AND kind IN ({placeholders}) LIMIT 1",
                    (experiment_id, after_id, *kinds),
                ).fetchone()
            if event is None:
                return result
            event_id, kind, status, created_at, raw_payload = event
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                result.update(status="FAIL", reason="backend payload is not an object")
                return result
            result.update(
                experiment_id=event_id, kind=kind, event_status=status,
                created_at=created_at, payload_sha256=_sha256_json(payload),
            )
            if status != "PASS" or kind == "prediction_blocked":
                detail: dict[str, Any] = {}
                if kind == "prediction_blocked":
                    gate = payload.get("gate")
                    if isinstance(gate, dict):
                        checks = gate.get("checks")
                        failed_checks = (
                            sorted(str(name) for name, ok in checks.items() if ok is not True)
                            if isinstance(checks, dict) else []
                        )
                        detail = {
                            "gate_status": gate.get("status"),
                            "hard_fail_count": gate.get("hard_fail_count"),
                            "failed_checks": failed_checks,
                            "gate_hash": gate.get("gate_hash"),
                            "auto_update_error": payload.get("auto_update_error"),
                        }
                result.update(
                    status="FAIL",
                    reason="backend operation did not PASS",
                    failure_detail=detail,
                )
                return result
            if operation == "predict":
                gate_hash = payload.get("gate_hash")
                freeze_hash = payload.get("freeze_hash")
                prediction_id = payload.get("prediction_id")
                gate = db.execute(
                    "SELECT status FROM final_gate_decisions WHERE gate_hash=?",
                    (gate_hash,),
                ).fetchone() if gate_hash else None
                freeze = db.execute(
                    "SELECT freeze_hash FROM freezes WHERE prediction_id=?",
                    (prediction_id,),
                ).fetchone() if prediction_id else None
                valid = bool(
                    gate_hash and freeze_hash and prediction_id
                    and gate and gate[0] == "PASS"
                    and freeze and freeze[0] == freeze_hash
                )
                result["final_gate_status"] = gate[0] if gate else "MISSING"
                result["display_token"] = freeze_hash if isinstance(freeze_hash, str) else ""
            elif operation == "update":
                integrity = payload.get("persisted_integrity")
                update_checks = {
                    "crosscheck_status": payload.get("crosscheck_status") == "PASS",
                    "persisted_integrity": isinstance(integrity, dict) and integrity.get("ok") is True,
                    "canonical_hash": bool(payload.get("canonical_hash")),
                    "source_evidence_file": (data_dir / "source_evidence.json").is_file(),
                }
                result["contract_checks"] = update_checks
                valid = all(update_checks.values())
                result["display_token"] = payload.get("canonical_hash", "")
            elif operation == "repair":
                integrity = payload.get("after") if payload.get("repaired") else payload.get("integrity")
                repair_checks = {
                    "service_status": payload.get("status") == "PASS",
                    "persisted_integrity": isinstance(integrity, dict) and integrity.get("ok") is True,
                }
                result["contract_checks"] = repair_checks
                valid = all(repair_checks.values())
                result["display_token"] = payload.get("canonical_hash") or payload.get("detail", "")
            else:
                court = payload.get("court")
                valid = bool(
                    payload.get("software_verdict") == "PASS"
                    and payload.get("formal_freeze_written") is False
                    and isinstance(court, dict)
                    and court.get("court_hash")
                )
                result["display_token"] = court.get("court_hash", "") if isinstance(court, dict) else ""
            token_ok = isinstance(result.get("display_token"), str) and bool(result["display_token"])
            if not token_ok:
                valid = False
            if operation in {"update", "repair"}:
                updater = _verify_updater_process(data_dir, operation, parent_pid, payload)
                result["updater_process"] = updater
                updater_status = updater.get("status")
                result.setdefault("contract_checks", {})["updater_process"] = updater_status == "PASS"
                if updater_status == "PENDING" and valid:
                    result.update(
                        status="PENDING",
                        reason="waiting for updater process evidence to be persisted",
                    )
                    return result
                valid = valid and updater_status == "PASS"
            result["status"] = "PASS" if valid else "FAIL"
            if not valid:
                result["reason"] = "operation-specific persisted contract is incomplete"
            return result
        finally:
            db.close()
    except (OSError, sqlite3.OperationalError) as exc:
        # A writer may be opening/committing the database. Keep polling until
        # the bounded click timeout; no unavailable snapshot can ever PASS.
        result["reason"] = f"database temporarily unreadable: {exc}"
        return result
    except (TypeError, ValueError, sqlite3.DatabaseError) as exc:
        result.update(status="FAIL", reason=f"invalid backend ledger: {exc}")
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--operation", choices=sorted(EVENT_KINDS), required=True)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(inspect_effect(args.data_dir, args.operation, args.after_id, parent_pid=args.parent_pid), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
