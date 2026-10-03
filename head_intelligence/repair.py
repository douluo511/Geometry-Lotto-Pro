from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from head_intelligence.engine import APP_VERSION, SNAPSHOT_FILE
from head_intelligence.software_update import software_update_environment_status


def validate_snapshot(engine, value) -> bool:
    if not isinstance(value, dict) or value.get("status") != "PASS":
        return False
    items, health = value.get("items"), value.get("source_health")
    if not isinstance(items, list) or not items or not isinstance(health, list) or not health:
        return False
    if value.get("deduped_count") != len(items) or not value.get("snapshot_id"):
        return False
    for source in health:
        digest = str(source.get("raw_hash") or "")
        source_id = str(source.get("source_id") or "")
        if source_id not in {configured.id for configured in engine.sources if configured.enabled}:
            return False
        if source.get("status") != "PASS" or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return False
        raw = engine.data_dir / "raw" / f"{source_id}_{digest[:12]}.xml"
        if not raw.is_file() or raw.is_symlink() or hashlib.sha256(raw.read_bytes()).hexdigest() != digest:
            return False
    return all(isinstance(item, dict) and item.get("title") and item.get("source_id") for item in items)


def preserve_snapshot(storage, snapshot) -> None:
    identifier = str(snapshot.get("snapshot_id") or "")
    if not identifier or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("snapshot archive identity invalid")
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope = {"schema": "head-intelligence-snapshot-recovery-v1", "sha256": hashlib.sha256(canonical).hexdigest(), "snapshot": snapshot}
    name = f"snapshots/{identifier}.json"
    existing = storage.read_json(name)
    if existing is not None and existing != envelope:
        raise RuntimeError("immutable recovery snapshot already exists with different bytes")
    if existing is None:
        storage.save_json_atomic(name, envelope)


def repair_data(engine, *, main_exe: Path, updater_exe: Path | None = None) -> dict:
    root = engine.data_dir
    checks = {}
    actions = []
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "raw").mkdir(exist_ok=True)
        engine.storage.save_json_atomic("repair_probe.json", {"probe": "head-repair-storage"})
        database_ok = engine.storage.read_json("repair_probe.json") == {"probe": "head-repair-storage"}
    except Exception as exc:
        database_ok = False
        actions.append(f"storage failure: {type(exc).__name__}: {exc}")
    checks["database"] = {"status": "PASS" if database_ok else "FAIL", "implementation": "atomic JSON/raw-file persistence"}

    latest = root / SNAPSHOT_FILE
    snapshot = engine.storage.read_json(SNAPSHOT_FILE)
    has_user_data = latest.exists() or bool(list((root / "snapshots").glob("*.json")))
    valid = validate_snapshot(engine, snapshot) if latest.exists() else not has_user_data
    if not valid:
        candidates = []
        for path in (root / "snapshots").glob("*.json"):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                candidate = envelope["snapshot"]
                canonical = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if envelope.get("schema") != "head-intelligence-snapshot-recovery-v1" or hashlib.sha256(canonical).hexdigest() != envelope.get("sha256"):
                    continue
                if validate_snapshot(engine, candidate):
                    candidates.append(candidate)
            except Exception:
                continue
        if candidates:
            selected = max(candidates, key=lambda value: str(value.get("generated_at") or ""))
            if latest.exists():
                engine.storage._atomic_write_bytes(root / "repair_backups" / (hashlib.sha256(latest.read_bytes()).hexdigest() + ".json"), latest.read_bytes())
            engine.storage.save_json_atomic(SNAPSHOT_FILE, selected)
            snapshot = selected
            valid = validate_snapshot(engine, selected)
            actions.append("RESTORED_VERIFIED_SNAPSHOT")

    checks["index"] = {"status": "PASS" if valid else "FAIL", "implementation": SNAPSHOT_FILE, "empty_initial_state": not has_user_data}
    checks["missing_files"] = {"status": "PASS" if valid and (root / "raw").is_dir() else "FAIL", "detail": "missing raw user evidence cannot be synthesized"}
    cache = root / "cache"
    cache_ok = not cache.exists() or cache.is_dir() and not cache.is_symlink()
    checks["cache"] = {"status": "PASS" if cache_ok else "FAIL", "detail": "no user raw/snapshot/archive files are deleted"}
    source_urls = [url for source in engine.sources if source.enabled for url in [source.url, *source.fallback_urls]]
    checks["configuration"] = {"status": "PASS" if source_urls and all(urlsplit(url).scheme == "https" for url in source_urls) else "FAIL", "detail": "production source configuration retained"}
    environment = software_update_environment_status(main_exe=main_exe, current_version=APP_VERSION, updater_exe=updater_exe)
    checks["network_configuration"] = environment["checks"]["release_config"]
    checks["version"] = environment["checks"]["version_contract"]
    checks["data_integrity"] = {"status": "PASS" if valid else "FAIL", "snapshot_id": snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None}
    local_states = [value["status"] for key, value in checks.items() if key != "network_configuration"]
    status = "FAIL" if "FAIL" in local_states else ("BLOCKED" if checks["network_configuration"]["status"] != "PASS" else "PASS")
    report = {"schema": "head-intelligence-repair-v1", "status": status, "local_integrity_status": "PASS" if "FAIL" not in local_states else "FAIL", "data_dir": str(root), "checks": checks, "actions": actions, "software_update_environment": environment}
    engine.storage.save_json_atomic("repair_evidence.json", report)
    return report
