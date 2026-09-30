from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .util import app_data_dir, atomic_json, atomic_write, sha256_json


BUNDLE_DIR = "updater_bundle"
MANIFEST_NAME = "updater_manifest.json"
LAST_RUN_NAME = "updater_last_run.json"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


class UpdaterClient:
    def __init__(self, data_root: Path | None = None):
        self.data_root = (data_root or app_data_dir()).resolve()

    def _bundle(self) -> tuple[Path, dict[str, Any]]:
        root = _resource_root() / BUNDLE_DIR
        manifest_path = root / MANIFEST_NAME
        if not manifest_path.is_file():
            raise RuntimeError("embedded updater manifest missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("schema") != "ssq-updater-bundle-v1":
            raise RuntimeError("embedded updater manifest schema mismatch")
        filename = str(manifest.get("filename") or "")
        digest = str(manifest.get("sha256") or "")
        if not filename or len(digest) != 64:
            raise RuntimeError("embedded updater manifest incomplete")
        bundled = root / filename
        if not bundled.is_file() or _sha256_file(bundled) != digest:
            raise RuntimeError("embedded updater bytes fail SHA256 verification")
        return bundled, manifest

    def bundle_integrity(self) -> dict[str, Any]:
        try:
            bundled, manifest = self._bundle()
            return {
                "status": "PASS",
                "filename": bundled.name,
                "sha256": manifest["sha256"],
                "bytes": bundled.stat().st_size,
                "manifest_sha256": sha256_json(manifest),
            }
        except Exception as exc:
            return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}

    def _materialize(self) -> tuple[Path, dict[str, Any]]:
        bundled, manifest = self._bundle()
        digest = manifest["sha256"]
        target = self.data_root / "updater" / digest / bundled.name
        if not target.is_file() or _sha256_file(target) != digest:
            atomic_write(target, bundled.read_bytes())
        if _sha256_file(target) != digest:
            raise RuntimeError("materialized updater failed SHA256 read-back")
        return target, manifest

    def _run(self, mode: str, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        updater, manifest = self._materialize()
        runs = self.data_root / "updater_runs"
        runs.mkdir(parents=True, exist_ok=True)
        result_path = runs / f"{uuid4().hex}.json"
        if progress:
            progress(f"启动独立 Updater 进程：{mode}")

        env = os.environ.copy()
        env["GLP_DATA_DIR"] = str(self.data_root)
        env["GLP_UPDATER_PARENT_PID"] = str(os.getpid())
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.run(
            [str(updater), "--mode", mode, "--result-file", str(result_path)],
            env=env,
            timeout=1800,
            creationflags=creationflags,
        )
        if not result_path.is_file():
            raise RuntimeError("updater process returned without machine result")
        report = json.loads(result_path.read_text(encoding="utf-8-sig"))
        expected_hash = manifest["sha256"]
        valid = (
            proc.returncode == 0
            and report.get("status") == "PASS"
            and report.get("mode") == mode
            and report.get("updater_exe_sha256") == expected_hash
            and report.get("parent_pid_match") is True
            and int(report.get("pid") or 0) != os.getpid()
            and int(report.get("parent_pid") or 0) == os.getpid()
            and Path(str(report.get("data_dir") or "")).resolve() == self.data_root
        )
        if not valid:
            raise RuntimeError("independent updater process evidence failed validation")

        atomic_json(self.data_root / LAST_RUN_NAME, report)
        service_result = report.get("service_result")
        if not isinstance(service_result, dict):
            raise RuntimeError("updater service result missing")
        enriched = dict(service_result)
        enriched["updater_process"] = {
            "status": "PASS",
            "pid": report["pid"],
            "parent_pid": report["parent_pid"],
            "exe_sha256": expected_hash,
            "mode": mode,
            "result_sha256": report.get("service_result_sha256"),
        }
        return enriched

    def update(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        return self._run("update", progress)

    def repair(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        return self._run("repair", progress)
