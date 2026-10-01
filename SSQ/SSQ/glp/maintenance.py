from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .storage import Store
from .util import atomic_json, atomic_write, sha256_json, utc_now


BACKUP_SCHEMA = "ssq-maintenance-backup-v1"
EVIDENCE_EXPORT_SCHEMA = "ssq-maintenance-evidence-export-v1"
REQUIRED_SQLITE_TABLES = {
    "experiments",
    "freezes",
    "replays",
    "canonical_contexts",
    "final_gate_decisions",
    "postmortems",
}
REQUIRED_SQLITE_TRIGGERS = {
    "freezes_no_update",
    "freezes_no_delete",
    "replays_no_update",
    "contexts_no_update",
    "final_gate_no_update",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("manifest path must be a nonempty POSIX relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("manifest path is unsafe")
    return Path(*pure.parts)


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    source_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        target_db.commit()
    finally:
        target_db.close()
        source_db.close()


def _sqlite_inventory(path: Path) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()
        objects = db.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table','trigger')"
        ).fetchall()
        tables = {name for typ, name in objects if typ == "table"}
        triggers = {name for typ, name in objects if typ == "trigger"}
        counts = {}
        for table in sorted(REQUIRED_SQLITE_TABLES):
            if table in tables:
                counts[table] = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return {
            "integrity": str(integrity[0]).lower() if integrity else "",
            "tables": sorted(tables),
            "triggers": sorted(triggers),
            "counts": counts,
        }
    finally:
        db.close()


def _validate_sqlite(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError("ledger.sqlite3 missing")
    inventory = _sqlite_inventory(path)
    if inventory["integrity"] != "ok":
        raise ValueError("SQLite backup integrity_check failed")
    if not REQUIRED_SQLITE_TABLES.issubset(inventory["tables"]):
        raise ValueError("SQLite backup is missing required tables")
    if not REQUIRED_SQLITE_TRIGGERS.issubset(inventory["triggers"]):
        raise ValueError("SQLite backup is missing immutability triggers")
    return inventory


def _state_identity(root: Path) -> dict[str, Any]:
    history_path = root / "canonical_history.json"
    evidence_path = root / "source_evidence.json"
    ledger_path = root / "ledger.sqlite3"
    if not history_path.is_file() or not evidence_path.is_file() or not ledger_path.is_file():
        raise FileNotFoundError("maintenance state is incomplete")

    history = json.loads(history_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if history.get("game") != "SSQ":
        raise ValueError("backup dataset game mismatch")
    draws = history.get("draws")
    if not isinstance(draws, list) or not draws:
        raise ValueError("backup canonical history is empty")
    canonical_hash = str(history.get("canonical_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", canonical_hash):
        raise ValueError("backup canonical hash is malformed")
    if sha256_json(draws) != canonical_hash:
        raise ValueError("backup canonical history hash mismatch")
    if evidence.get("canonical_hash") != canonical_hash:
        raise ValueError("backup source evidence is not bound to canonical history")

    raw_rows = evidence.get("raw_responses")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("backup source evidence has no raw response manifest")
    raw_hashes: list[str] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise ValueError("backup raw manifest row is malformed")
        digest = str(row.get("sha256") or "")
        byte_count = row.get("bytes")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("backup raw response hash is malformed")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError("backup raw response byte count is malformed")
        raw_path = root / "raw_responses" / f"{digest}.bin"
        if not raw_path.is_file():
            raise FileNotFoundError(f"backup raw response missing: {digest}")
        if raw_path.stat().st_size != byte_count or _sha256_file(raw_path) != digest:
            raise ValueError("backup raw response does not match manifest")
        raw_hashes.append(digest)

    sqlite_inventory = _validate_sqlite(ledger_path)
    return {
        "canonical_hash": canonical_hash,
        "history_sha256": _sha256_file(history_path),
        "source_evidence_sha256": _sha256_file(evidence_path),
        "raw_response_count": len(raw_hashes),
        "raw_response_hashes": sorted(raw_hashes),
        "sqlite": sqlite_inventory,
    }


def source_health(store: Store) -> dict[str, Any]:
    if not store.evidence_path.is_file():
        return {"status": "FAIL", "alerts": [{"kind": "missing_source_evidence"}]}
    evidence = json.loads(store.evidence_path.read_text(encoding="utf-8"))
    receipts = evidence.get("source_receipts")
    if not isinstance(receipts, list) or len(receipts) != 3:
        return {"status": "FAIL", "alerts": [{"kind": "incomplete_source_receipts"}]}
    alerts = []
    pass_count = 0
    for receipt in receipts:
        if not isinstance(receipt, dict):
            alerts.append({"kind": "malformed_source_receipt"})
            continue
        status = receipt.get("status")
        if status == "PASS":
            pass_count += 1
        elif status == "FAIL":
            alerts.append({
                "kind": "official_source_failure",
                "source": receipt.get("source"),
                "http_status": receipt.get("http_status"),
                "detail": receipt.get("detail"),
            })
        else:
            alerts.append({
                "kind": "indeterminate_source_status",
                "source": receipt.get("source"),
                "status": status,
            })
    healthy = (
        pass_count >= 2
        and evidence.get("crosscheck_status") == "PASS"
        and all(a["kind"] == "official_source_failure" for a in alerts)
    )
    return {
        "status": "PASS" if healthy else "FAIL",
        "pass_count": pass_count,
        "crosscheck_status": evidence.get("crosscheck_status"),
        "alerts": alerts,
        "latest_issue": (evidence.get("latest") or {}).get("issue"),
    }


def _copy_failure_evidence(source_root: Path, destination_root: Path) -> int:
    failure_root = source_root / "failed"
    if not failure_root.is_dir():
        return 0
    copied = 0
    for path in sorted(p for p in failure_root.rglob("*") if p.is_file()):
        if path.is_symlink():
            raise ValueError("failure evidence symlink is not allowed")
        rel = path.relative_to(source_root)
        target = destination_root / rel
        atomic_write(target, path.read_bytes())
        copied += 1
    return copied


def _export_state(store: Store, destination: Path, schema: str) -> dict[str, Any]:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("maintenance destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)

    # Validate the accepted state without imposing a freshness window on a
    # backup/export operation. All bytes are re-hashed below.
    source_identity = _state_identity(store.root)

    atomic_write(destination / "canonical_history.json", store.history_path.read_bytes())
    atomic_write(destination / "source_evidence.json", store.evidence_path.read_bytes())

    evidence = json.loads(store.evidence_path.read_text(encoding="utf-8"))
    records = evidence.get("raw_responses") or []
    for row in records:
        digest = str(row["sha256"])
        source = store.raw_root / f"{digest}.bin"
        target = destination / "raw_responses" / f"{digest}.bin"
        atomic_write(target, source.read_bytes())

    failure_file_count = _copy_failure_evidence(store.root, destination)
    _sqlite_snapshot(store.db_path, destination / "ledger.sqlite3")

    files = []
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        rel = path.relative_to(destination).as_posix()
        if rel == "MANIFEST.json":
            continue
        files.append({
            "path": rel,
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        })

    manifest = {
        "schema": schema,
        "status": "PASS",
        "created_at": utc_now(),
        "game": "SSQ",
        "canonical_hash": source_identity["canonical_hash"],
        "source_root_name": store.root.name,
        "failure_evidence_file_count": failure_file_count,
        "files": files,
    }
    atomic_json(destination / "MANIFEST.json", manifest)
    proof = verify_export(destination, expected_schema=schema)
    if proof["status"] != "PASS":
        raise RuntimeError(f"maintenance export verification failed: {proof}")
    return proof


def create_backup(store: Store, destination: Path) -> dict[str, Any]:
    return _export_state(store, destination, BACKUP_SCHEMA)


def export_evidence(store: Store, destination: Path) -> dict[str, Any]:
    return _export_state(store, destination, EVIDENCE_EXPORT_SCHEMA)


def verify_export(destination: Path, *, expected_schema: str | None = None) -> dict[str, Any]:
    destination = destination.resolve()
    manifest_path = destination / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"status": "FAIL", "reason": "MANIFEST.json missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema = manifest.get("schema")
        if expected_schema is not None and schema != expected_schema:
            raise ValueError("maintenance manifest schema mismatch")
        if schema not in {BACKUP_SCHEMA, EVIDENCE_EXPORT_SCHEMA}:
            raise ValueError("unknown maintenance manifest schema")
        if manifest.get("game") != "SSQ" or manifest.get("status") != "PASS":
            raise ValueError("maintenance manifest identity/status mismatch")
        rows = manifest.get("files")
        if not isinstance(rows, list) or not rows:
            raise ValueError("maintenance manifest file list is empty")
        expected: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("maintenance manifest row is malformed")
            rel_text = str(row.get("path") or "")
            rel = _safe_relative(rel_text)
            if rel_text in expected:
                raise ValueError("duplicate maintenance manifest path")
            expected[rel_text] = row
            path = (destination / rel).resolve()
            path.relative_to(destination)
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"maintenance artifact missing/unsafe: {rel_text}")
            byte_count = row.get("bytes")
            digest = row.get("sha256")
            if (isinstance(byte_count, bool) or not isinstance(byte_count, int)
                    or byte_count < 0 or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError("maintenance manifest hash/size is malformed")
            if path.stat().st_size != byte_count or _sha256_file(path) != digest:
                raise ValueError(f"maintenance artifact hash mismatch: {rel_text}")

        actual = {
            p.relative_to(destination).as_posix()
            for p in destination.rglob("*")
            if p.is_file() and p.name != "MANIFEST.json"
        }
        if actual != set(expected):
            raise ValueError("maintenance export has missing or unmanifested files")
        required = {"canonical_history.json", "source_evidence.json", "ledger.sqlite3"}
        if not required.issubset(expected):
            raise ValueError("maintenance export lacks required state files")

        identity = _state_identity(destination)
        if identity["canonical_hash"] != manifest.get("canonical_hash"):
            raise ValueError("maintenance manifest canonical hash mismatch")
        return {
            "status": "PASS",
            "schema": schema,
            "manifest_sha256": _sha256_file(manifest_path),
            "file_count": len(expected),
            "canonical_hash": identity["canonical_hash"],
            "raw_response_count": identity["raw_response_count"],
            "sqlite": identity["sqlite"],
        }
    except Exception as exc:
        return {"status": "FAIL", "reason": f"{type(exc).__name__}: {exc}"}


def restore_backup(backup: Path, target_root: Path) -> dict[str, Any]:
    backup = backup.resolve()
    target_root = target_root.resolve()
    proof = verify_export(backup, expected_schema=BACKUP_SCHEMA)
    if proof.get("status") != "PASS":
        raise ValueError(f"backup verification failed: {proof}")
    if target_root.exists() and any(target_root.iterdir()):
        raise ValueError("restore target must be empty; in-place destructive restore is forbidden")
    target_root.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((backup / "MANIFEST.json").read_text(encoding="utf-8"))
    try:
        for row in manifest["files"]:
            rel = _safe_relative(str(row["path"]))
            source = (backup / rel).resolve()
            source.relative_to(backup)
            target = (target_root / rel).resolve()
            target.relative_to(target_root)
            atomic_write(target, source.read_bytes())

        restored = _state_identity(target_root)
        if restored["canonical_hash"] != proof["canonical_hash"]:
            raise ValueError("restored canonical identity differs from backup")
        if restored["sqlite"]["counts"] != proof["sqlite"]["counts"]:
            raise ValueError("restored SQLite row inventory differs from backup")
        atomic_json(target_root / "RESTORE_PROVENANCE.json", {
            "schema": "ssq-maintenance-restore-v1",
            "status": "PASS",
            "restored_at": utc_now(),
            "backup_manifest_sha256": proof["manifest_sha256"],
            "canonical_hash": restored["canonical_hash"],
        })
        return {
            "status": "PASS",
            "canonical_hash": restored["canonical_hash"],
            "sqlite_counts": restored["sqlite"]["counts"],
            "backup_manifest_sha256": proof["manifest_sha256"],
            "target": str(target_root),
        }
    except Exception:
        shutil.rmtree(target_root, ignore_errors=True)
        raise


def migrate_backup(backup: Path, target_root: Path) -> dict[str, Any]:
    result = restore_backup(backup, target_root)
    result["schema"] = "ssq-maintenance-migration-v1"
    result["migration"] = "verified backup -> distinct app-data root"
    return result


def maintenance_acceptance(store: Store, workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    backup_dir = workspace / "backup"
    export_dir = workspace / "evidence-export"
    migrated_root = workspace / "迁移恢复目标"

    backup = create_backup(store, backup_dir)
    evidence_export = export_evidence(store, export_dir)
    migration = migrate_backup(backup_dir, migrated_root)
    source_status = source_health(store)

    original_identity = _state_identity(store.root)
    migrated_identity = _state_identity(migrated_root)

    tamper_dir = workspace / "tamper"
    shutil.copytree(backup_dir, tamper_dir)
    tamper_path = tamper_dir / "canonical_history.json"
    raw = bytearray(tamper_path.read_bytes())
    if not raw:
        raise RuntimeError("maintenance tamper fixture is empty")
    raw[-1] = (raw[-1] + 1) % 256
    tamper_path.write_bytes(bytes(raw))
    tamper_proof = verify_export(tamper_dir, expected_schema=BACKUP_SCHEMA)

    checks = {
        "backup_verified": backup.get("status") == "PASS",
        "evidence_export_verified": evidence_export.get("status") == "PASS",
        "migration_verified": migration.get("status") == "PASS",
        "canonical_identity_preserved": (
            migrated_identity["canonical_hash"] == original_identity["canonical_hash"]
        ),
        "ledger_inventory_preserved": (
            migrated_identity["sqlite"]["counts"] == original_identity["sqlite"]["counts"]
        ),
        "source_health_reported": source_status.get("status") == "PASS",
        "tampered_backup_rejected": tamper_proof.get("status") == "FAIL",
        "unicode_target_supported": "迁移恢复目标" in str(migrated_root),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "schema": "ssq-maintenance-acceptance-v1",
        "checks": checks,
        "backup": backup,
        "evidence_export": evidence_export,
        "migration": migration,
        "source_health": source_status,
        "tamper_result": tamper_proof,
        "original_identity": original_identity,
        "migrated_identity": migrated_identity,
    }
