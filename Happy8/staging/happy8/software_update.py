from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

UPDATE_CONFIG_FILENAME = "Happy8_Update_Config.json"
UPDATER_EXE_FILENAME = "Geometry_Lotto_Pro_Happy8_Updater.exe"


def _trusted_https(url: str, trusted_hosts: set[str]) -> bool:
    parsed = urlsplit(str(url))
    return parsed.scheme.lower() == "https" and parsed.hostname in trusted_hosts


def _load_release_config(main_exe: Path) -> dict[str, Any]:
    path = main_exe.with_name(UPDATE_CONFIG_FILENAME)
    if not path.exists():
        raise RuntimeError(
            "real software-update release config is unavailable; "
            "independent repository/release source remains BLOCKED"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError("software-update release config is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != "happy8-update-config-v1":
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


def launch_independent_updater(
    *,
    data_root: Path,
    current_version: str,
    main_exe: Path | None = None,
    updater_exe: Path | None = None,
    parent_pid: int | None = None,
) -> dict[str, Any]:
    """Start the sibling Updater process; never perform replacement in-process.

    The main application only hands off the transaction. The Updater waits for
    the parent process to exit, then performs download/hash/backup/atomic
    replace/self-test/commit-or-rollback and writes its own evidence file.
    """
    if main_exe is None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("software update requires the packaged Windows main EXE")
        main_exe = Path(sys.executable)
    main_exe = Path(main_exe).resolve()
    if not main_exe.exists() or not main_exe.is_file():
        raise FileNotFoundError(f"main EXE not found: {main_exe}")

    if updater_exe is None:
        updater_exe = main_exe.with_name(UPDATER_EXE_FILENAME)
    updater_exe = Path(updater_exe).resolve()
    if not updater_exe.exists() or not updater_exe.is_file():
        raise RuntimeError(f"independent Updater EXE unavailable: {updater_exe}")

    release = _load_release_config(main_exe)
    evidence = Path(data_root).resolve() / "evidence" / "software_update_transaction.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)

    args = [
        str(updater_exe),
        "--manifest-url",
        release["manifest_url"],
        "--target-exe",
        str(main_exe),
        "--current-version",
        str(current_version),
        "--parent-pid",
        str(parent_pid if parent_pid is not None else os.getpid()),
        "--evidence-file",
        str(evidence),
    ]
    for host in release["trusted_hosts"]:
        args.extend(["--trusted-host", host])

    process = subprocess.Popen(
        args,
        cwd=str(main_exe.parent),
        close_fds=True,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    return {
        "status": "PASS",
        "operation": "software_update",
        "action": "UPDATER_HANDOFF",
        "updater_pid": int(process.pid),
        "target_exe": str(main_exe),
        "updater_exe": str(updater_exe),
        "release_config": release["config_path"],
        "evidence_file": str(evidence),
        "requires_parent_exit": True,
    }
