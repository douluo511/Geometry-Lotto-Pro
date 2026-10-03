from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from software_net_client import NetClient


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _durable_sync_path(path: Path) -> None:
    """Flush staged bytes using a Windows-safe handle when running on Windows."""
    path = Path(path).resolve()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        flush_file = kernel32.FlushFileBuffers
        flush_file.argtypes = [wintypes.HANDLE]
        flush_file.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        handle = create_file(str(path), GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not flush_file(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close_handle(handle)
        return

    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_path(src: Path, dst: Path) -> None:
    os.replace(src, dst)


def _atomic_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_canonical_json(value) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = str(value).strip().split(".")
    if not parts or any(not x.isdigit() for x in parts):
        raise ValueError(f"invalid numeric version: {value!r}")
    return tuple(int(x) for x in parts)


def _trusted_https(url: str, trusted_hosts: set[str]) -> bool:
    p = urlsplit(str(url))
    return p.scheme.lower() == "https" and bool(p.hostname) and p.hostname.lower() in trusted_hosts


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _receipt_without_raw(receipt: Any) -> dict[str, Any]:
    value = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {})
    value.pop("raw_b64", None)
    return value


def _wait_parent_exit(parent_pid: int, timeout: float = 30.0) -> None:
    if parent_pid <= 0:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(parent_pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise RuntimeError(f"parent process {parent_pid} did not exit before timeout")


def _transaction_paths(target_exe: Path) -> tuple[Path, Path, Path, Path]:
    target = Path(target_exe).resolve()
    return (
        target.with_name(target.name + ".update-stage"),
        target.with_name(target.name + ".backup"),
        target.with_name(target.name + ".health.json"),
        target.with_name(target.name + ".update-transaction.json"),
    )


def recover_interrupted_update(target_exe: Path) -> dict[str, Any]:
    target = Path(target_exe).resolve()
    stage, backup, health, journal = _transaction_paths(target)
    if not journal.exists():
        stage.unlink(missing_ok=True)
        health.unlink(missing_ok=True)
        if backup.exists():
            _replace_path(backup, target)
            return {
                "status": "PASS",
                "action": "RECOVERED_ORPHAN_BACKUP",
                "restored_sha256": _sha256_path(target),
            }
        return {"status": "PASS", "action": "NO_INCOMPLETE_UPDATE"}

    try:
        state = json.loads(journal.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError("software-update transaction journal is invalid") from exc
    if not isinstance(state, dict) or state.get("schema") != "psychology-software-update-transaction-v1":
        raise RuntimeError("software-update transaction journal schema invalid")
    if str(Path(state.get("target_exe") or "").resolve()) != str(target):
        raise RuntimeError("software-update transaction target mismatch")

    expected_old = str(state.get("old_exe_sha256") or "").lower()
    expected_new = str(state.get("new_exe_sha256") or "").lower()
    phase = str(state.get("phase") or "")

    if backup.exists():
        _replace_path(backup, target)
        restored = _sha256_path(target)
        if expected_old and restored != expected_old:
            raise RuntimeError("restart rollback hash mismatch")
        stage.unlink(missing_ok=True)
        health.unlink(missing_ok=True)
        journal.unlink(missing_ok=True)
        return {"status": "PASS", "action": "RECOVERED_ROLLBACK", "phase": phase, "restored_sha256": restored}

    if phase == "STAGED" and target.exists():
        actual = _sha256_path(target)
        if expected_old and actual != expected_old:
            raise RuntimeError("staged interrupted update target drift")
        stage.unlink(missing_ok=True)
        health.unlink(missing_ok=True)
        journal.unlink(missing_ok=True)
        return {"status": "PASS", "action": "DISCARDED_PRE_REPLACE_STAGE", "target_sha256": actual}

    if phase == "SELF_TEST_PASSED" and target.exists():
        actual = _sha256_path(target)
        if expected_new and actual == expected_new:
            stage.unlink(missing_ok=True)
            health.unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
            return {"status": "PASS", "action": "RECOVERED_COMMIT", "target_sha256": actual}

    raise RuntimeError(
        f"incomplete update cannot be recovered safely: phase={phase!r}, "
        f"backup_exists={backup.exists()}, target_exists={target.exists()}"
    )


class Updater:
    def __init__(self, *, manifest_url: str, trusted_hosts: set[str], net: NetClient | None = None):
        self.manifest_url = str(manifest_url)
        self.trusted_hosts = {str(x).strip().lower() for x in trusted_hosts if str(x).strip()}
        if not self.trusted_hosts:
            raise ValueError("trusted_hosts must not be empty")
        if not _trusted_https(self.manifest_url, self.trusted_hosts):
            raise ValueError("manifest URL must be HTTPS on a trusted host")
        self.net = net or NetClient(
            connect_timeout=10,
            read_timeout=120,
            max_attempts=3,
            max_payload_bytes=512 * 1024 * 1024,
        )

    def fetch_manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        raw, receipt_obj = self.net.get_bytes(self.manifest_url, source_id="software_update_manifest")
        receipt = _receipt_without_raw(receipt_obj)
        final_url = str(receipt.get("final_url") or self.manifest_url)
        if not _trusted_https(final_url, self.trusted_hosts):
            raise RuntimeError("manifest response left trusted HTTPS hosts")
        if len(raw) > 1024 * 1024:
            raise RuntimeError("manifest exceeds 1 MiB")
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            raise RuntimeError("manifest JSON invalid") from exc
        if not isinstance(value, dict) or value.get("schema") != "psychology-software-update-manifest-v1":
            raise RuntimeError("manifest schema invalid")
        version = str(value.get("version") or "")
        _version_tuple(version)
        artifact_url = str(value.get("artifact_url") or "")
        if not _trusted_https(artifact_url, self.trusted_hosts):
            raise RuntimeError("artifact URL is not trusted HTTPS")
        digest = str(value.get("artifact_sha256") or "").lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise RuntimeError("manifest artifact SHA-256 invalid")
        try:
            artifact_bytes = int(value.get("artifact_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("manifest artifact byte size invalid") from exc
        if artifact_bytes <= 0 or artifact_bytes > 512 * 1024 * 1024:
            raise RuntimeError("manifest artifact byte size invalid")
        return value, receipt

    def download_artifact(self, manifest: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
        url = str(manifest["artifact_url"])
        raw, receipt_obj = self.net.get_bytes(url, source_id="software_update_artifact")
        receipt = _receipt_without_raw(receipt_obj)
        final_url = str(receipt.get("final_url") or url)
        if not _trusted_https(final_url, self.trusted_hosts):
            raise RuntimeError("artifact response left trusted HTTPS hosts")
        expected_bytes = int(manifest["artifact_bytes"])
        if len(raw) != expected_bytes:
            raise RuntimeError(f"artifact size mismatch: {len(raw)} != {expected_bytes}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(manifest["artifact_sha256"]).lower():
            raise RuntimeError("artifact SHA-256 mismatch")
        return raw, receipt

    def install(
        self,
        *,
        target_exe: Path,
        current_version: str,
        parent_pid: int = 0,
        evidence_file: Path | None = None,
    ) -> dict[str, Any]:
        target = Path(target_exe).resolve()
        if not target.is_file():
            raise FileNotFoundError(f"target EXE does not exist: {target}")

        current = _version_tuple(current_version)
        recovery = recover_interrupted_update(target)
        stage, backup, health, journal = _transaction_paths(target)
        old_hash = _sha256_path(target)
        manifest: dict[str, Any] = {}
        manifest_receipt: dict[str, Any] | None = None
        artifact_receipt: dict[str, Any] | None = None
        backup_created = False

        try:
            manifest, manifest_receipt = self.fetch_manifest()
            proposed = _version_tuple(str(manifest["version"]))
            if proposed <= current:
                result = {
                    "status": "PASS",
                    "operation": "software_update",
                    "action": "UP_TO_DATE",
                    "current_version": current_version,
                    "manifest_version": manifest["version"],
                    "manifest_receipt": manifest_receipt,
                    "startup_recovery": recovery,
                }
                if evidence_file:
                    _atomic_json(Path(evidence_file), result)
                return result

            artifact, artifact_receipt = self.download_artifact(manifest)
            stage.unlink(missing_ok=True)
            health.unlink(missing_ok=True)
            with stage.open("wb") as fh:
                fh.write(artifact)
                fh.flush()
                os.fsync(fh.fileno())

            transaction = {
                "schema": "psychology-software-update-transaction-v1",
                "status": "NOT VERIFIED",
                "phase": "STAGED",
                "target_exe": str(target),
                "from_version": current_version,
                "to_version": manifest["version"],
                "old_exe_sha256": old_hash,
                "new_exe_sha256": str(manifest["artifact_sha256"]).lower(),
            }
            _atomic_json(journal, transaction)

            _wait_parent_exit(parent_pid)
            backup.unlink(missing_ok=True)
            shutil.copy2(target, backup)
            _durable_sync_path(backup)
            backup_created = True

            _replace_path(stage, target)
            installed_hash = _sha256_path(target)
            if installed_hash != str(manifest["artifact_sha256"]).lower():
                raise RuntimeError("installed EXE hash mismatch")

            transaction["phase"] = "REPLACED"
            _atomic_json(journal, transaction)
            completed = subprocess.run(
                [str(target), "--self-test", "--result-file", str(health)],
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"new EXE self-test exit code {completed.returncode}")
            try:
                health_value = json.loads(health.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                raise RuntimeError("new EXE did not produce valid health evidence") from exc
            if health_value.get("status") != "PASS":
                raise RuntimeError("new EXE health evidence is not PASS")

            transaction["phase"] = "SELF_TEST_PASSED"
            _atomic_json(journal, transaction)
            backup.unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
            health.unlink(missing_ok=True)
            result = {
                "status": "PASS",
                "operation": "software_update",
                "action": "UPDATED",
                "from_version": current_version,
                "to_version": manifest["version"],
                "old_exe_sha256": old_hash,
                "new_exe_sha256": installed_hash,
                "manifest_receipt": manifest_receipt,
                "artifact_receipt": artifact_receipt,
                "rollback_performed": False,
                "startup_recovery": recovery,
            }
        except Exception as exc:
            rollback_error = None
            action = "ABORTED_BEFORE_REPLACE"
            if backup_created and backup.exists():
                try:
                    _replace_path(backup, target)
                    restored = _sha256_path(target)
                    if restored != old_hash:
                        raise RuntimeError("rollback restored hash mismatch")
                    action = "ROLLED_BACK"
                    journal.unlink(missing_ok=True)
                except Exception as rollback_exc:
                    rollback_error = f"{type(rollback_exc).__name__}: {rollback_exc}"
                    action = "ROLLBACK_FAILED"
            else:
                journal.unlink(missing_ok=True)
            result = {
                "status": "FAIL",
                "operation": "software_update",
                "action": action,
                "from_version": current_version,
                "to_version": manifest.get("version"),
                "error": f"{type(exc).__name__}: {exc}",
                "rollback_error": rollback_error,
                "manifest_receipt": manifest_receipt,
                "artifact_receipt": artifact_receipt,
                "startup_recovery": recovery,
            }
        finally:
            stage.unlink(missing_ok=True)
            health.unlink(missing_ok=True)

        if evidence_file:
            _atomic_json(Path(evidence_file), result)
        return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--manifest-url")
    p.add_argument("--trusted-host", action="append")
    p.add_argument("--target-exe")
    p.add_argument("--current-version")
    p.add_argument("--parent-pid", type=int, default=0)
    p.add_argument("--evidence-file")
    args = p.parse_args(argv)

    if args.self_test:
        checks = {}
        try:
            checks["version_parser"] = "PASS" if _version_tuple("1.2.3") == (1, 2, 3) else "FAIL"
        except Exception:
            checks["version_parser"] = "FAIL"
        checks["https_trust"] = (
            "PASS"
            if _trusted_https("https://updates.example/a", {"updates.example"})
            and not _trusted_https("http://updates.example/a", {"updates.example"})
            else "FAIL"
        )
        result = {
            "schema": "psychology-updater-self-test-v1",
            "process_id": os.getpid(),
            "status": "PASS" if all(x == "PASS" for x in checks.values()) else "FAIL",
            "checks": checks,
        }
        if args.evidence_file:
            _atomic_json(Path(args.evidence_file), result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2

    missing = [
        name for name, value in (
            ("manifest-url", args.manifest_url),
            ("trusted-host", args.trusted_host),
            ("target-exe", args.target_exe),
            ("current-version", args.current_version),
        ) if not value
    ]
    if missing:
        p.error("missing required updater arguments: " + ", ".join(missing))

    try:
        target_hash_before = _sha256_path(Path(args.target_exe))
        updater = Updater(
            manifest_url=args.manifest_url,
            trusted_hosts=set(args.trusted_host),
        )
        result = updater.install(
            target_exe=Path(args.target_exe),
            current_version=args.current_version,
            parent_pid=args.parent_pid,
            evidence_file=Path(args.evidence_file) if args.evidence_file else None,
        )
    except Exception as exc:
        result = {"status": "FAIL", "operation": "software_update", "error": f"{type(exc).__name__}: {exc}"}
    result.update({"schema": "psychology-updater-execution-v1", "process_id": os.getpid(),
                   "github_sha": os.environ.get("PSYCHOLOGY_SOURCE_SHA") or os.environ.get("GITHUB_SHA"),
                   "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                   "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                   "target_exe": str(Path(args.target_exe).resolve()),
                   "main_sha256_before": locals().get("target_hash_before"),
                   "main_sha256_after": _sha256_path(Path(args.target_exe)) if Path(args.target_exe).is_file() else None,
                   "updater_exe_sha256": _sha256_path(Path(sys.executable)) if getattr(sys, "frozen", False) else None})
    if args.evidence_file:
        _atomic_json(Path(args.evidence_file), result)
    if not args.evidence_file:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
