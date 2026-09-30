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


def inspect_effect(
    data_dir: Path, operation: str, after_id: int = 0,
    experiment_id: int | None = None,
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
                result.update(status="FAIL", reason="backend operation did not PASS")
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
                valid = bool(
                    payload.get("crosscheck_status") == "PASS"
                    and isinstance(integrity, dict) and integrity.get("ok") is True
                    and payload.get("canonical_hash")
                    and (data_dir / "source_evidence.json").is_file()
                )
                result["display_token"] = payload.get("canonical_hash", "")
            elif operation == "repair":
                integrity = payload.get("after") if payload.get("repaired") else payload.get("integrity")
                valid = bool(
                    payload.get("status") == "PASS"
                    and isinstance(integrity, dict) and integrity.get("ok") is True
                )
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
            if not isinstance(result.get("display_token"), str) or not result["display_token"]:
                valid = False
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
    args = parser.parse_args()
    print(json.dumps(inspect_effect(args.data_dir, args.operation, args.after_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
