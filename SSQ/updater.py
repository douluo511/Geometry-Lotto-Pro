from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from glp.service import LottoService
from glp.storage import Store
from glp.util import app_data_dir, atomic_json, sha256_bytes, sha256_json


SCHEMA = "ssq-independent-updater-v1"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _metadata(mode: str, root: Path) -> dict[str, Any]:
    exe = Path(sys.executable).resolve()
    expected_parent = int(os.environ.get("GLP_UPDATER_PARENT_PID", "0") or 0)
    actual_parent = int(os.getppid())
    return {
        "schema": SCHEMA,
        "mode": mode,
        "pid": int(os.getpid()),
        "parent_pid": actual_parent,
        "expected_parent_pid": expected_parent,
        "parent_pid_match": bool(expected_parent and actual_parent == expected_parent),
        "data_dir": str(root.resolve()),
        "updater_exe": str(exe),
        "updater_exe_sha256": _file_sha256(exe) if exe.is_file() else "",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    }


def _offline_failclosed() -> dict[str, Any]:
    import glp.sources as sources

    with tempfile.TemporaryDirectory(prefix="ssq-updater-fault-") as td:
        root = Path(td)
        svc = LottoService(Store(root))
        svc.ensure_seed()
        before = svc.store.history_path.read_bytes()
        before_hash = sha256_bytes(before)
        original_get = sources.NET.get

        def offline(*args, **kwargs):
            raise ConnectionError("updater acceptance injected offline")

        sources.NET.get = offline
        rejected = False
        error = ""
        try:
            svc.update()
        except Exception as exc:
            rejected = True
            error = f"{type(exc).__name__}: {exc}"
        finally:
            sources.NET.get = original_get

        after = svc.store.history_path.read_bytes()
        after_hash = sha256_bytes(after)
        unchanged = before == after and before_hash == after_hash
        integrity = svc.store.baseline_integrity_check()
        status = "PASS" if rejected and unchanged and integrity.get("ok") is True else "FAIL"
        return {
            "status": status,
            "update_rejected": rejected,
            "history_unchanged": unchanged,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "integrity": integrity,
            "error": error,
        }


def _run(mode: str, root: Path) -> tuple[str, dict[str, Any]]:
    svc = LottoService(Store(root))
    if mode == "self-test":
        result = svc.self_test()
        return ("PASS" if result.get("status") == "PASS" else "FAIL"), result
    if mode == "update":
        result = svc.update()
        ok = (
            result.get("crosscheck_status") == "PASS"
            and isinstance(result.get("persisted_integrity"), dict)
            and result["persisted_integrity"].get("ok") is True
            and bool(result.get("canonical_hash"))
        )
        return ("PASS" if ok else "FAIL"), result
    if mode == "repair":
        result = svc.repair()
        return ("PASS" if result.get("status") == "PASS" else "FAIL"), result
    if mode == "offline-failclosed":
        result = _offline_failclosed()
        return result.get("status", "FAIL"), result
    raise ValueError(f"unsupported updater mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["self-test", "update", "repair", "offline-failclosed"], required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    args = parser.parse_args()

    root = app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    report = _metadata(args.mode, root)
    try:
        status, service_result = _run(args.mode, root)
        report["status"] = status
        report["service_result"] = service_result
        report["service_result_sha256"] = sha256_json(service_result)
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"

    args.result_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.result_file, report)
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
