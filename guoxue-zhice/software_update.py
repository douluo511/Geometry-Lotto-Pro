from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

UPDATE_CONFIG_FILENAME = "Guoxue_Zhice_Update_Config.json"
UPDATER_EXE_FILENAME = "Guoxue_Zhice_Updater.exe"


def _trusted_https(url: str, trusted_hosts: set[str]) -> bool:
    parsed = urlsplit(str(url))
    return parsed.scheme.lower() == "https" and parsed.hostname in trusted_hosts


def _load_release_config(main_exe: Path) -> dict[str, Any]:
    path = Path(main_exe).resolve().with_name(UPDATE_CONFIG_FILENAME)
    if not path.is_file():
        raise RuntimeError(
            "real software-update release config is unavailable; "
            "independent repository/release source remains BLOCKED"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError("software-update release config is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != "guoxue-software-update-config-v1":
        raise RuntimeError("software-update release config schema invalid")
    manifest_url = str(value.get("manifest_url") or "")
    trusted_hosts = {
        str(host).strip().lower()
        for host in (value.get("trusted_hosts") or [])
        if str(host).strip()
    }
    if not trusted_hosts or not _trusted_https(manifest_url, trusted_hosts):
        raise RuntimeError("software-update manifest is not trusted HTTPS")
    return {
        "manifest_url": manifest_url,
        "trusted_hosts": sorted(trusted_hosts),
        "config_path": str(path),
    }


def software_update_environment_status(
    *,
    main_exe: Path,
    current_version: str,
    updater_exe: Path | None = None,
) -> dict[str, Any]:
    main_exe = Path(main_exe).resolve()
    updater_exe = Path(updater_exe).resolve() if updater_exe else main_exe.with_name(UPDATER_EXE_FILENAME)
    version_parts = str(current_version).strip().split(".")
    checks: dict[str, dict[str, Any]] = {
        "version_contract": {
            "status": "PASS" if version_parts and all(x.isdigit() for x in version_parts) else "FAIL",
            "current_version": str(current_version),
        },
        "main_exe": {"status": "PASS" if main_exe.is_file() else "BLOCKED", "path": str(main_exe)},
        "updater_exe": {"status": "PASS" if updater_exe.is_file() else "BLOCKED", "path": str(updater_exe)},
    }
    try:
        release = _load_release_config(main_exe)
        checks["release_config"] = {
            "status": "PASS",
            "config_path": release["config_path"],
            "manifest_url": release["manifest_url"],
            "trusted_hosts": release["trusted_hosts"],
        }
    except Exception as exc:
        checks["release_config"] = {"status": "BLOCKED", "detail": f"{type(exc).__name__}: {exc}"}

    states = [str(x.get("status")) for x in checks.values()]
    status = "FAIL" if "FAIL" in states else ("BLOCKED" if "BLOCKED" in states else "PASS")
    return {"schema": "guoxue-software-update-environment-v1", "status": status, "checks": checks}


def launch_independent_updater(
    *,
    data_root: Path,
    current_version: str,
    main_exe: Path | None = None,
    updater_exe: Path | None = None,
    parent_pid: int | None = None,
) -> dict[str, Any]:
    if main_exe is None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("software update requires the packaged Windows main EXE")
        main_exe = Path(sys.executable)
    main_exe = Path(main_exe).resolve()
    if not main_exe.is_file():
        raise FileNotFoundError(f"main EXE not found: {main_exe}")

    updater_exe = Path(updater_exe).resolve() if updater_exe else main_exe.with_name(UPDATER_EXE_FILENAME)
    if not updater_exe.is_file():
        raise RuntimeError(f"independent Updater EXE unavailable: {updater_exe}")

    release = _load_release_config(main_exe)
    evidence = Path(data_root).resolve() / "software_update_transaction.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    args = [
        str(updater_exe),
        "--manifest-url", release["manifest_url"],
        "--target-exe", str(main_exe),
        "--current-version", str(current_version),
        "--parent-pid", str(parent_pid if parent_pid is not None else os.getpid()),
        "--evidence-file", str(evidence),
    ]
    for host in release["trusted_hosts"]:
        args.extend(["--trusted-host", host])

    proc = subprocess.Popen(
        args,
        cwd=str(main_exe.parent),
        close_fds=True,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    return {
        "status": "PASS",
        "operation": "software_update",
        "action": "UPDATER_HANDOFF",
        "updater_pid": int(proc.pid),
        "target_exe": str(main_exe),
        "updater_exe": str(updater_exe),
        "release_config": release["config_path"],
        "evidence_file": str(evidence),
        "requires_parent_exit": True,
    }
