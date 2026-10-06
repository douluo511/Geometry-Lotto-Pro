from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .constants import APP_VERSION
from .sources import build_canonical
from .storage import Store
from .util import app_data_dir, atomic_json, atomic_write, sha256_bytes, utc_now


UPDATER_NAME = "Geometry_Lotto_Pro_DLT_Updater.exe"
MAIN_NAME = "Geometry_Lotto_Pro_DLT.exe"
UPDATER_SCHEMA = "dlt-independent-updater-v1"
EVIDENCE_EXPORT_SCHEMA = "dlt-evidence-export-v1"
BACKUP_SCHEMA = "dlt-data-backup-v1"


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


class UpdaterClient:
    """Main-process client for the independent updater process."""

    def __init__(
        self,
        updater_path: Path | None = None,
        data_dir: Path | None = None,
        result_dir: Path | None = None,
    ):
        self.data_dir = (data_dir or app_data_dir()).resolve()
        self.result_dir = (result_dir or (self.data_dir / "updater_results")).resolve()
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.updater_path = updater_path.resolve() if updater_path else self._default_updater_path()

    @staticmethod
    def _default_updater_path() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().with_name(UPDATER_NAME)
        return (Path(__file__).resolve().parents[1] / "updater.py").resolve()

    def _command_prefix(self) -> list[str]:
        if getattr(sys, "frozen", False):
            if not self.updater_path.is_file():
                raise FileNotFoundError(f"独立 Updater 不存在: {self.updater_path}")
            return [str(self.updater_path)]
        if not self.updater_path.is_file():
            raise FileNotFoundError(f"Updater source 不存在: {self.updater_path}")
        return [sys.executable, str(self.updater_path)]

    def _run(
        self,
        mode: str,
        *,
        extra: list[str] | None = None,
        timeout: int = 2400,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        token = uuid.uuid4().hex
        result_file = self.result_dir / f"{mode.strip('-')}-{token}.json"
        command = [*self._command_prefix(), mode, "--result-file", str(result_file), *(extra or [])]
        env = dict(os.environ)
        env["GLP_DATA_DIR"] = str(self.data_dir)
        env["GLP_UPDATER_PARENT_PID"] = str(os.getpid())
        if progress:
            progress(f"独立 Updater 正在执行 {mode}")
        proc = subprocess.run(
            command,
            env=env,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if not result_file.is_file():
            raise RuntimeError(
                f"独立 Updater 未生成结果文件；exit={proc.returncode}; stderr={proc.stderr[-1000:]}"
            )
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if result.get("schema") != UPDATER_SCHEMA:
            raise RuntimeError("Updater schema 不匹配")
        if getattr(sys, "frozen", False):
            expected = _sha256_file(self.updater_path)
            if result.get("updater_exe_sha256") != expected:
                raise RuntimeError("Updater 结果未绑定当前 Exact Updater EXE")
            if result.get("parent_pid_match") is not True:
                raise RuntimeError("Updater 未证明独立子进程边界")
        if proc.returncode != 0 or result.get("status") != "PASS":
            raise RuntimeError(
                f"独立 Updater {mode} FAIL: {result.get('error') or result.get('error_type') or proc.stderr[-1000:]}"
            )
        if progress:
            progress(f"独立 Updater {mode}：PASS")
        return result

    def update(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        result = self._run("--data-update", progress=progress)
        value = result.get("service_result")
        if not isinstance(value, dict) or value.get("network_gate") != "PASS" or value.get("crosscheck_status") != "PASS":
            raise RuntimeError("Updater update 未返回真实官方联网 PASS")
        value = dict(value)
        value["_updater"] = {
            "schema": result.get("schema"),
            "pid": result.get("pid"),
            "parent_pid_match": result.get("parent_pid_match"),
            "updater_exe_sha256": result.get("updater_exe_sha256"),
            "github_sha": result.get("github_sha"),
            "github_run_id": result.get("github_run_id"),
        }
        return value

    def repair(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        result = self._run("--data-repair", progress=progress)
        value = result.get("service_result")
        if not isinstance(value, dict) or value.get("after", {}).get("status") != "PASS":
            raise RuntimeError("Updater repair 未恢复完整性")
        value = dict(value)
        value["_updater"] = {
            "schema": result.get("schema"),
            "pid": result.get("pid"),
            "parent_pid_match": result.get("parent_pid_match"),
            "updater_exe_sha256": result.get("updater_exe_sha256"),
            "github_sha": result.get("github_sha"),
            "github_run_id": result.get("github_run_id"),
        }
        return value

    def software_update(
        self,
        manifest_url: str,
        target_exe: Path | None = None,
        *,
        current_version: str = APP_VERSION,
        timeout: int = 2400,
    ) -> dict[str, Any]:
        target = (target_exe or Path(sys.executable)).resolve()
        result = self._run(
            "--software-update",
            extra=[
                "--manifest-url", manifest_url,
                "--target-exe", str(target),
                "--current-version", current_version,
            ],
            timeout=timeout,
        )
        value = result.get("service_result")
        if not isinstance(value, dict) or value.get("status") != "PASS":
            raise RuntimeError("软件升级没有完成 PASS")
        return value


def launch_software_update(
    manifest_url: str,
    target_exe: Path | None = None,
    *,
    current_version: str = APP_VERSION,
    updater_path: Path | None = None,
) -> dict[str, Any]:
    """Launch the independent updater and return immediately so the main EXE can exit."""
    client = UpdaterClient(updater_path=updater_path)
    target = (target_exe or Path(sys.executable)).resolve()
    result_file = client.result_dir / "software_update_result.json"
    result_file.unlink(missing_ok=True)
    command = [
        *client._command_prefix(),
        "--software-update",
        "--result-file", str(result_file),
        "--manifest-url", manifest_url,
        "--target-exe", str(target),
        "--current-version", current_version,
        "--wait-parent-pid", str(os.getpid()),
    ]
    env = dict(os.environ)
    env["GLP_DATA_DIR"] = str(client.data_dir)
    env["GLP_UPDATER_PARENT_PID"] = str(os.getpid())
    proc = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return {
        "status": "LAUNCHED",
        "pid": proc.pid,
        "result_file": str(result_file),
        "target_exe": str(target),
        "updater": str(client.updater_path),
    }


def read_software_update_result(result_file: Path | None = None) -> dict[str, Any] | None:
    path = (result_file or (app_data_dir() / "updater_results" / "software_update_result.json")).resolve()
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != UPDATER_SCHEMA:
        raise ValueError("软件升级结果 schema 不匹配")
    return value


def create_backup(
    root: Path | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    store = Store(root)
    integrity = store.integrity_check()
    if integrity.get("status") != "PASS":
        raise ValueError("拒绝备份：当前 Store 完整性不是 PASS")
    dest = (destination or (store.root / "backups" / ("backup-" + utc_now().replace(":", "").replace("-", "")))).resolve()
    if dest.exists():
        raise FileExistsError(f"备份目录已存在: {dest}")
    dest.mkdir(parents=True)
    files: list[dict[str, Any]] = []

    for source in (store.history_path, store.evidence_path, store.freeze_archive_path):
        if not source.is_file():
            raise FileNotFoundError(f"备份必需文件缺失: {source.name}")
        target = dest / source.name
        shutil.copy2(source, target)
        files.append({"name": source.name, "bytes": target.stat().st_size, "sha256": _sha256_file(target)})

    ledger = dest / store.db_path.name
    src_db = sqlite3.connect(store.db_path)
    dst_db = sqlite3.connect(ledger)
    try:
        src_db.backup(dst_db)
    finally:
        dst_db.close()
        src_db.close()
    files.append({"name": ledger.name, "bytes": ledger.stat().st_size, "sha256": _sha256_file(ledger)})

    raw = store.validate_raw_evidence()
    manifest = {
        "schema": BACKUP_SCHEMA,
        "status": "PASS",
        "created_at": utc_now(),
        "source_root": str(store.root),
        "integrity": integrity,
        "raw_evidence": {
            "status": raw.get("status"),
            "raw_response_count": raw.get("raw_response_count"),
        },
        "files": sorted(files, key=lambda x: x["name"]),
    }
    atomic_json(dest / "manifest.json", manifest)
    return {"status": "PASS", "backup_dir": str(dest), "manifest": manifest}


def _verify_manifest_directory(path: Path, schema: str) -> dict[str, Any]:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("manifest.json missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != schema or manifest.get("status") != "PASS":
        raise ValueError("manifest schema/status mismatch")
    checked: list[dict[str, Any]] = []
    for row in manifest.get("files", []):
        name = str(row.get("name", ""))
        if not name or Path(name).name != name:
            raise ValueError("unsafe manifest file name")
        target = path / name
        if not target.is_file():
            raise FileNotFoundError(f"export file missing: {name}")
        actual_size = target.stat().st_size
        actual_hash = _sha256_file(target)
        ok = actual_size == int(row.get("bytes", -1)) and actual_hash == str(row.get("sha256", "")).lower()
        checked.append({"name": name, "status": "PASS" if ok else "FAIL", "sha256": actual_hash, "bytes": actual_size})
    if not checked or any(x["status"] != "PASS" for x in checked):
        raise ValueError("manifest file verification failed")
    return {"status": "PASS", "manifest": manifest, "files": checked}


def restore_backup(backup_dir: Path, root: Path | None = None) -> dict[str, Any]:
    source = backup_dir.resolve()
    verified = _verify_manifest_directory(source, BACKUP_SCHEMA)
    target_store = Store(root)
    names = [str(x["name"]) for x in verified["manifest"]["files"]]
    required = {"canonical_history.json", "source_evidence.json", "freeze_archive.json", "ledger.sqlite3"}
    if set(names) != required:
        raise ValueError(f"备份文件集合不完整: {sorted(names)}")

    with tempfile.TemporaryDirectory(prefix="dlt-restore-verify-") as td:
        staged = Path(td)
        for name in names:
            shutil.copy2(source / name, staged / name)
        candidate = Store(staged)
        candidate_integrity = candidate.integrity_check()
        if candidate_integrity.get("status") != "PASS":
            raise ValueError("备份内容无法通过独立完整性重验")

    previous: dict[str, bytes | None] = {}
    target_paths = {name: target_store.root / name for name in names}
    try:
        for name, path in target_paths.items():
            previous[name] = path.read_bytes() if path.exists() else None
            atomic_write(path, (source / name).read_bytes())
        for suffix in ("-wal", "-shm"):
            Path(str(target_store.db_path) + suffix).unlink(missing_ok=True)
        final = Store(target_store.root).integrity_check()
        if final.get("status") != "PASS":
            raise RuntimeError("恢复后完整性不是 PASS")
    except Exception:
        for name, path in target_paths.items():
            old = previous.get(name)
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old)
        raise
    return {
        "status": "PASS",
        "restored_to": str(target_store.root),
        "integrity": final,
        "backup_manifest": verified["manifest"],
    }


def export_evidence(
    root: Path | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    store = Store(root)
    integrity = store.integrity_check()
    raw = store.validate_raw_evidence()
    if integrity.get("status") != "PASS":
        raise ValueError("Evidence 导出拒绝：Store 完整性不是 PASS")
    dest = (destination or (store.root / "exports" / ("evidence-" + uuid.uuid4().hex))).resolve()
    if dest.exists():
        raise FileExistsError(f"Evidence 导出目录已存在: {dest}")
    dest.mkdir(parents=True)
    source_files = (store.history_path, store.evidence_path, store.db_path, store.freeze_archive_path)
    files: list[dict[str, Any]] = []
    for source in source_files:
        if not source.is_file():
            raise FileNotFoundError(f"Evidence 文件缺失: {source.name}")
        target = dest / source.name
        if source == store.db_path:
            src_db = sqlite3.connect(source)
            dst_db = sqlite3.connect(target)
            try:
                src_db.backup(dst_db)
            finally:
                dst_db.close()
                src_db.close()
        else:
            shutil.copy2(source, target)
        files.append({"name": source.name, "bytes": target.stat().st_size, "sha256": _sha256_file(target)})
    manifest = {
        "schema": EVIDENCE_EXPORT_SCHEMA,
        "status": "PASS",
        "exported_at": utc_now(),
        "files": sorted(files, key=lambda x: x["name"]),
        "integrity_status": integrity.get("status"),
        "raw_evidence_status": raw.get("status"),
        "raw_response_count": raw.get("raw_response_count"),
    }
    atomic_json(dest / "manifest.json", manifest)
    verified = verify_export(dest)
    return {"status": "PASS", "export_dir": str(dest), "manifest": manifest, "verification": verified}


def verify_export(export_dir: Path) -> dict[str, Any]:
    path = export_dir.resolve()
    verified = _verify_manifest_directory(path, EVIDENCE_EXPORT_SCHEMA)
    with tempfile.TemporaryDirectory(prefix="dlt-export-verify-") as td:
        temp = Path(td)
        for row in verified["manifest"]["files"]:
            shutil.copy2(path / row["name"], temp / row["name"])
        store = Store(temp)
        integrity = store.integrity_check()
        raw = store.validate_raw_evidence()
    if integrity.get("status") != "PASS":
        raise ValueError("导出重验的 Store 完整性不是 PASS")
    return {
        "status": "PASS",
        "files": verified["files"],
        "integrity": integrity,
        "raw_evidence": {
            "status": raw.get("status"),
            "raw_response_count": raw.get("raw_response_count"),
        },
    }


def source_health(progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Perform a fresh official-source retrieval without mutating the user's Store."""
    dataset, evidence = build_canonical(progress)
    with tempfile.TemporaryDirectory(prefix="dlt-source-health-") as td:
        store = Store(Path(td))
        store.save_dataset(dataset, evidence)
        raw = store.validate_raw_evidence()
        integrity = store.integrity_check()
    ok = (
        evidence.get("network_gate") == "PASS"
        and evidence.get("crosscheck_status") == "PASS"
        and integrity.get("status") == "PASS"
        and raw.get("status") == "PASS"
    )
    if not ok:
        raise RuntimeError("来源健康检查未达到真实联网/RAW/完整性全 PASS")
    return {
        "status": "PASS",
        "checked_at": utc_now(),
        "latest": dataset.draws[-1].to_dict(),
        "draw_count": len(dataset.draws),
        "canonical_hash": dataset.canonical_hash,
        "source_receipts": evidence.get("source_receipts", []),
        "raw_response_count": raw.get("raw_response_count"),
    }
