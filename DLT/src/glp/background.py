from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .constants import (
    APP_VERSION,
    BACKGROUND_POLL_SECONDS,
    BACKGROUND_STARTUP_MODE,
    DEFAULT_RESEARCH_DAN_FRONT_COUNT,
    DEFAULT_RESEARCH_DAN_BACK_COUNT,
)
from .service import LottoService
from .util import atomic_json, next_issue, sha256_bytes, sha256_json, utc_now


BACKGROUND_SCHEMA = "dlt-background-worker-v1"


def _exe_sha256() -> str:
    try:
        path = Path(sys.executable)
        return sha256_bytes(path.read_bytes()) if path.is_file() else ""
    except Exception:
        return ""


def _status_path(root: Path) -> Path:
    return root / "background_status.json"


def _mutex_name(root: Path) -> str:
    digest = hashlib.sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest()[:20]
    return f"Local\\GeometryLottoProDLTBackground-{digest}"


class _WindowsMutex:
    def __init__(self, root: Path):
        self.handle = None
        self.already_exists = False
        if os.name != "nt":
            return
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, 0, _mutex_name(root))
        if not handle:
            raise ctypes.WinError()
        self.handle = handle
        self.already_exists = int(kernel32.GetLastError()) == 183
        self._kernel32 = kernel32

    def close(self) -> None:
        if self.handle is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _load_current_latest(service: LottoService) -> str | None:
    try:
        draws, _ = service.store.load_draws()
    except Exception:
        return None
    return draws[-1].issue if draws else None


def background_cycle(service: LottoService | None = None) -> dict[str, Any]:
    """
    One fail-closed background cycle.

    Always performs a fresh official update. The update path already replays settled
    Freezes. A new prediction is created only when the currently expected target issue
    has no immutable Freeze yet, so repeated 30-minute checks do not overwrite or
    manufacture duplicate predictions.
    """
    service = service or LottoService()
    before_latest = _load_current_latest(service)
    update = service.update()
    if update.get("network_gate") != "PASS" or update.get("crosscheck_status") != "PASS":
        raise RuntimeError("background official update did not PASS")

    draws, canonical_hash = service.store.load_draws()
    latest = draws[-1]
    target_issue = next_issue(latest.issue, latest.draw_date)
    existing = {p.target_issue: p for p in service.store.freezes()}
    prediction: dict[str, Any] | None = None
    created = False
    if target_issue not in existing:
        prediction = service.predict()["prediction"]
        created = True
    else:
        prediction = existing[target_issue].to_dict()

    if len(prediction.get("research_dan_front") or []) not in {
        1,
        DEFAULT_RESEARCH_DAN_FRONT_COUNT,
    }:
        raise RuntimeError("background freeze has unsupported front research-dan length")

    result = {
        "schema": "dlt-background-cycle-v1",
        "status": "PASS",
        "completed_at": utc_now(),
        "before_latest_issue": before_latest,
        "latest_issue": latest.issue,
        "new_official_issue_detected": bool(before_latest and latest.issue != before_latest),
        "matched_replays": int(update.get("replayed", 0) or 0),
        "target_issue": target_issue,
        "prediction_created": created,
        "prediction_id": prediction.get("prediction_id"),
        "freeze_hash": prediction.get("freeze_hash"),
        "research_dan_front": list(prediction.get("research_dan_front") or []),
        "research_dan_back": list(prediction.get("research_dan_back") or []),
        "canonical_hash": canonical_hash,
        "network_gate": update.get("network_gate"),
        "crosscheck_status": update.get("crosscheck_status"),
        "production_edge_state": prediction.get("edge_state"),
        "production_dan_state": prediction.get("dan_state"),
    }
    service.store.append_experiment(
        "background_cycle",
        "PASS",
        canonical_hash,
        APP_VERSION,
        result,
    )
    return result


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_parent_exit(pid: int, timeout_seconds: int = 30) -> bool:
    if pid <= 0:
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.1)
    return not _process_exists(pid)


def run_background_worker(
    *,
    interval_seconds: int = BACKGROUND_POLL_SECONDS,
    max_cycles: int = 0,
    wait_parent_pid: int = 0,
) -> int:
    if interval_seconds <= 0:
        raise ValueError("background interval must be positive")
    service = LottoService()
    root = service.store.root
    status_path = _status_path(root)

    with _WindowsMutex(root) as mutex:
        if os.name == "nt" and mutex.already_exists:
            atomic_json(status_path, {
                "schema": BACKGROUND_SCHEMA,
                "status": "ALREADY_RUNNING",
                "pid": os.getpid(),
                "updated_at": utc_now(),
                "interval_seconds": interval_seconds,
                "startup_mode": BACKGROUND_STARTUP_MODE,
            })
            return 0

        parent_exit_observed = _wait_parent_exit(wait_parent_pid) if wait_parent_pid else None
        started = {
            "schema": BACKGROUND_SCHEMA,
            "status": "RUNNING",
            "pid": os.getpid(),
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "interval_seconds": interval_seconds,
            "cycle_count": 0,
            "startup_mode": BACKGROUND_STARTUP_MODE,
            "autostart_registered": False,
            "parent_pid": wait_parent_pid or None,
            "parent_exit_observed": parent_exit_observed,
            "exe_sha256": _exe_sha256(),
            "default_research_dan_front_count": DEFAULT_RESEARCH_DAN_FRONT_COUNT,
            "default_research_dan_back_count": DEFAULT_RESEARCH_DAN_BACK_COUNT,
        }
        atomic_json(status_path, started)

        cycle_count = 0
        while True:
            cycle_count += 1
            try:
                cycle = background_cycle(service)
                state = {
                    **started,
                    "status": "PASS",
                    "updated_at": utc_now(),
                    "cycle_count": cycle_count,
                    "last_cycle": cycle,
                    "last_error": None,
                }
            except Exception as exc:
                state = {
                    **started,
                    "status": "FAIL",
                    "updated_at": utc_now(),
                    "cycle_count": cycle_count,
                    "last_cycle": None,
                    "last_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
                try:
                    service.store.append_experiment(
                        "background_cycle",
                        "FAIL",
                        sha256_json(state["last_error"]),
                        APP_VERSION,
                        state,
                    )
                except Exception:
                    pass
            atomic_json(status_path, state)

            if max_cycles and cycle_count >= max_cycles:
                state["worker_exit"] = "MAX_CYCLES_REACHED"
                state["updated_at"] = utc_now()
                atomic_json(status_path, state)
                return 0

            time.sleep(interval_seconds)


def launch_background_worker(
    *,
    interval_seconds: int = BACKGROUND_POLL_SECONDS,
    max_cycles: int = 0,
    wait_parent_exit: bool = False,
) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("background worker launch requires Windows")

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--background-worker"]
    else:
        main_py = Path(__file__).resolve().parents[1] / "main.py"
        cmd = [sys.executable, str(main_py), "--background-worker"]

    cmd += ["--background-interval-seconds", str(int(interval_seconds))]
    if max_cycles:
        cmd += ["--background-max-cycles", str(int(max_cycles))]
    if wait_parent_exit:
        cmd += ["--background-wait-parent-pid", str(os.getpid())]

    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
        shell=False,
    )
    return {
        "schema": "dlt-background-launch-v1",
        "status": "PASS",
        "launched_at": utc_now(),
        "child_pid": int(proc.pid),
        "parent_pid": os.getpid(),
        "interval_seconds": int(interval_seconds),
        "max_cycles": int(max_cycles),
        "wait_parent_exit": bool(wait_parent_exit),
        "startup_mode": BACKGROUND_STARTUP_MODE,
        "autostart_registered": False,
        "shell": False,
        "exe_sha256": _exe_sha256(),
    }
