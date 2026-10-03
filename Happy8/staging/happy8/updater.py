from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from .net_client import NetClient
from .storage import canonical_json


def _durable_sync_path(path: Path) -> None:
    """Force staged bytes to stable storage without relying on a live Python fd on Windows."""
    path = Path(path).resolve()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
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
        handle = create_file(
            str(path),
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
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


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical_json(value) + "\n")
            fh.flush()
        _durable_sync_path(Path(tmp_name))
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = str(value).strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid numeric version: {value!r}")
    return tuple(int(part) for part in parts)


def _trusted_https(url: str, trusted_hosts: set[str]) -> bool:
    parsed = urlsplit(str(url))
    return parsed.scheme.lower() == "https" and parsed.hostname in trusted_hosts


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


class Updater:
    def __init__(
        self,
        *,
        manifest_url: str,
        trusted_hosts: set[str],
        net: NetClient | None = None,
    ):
        self.manifest_url = str(manifest_url)
        self.trusted_hosts = {str(host).lower() for host in trusted_hosts if str(host).strip()}
        if not self.trusted_hosts:
            raise ValueError("trusted_hosts must not be empty")
        if not _trusted_https(self.manifest_url, self.trusted_hosts):
            raise ValueError("manifest URL must be HTTPS on a trusted host")
        self.net = net or NetClient(connect_timeout=10, read_timeout=60, max_attempts=3)

    def fetch_manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self.net.get(
            self.manifest_url,
            headers={"Accept": "application/json", "User-Agent": "Happy8Updater/0.2"},
            timeout=(10, 60),
            allow_redirects=True,
        )
        final_url = str(getattr(response, "url", "") or self.manifest_url)
        if not _trusted_https(final_url, self.trusted_hosts):
            raise RuntimeError("manifest response left trusted HTTPS hosts")
        raw = bytes(response.content)
        if int(response.status_code) != 200:
            raise RuntimeError(f"manifest HTTP {response.status_code}")
        ctype = str(response.headers.get("Content-Type", "")).lower()
        if "json" not in ctype and "text/plain" not in ctype:
            raise RuntimeError(f"manifest content type invalid: {ctype!r}")
        if not raw or len(raw) > 1024 * 1024:
            raise RuntimeError(f"manifest size invalid: {len(raw)}")
        try:
            manifest = json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            raise RuntimeError("manifest JSON invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != "happy8-update-manifest-v1":
            raise RuntimeError("manifest schema invalid")
        version = str(manifest.get("version") or "")
        _version_tuple(version)
        artifact_url = str(manifest.get("artifact_url") or "")
        if not _trusted_https(artifact_url, self.trusted_hosts):
            raise RuntimeError("artifact URL is not trusted HTTPS")
        digest = str(manifest.get("artifact_sha256") or "").lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise RuntimeError("manifest artifact SHA-256 invalid")
        artifact_bytes = int(manifest.get("artifact_bytes") or 0)
        if artifact_bytes <= 0 or artifact_bytes > 512 * 1024 * 1024:
            raise RuntimeError("manifest artifact byte size invalid")
        receipt = {
            "url": final_url,
            "http_status": int(response.status_code),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "attempts": list(getattr(response, "happy8_attempts", ())),
        }
        return manifest, receipt

    def download_artifact(self, manifest: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
        url = str(manifest["artifact_url"])
        response = self.net.get(
            url,
            headers={"Accept": "application/octet-stream,*/*;q=0.8", "User-Agent": "Happy8Updater/0.2"},
            timeout=(10, 120),
            allow_redirects=True,
        )
        final_url = str(getattr(response, "url", "") or url)
        if not _trusted_https(final_url, self.trusted_hosts):
            raise RuntimeError("artifact response left trusted HTTPS hosts")
        raw = bytes(response.content)
        if int(response.status_code) != 200:
            raise RuntimeError(f"artifact HTTP {response.status_code}")
        expected_bytes = int(manifest["artifact_bytes"])
        if len(raw) != expected_bytes:
            raise RuntimeError(f"artifact size mismatch: {len(raw)} != {expected_bytes}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(manifest["artifact_sha256"]).lower():
            raise RuntimeError("artifact SHA-256 mismatch")
        receipt = {
            "url": final_url,
            "http_status": int(response.status_code),
            "bytes": len(raw),
            "sha256": digest,
            "attempts": list(getattr(response, "happy8_attempts", ())),
        }
        return raw, receipt

    def install(
        self,
        *,
        target_exe: Path,
        current_version: str,
        parent_pid: int = 0,
        evidence_file: Path | None = None,
    ) -> dict[str, Any]:
        target_exe = Path(target_exe).resolve()
        if not target_exe.exists() or not target_exe.is_file():
            raise FileNotFoundError(f"target EXE does not exist: {target_exe}")
        current = _version_tuple(current_version)
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
            }
            if evidence_file:
                _atomic_json(Path(evidence_file), result)
            return result

        artifact, artifact_receipt = self.download_artifact(manifest)
        stage = target_exe.with_name(target_exe.name + ".update-stage")
        backup = target_exe.with_name(target_exe.name + ".backup")
        health_file = target_exe.with_name(target_exe.name + ".health.json")
        with stage.open("wb") as fh:
            fh.write(artifact)
            fh.flush()
        _durable_sync_path(stage)

        _wait_parent_exit(parent_pid)
        if backup.exists():
            backup.unlink()
        shutil.copy2(target_exe, backup)
        old_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
        try:
            os.replace(stage, target_exe)
            installed_hash = hashlib.sha256(target_exe.read_bytes()).hexdigest()
            if installed_hash != str(manifest["artifact_sha256"]).lower():
                raise RuntimeError("installed EXE hash changed after atomic replace")

            completed = subprocess.run(
                [
                    str(target_exe),
                    "--self-test",
                    "--result-file",
                    str(health_file),
                ],
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"new EXE self-test exit code {completed.returncode}")
            try:
                health = json.loads(health_file.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                raise RuntimeError("new EXE did not produce valid health evidence") from exc
            if health.get("status") != "PASS":
                raise RuntimeError("new EXE health evidence is not PASS")

            backup.unlink(missing_ok=True)
            health_file.unlink(missing_ok=True)
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
            }
        except Exception as exc:
            rollback_error = None
            try:
                if backup.exists():
                    os.replace(backup, target_exe)
            except Exception as rollback_exc:
                rollback_error = f"{type(rollback_exc).__name__}: {rollback_exc}"
            result = {
                "status": "FAIL",
                "operation": "software_update",
                "action": "ROLLED_BACK" if rollback_error is None else "ROLLBACK_FAILED",
                "from_version": current_version,
                "to_version": manifest.get("version"),
                "error": f"{type(exc).__name__}: {exc}",
                "rollback_error": rollback_error,
                "manifest_receipt": manifest_receipt,
                "artifact_receipt": artifact_receipt,
            }
        finally:
            stage.unlink(missing_ok=True)
            health_file.unlink(missing_ok=True)

        if evidence_file:
            _atomic_json(Path(evidence_file), result)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest-url")
    parser.add_argument("--trusted-host", action="append")
    parser.add_argument("--target-exe")
    parser.add_argument("--current-version")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--evidence-file")
    args = parser.parse_args(argv)

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
            "schema": "happy8-updater-self-test-v1",
            "status": "PASS" if all(v == "PASS" for v in checks.values()) else "FAIL",
            "checks": checks,
        }
        if args.evidence_file:
            _atomic_json(Path(args.evidence_file), result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2

    missing = [
        name
        for name, value in (
            ("manifest-url", args.manifest_url),
            ("trusted-host", args.trusted_host),
            ("target-exe", args.target_exe),
            ("current-version", args.current_version),
        )
        if not value
    ]
    if missing:
        parser.error("missing required updater arguments: " + ", ".join(missing))

    try:
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
        result = {
            "status": "FAIL",
            "operation": "software_update",
            "error": f"{type(exc).__name__}: {exc}",
        }
        if args.evidence_file:
            _atomic_json(Path(args.evidence_file), result)
    if not args.evidence_file:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
