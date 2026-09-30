from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests

from glp.constants import APP_VERSION
from glp.service import LottoService
from glp.storage import Store
from glp.util import app_data_dir, atomic_json, sha256_bytes, sha256_json


SCHEMA = "ssq-independent-updater-v2"
SOFTWARE_MANIFEST_SCHEMA = "ssq-software-update-manifest-v1"
TRUSTED_RELEASE_OWNER = "douluo511"
TRUSTED_RELEASE_REPOSITORY = "Geometry-Lotto-Pro-SSQ"
TRUSTED_UPDATE_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _process_ancestor_chain(limit: int = 12) -> list[int]:
    """Return parent -> grandparent PID chain, including PyInstaller bootloader."""
    if os.name != "nt":
        parent = int(os.getppid())
        return [parent] if parent > 0 else []

    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        parent = int(os.getppid())
        return [parent] if parent > 0 else []
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = bool(kernel32.Process32FirstW(snap, ctypes.byref(entry)))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = bool(kernel32.Process32NextW(snap, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snap)

    chain: list[int] = []
    current = int(os.getpid())
    seen = {current}
    for _ in range(max(1, limit)):
        parent = int(parents.get(current, 0))
        if parent <= 0 or parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        current = parent
    return chain


def _metadata(mode: str, root: Path) -> dict[str, Any]:
    exe = Path(sys.executable).resolve()
    expected_parent = int(os.environ.get("GLP_UPDATER_PARENT_PID", "0") or 0)
    ancestors = _process_ancestor_chain()
    actual_parent = int(ancestors[0]) if ancestors else int(os.getppid())
    return {
        "schema": SCHEMA,
        "mode": mode,
        "pid": int(os.getpid()),
        "parent_pid": actual_parent,
        "ancestor_pids": ancestors,
        "expected_parent_pid": expected_parent,
        "parent_pid_match": bool(expected_parent and expected_parent in ancestors),
        "data_dir": str(root.resolve()),
        "updater_exe": str(exe),
        "updater_exe_sha256": _file_sha256(exe) if exe.is_file() else "",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    }


def _basic_trusted_https(url: str) -> bool:
    parsed = urlsplit(str(url))
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname in TRUSTED_UPDATE_HOSTS
        and parsed.username is None
        and parsed.password is None
        and (parsed.port in (None, 443))
    )


def _trusted_release_request(url: str, *, kind: str) -> bool:
    """Initial request must identify the frozen SSQ release publisher/repository."""
    if not _basic_trusted_https(url):
        return False
    parsed = urlsplit(str(url))
    path = parsed.path or ""
    repo_prefix = f"/{TRUSTED_RELEASE_OWNER}/{TRUSTED_RELEASE_REPOSITORY}/"
    if parsed.hostname == "github.com":
        if not path.startswith(repo_prefix):
            return False
        if kind == "artifact":
            return path.startswith(repo_prefix + "releases/download/")
        if kind == "manifest":
            return (
                path.startswith(repo_prefix + "releases/download/")
                or path.startswith(repo_prefix + "raw/")
                or path.startswith(repo_prefix + "blob/")
            )
        return False
    if parsed.hostname == "raw.githubusercontent.com":
        raw_prefix = f"/{TRUSTED_RELEASE_OWNER}/{TRUSTED_RELEASE_REPOSITORY}/"
        return kind == "manifest" and path.startswith(raw_prefix)
    # Direct object/release-assets URLs are not accepted from a manifest because
    # they do not themselves identify the trusted repository. They may only be
    # reached as HTTPS redirects from a verified github.com request.
    return False


def _trusted_redirect_target(url: str) -> bool:
    return _basic_trusted_https(url)


def _get_with_verified_redirects(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    timeout: tuple[float, float],
    max_redirects: int = 5,
):
    """Follow redirects only after validating each next hop."""
    current = url
    chain: list[dict[str, Any]] = []
    for hop in range(max_redirects + 1):
        response = session.get(
            current,
            timeout=timeout,
            allow_redirects=False,
            headers=headers,
        )
        status = int(response.status_code)
        if status not in {301, 302, 303, 307, 308}:
            response.updater_redirect_chain = chain
            return response
        location = str(response.headers.get("Location", "")).strip()
        if not location:
            raise RuntimeError(f"redirect HTTP {status} has no Location header")
        next_url = urljoin(current, location)
        if not _trusted_redirect_target(next_url):
            raise RuntimeError(f"redirect target violates trusted HTTPS policy before request: {next_url}")
        chain.append({
            "hop": hop + 1,
            "status_code": status,
            "from_url": current,
            "to_url": next_url,
        })
        current = next_url
    raise RuntimeError(f"redirect chain exceeded {max_redirects} hops")


def _bounded_get(url: str, *, kind: str, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    if not _trusted_release_request(url, kind=kind):
        raise ValueError(f"{kind} URL violates trusted release repository policy")
    session = requests.Session()
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for attempt in range(1, 4):
        delay = 0.0
        try:
            response = _get_with_verified_redirects(
                session,
                url,
                timeout=(5.0, 45.0),
                headers={
                    "User-Agent": "GeometryLottoPro-SSQ-Updater/2",
                    "Accept": "application/json,text/plain,*/*" if kind == "manifest" else "application/octet-stream,*/*",
                },
            )
            final_url = str(response.url)
            if not _trusted_redirect_target(final_url):
                raise RuntimeError(f"{kind} redirect left trusted GitHub HTTPS hosts: {final_url}")
            status = int(response.status_code)
            raw = bytes(response.content)
            receipt = {
                "attempt": attempt,
                "status_code": status,
                "requested_url": url,
                "final_url": final_url,
                "content_type": str(response.headers.get("Content-Type", "")),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "redirect_chain": list(getattr(response, "updater_redirect_chain", ())),
            }
            if status == 429 or 500 <= status <= 599:
                retry_after = str(response.headers.get("Retry-After", "")).strip()
                try:
                    delay = min(10.0, max(0.0, float(retry_after)))
                except ValueError:
                    delay = min(8.0, 0.5 * (2 ** (attempt - 1)) + random.random() * 0.25)
                receipt["outcome"] = "RETRY_HTTP" if attempt < 3 else "FINAL_HTTP"
                receipt["retry_delay"] = delay if attempt < 3 else 0.0
                attempts.append(receipt)
                if attempt >= 3:
                    raise RuntimeError(f"{kind} HTTP retry exhausted: {status}")
                time.sleep(delay)
                continue
            if status != 200:
                receipt["outcome"] = "FINAL_HTTP"
                attempts.append(receipt)
                raise RuntimeError(f"{kind} HTTP {status}")
            if not raw or len(raw) > max_bytes:
                receipt["outcome"] = "INVALID_SIZE"
                attempts.append(receipt)
                raise RuntimeError(f"{kind} invalid response size: {len(raw)}")
            receipt["outcome"] = "HTTP_RESPONSE"
            attempts.append(receipt)
            return raw, {
                "status": "PASS",
                "attempts": attempts,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": receipt["content_type"],
                "bytes": len(raw),
                "sha256": receipt["sha256"],
            }
        except Exception as exc:
            last_error = exc
            if attempts and attempts[-1].get("attempt") == attempt and attempts[-1].get("outcome") in {"FINAL_HTTP", "INVALID_SIZE"}:
                break
            attempts.append({
                "attempt": attempt,
                "outcome": "RETRY_EXCEPTION" if attempt < 3 else "FINAL_EXCEPTION",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "retry_delay": delay if attempt < 3 else 0.0,
                "requested_url": url,
            })
            if attempt >= 3:
                break
            delay = min(8.0, 0.5 * (2 ** (attempt - 1)) + random.random() * 0.25)
            attempts[-1]["retry_delay"] = delay
            time.sleep(delay)
    err = RuntimeError(f"{kind} download failed: {type(last_error).__name__}: {last_error}")
    setattr(err, "updater_attempts", attempts)
    raise err


def _version_precedence(version: str) -> tuple[Any, ...]:
    """Return a deterministic SemVer-like precedence key; build metadata is ignored."""
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?(?:\+([A-Za-z0-9.-]+))?",
        str(version).strip(),
    )
    if not match:
        raise ValueError(f"invalid software version: {version!r}")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return (*core, 1, ())
    identifiers: list[tuple[int, Any]] = []
    for token in prerelease.split("."):
        if not token:
            raise ValueError("empty prerelease identifier")
        identifiers.append((0, int(token)) if token.isdigit() else (1, token))
    return (*core, 0, tuple(identifiers))


def _require_forward_version(current_version: str, candidate_version: str) -> None:
    current_key = _version_precedence(current_version)
    candidate_key = _version_precedence(candidate_version)
    if candidate_key <= current_key:
        raise ValueError(
            f"software update must move forward: current={current_version}, candidate={candidate_version}"
        )


def _parse_software_manifest(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("software manifest too large")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise ValueError("software manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != SOFTWARE_MANIFEST_SCHEMA:
        raise ValueError("software manifest schema mismatch")
    if value.get("app") != "Geometry Lotto Pro SSQ":
        raise ValueError("software manifest app identity mismatch")
    version = str(value.get("version") or "").strip()
    artifact_url = str(value.get("artifact_url") or "").strip()
    digest = str(value.get("artifact_sha256") or "").lower()
    size = value.get("artifact_bytes")
    try:
        _version_precedence(version)
    except ValueError as exc:
        raise ValueError("software manifest version is not a valid release version") from exc
    if not _trusted_release_request(artifact_url, kind="artifact"):
        raise ValueError("software artifact URL violates trusted release repository policy")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("software manifest artifact SHA256 invalid")
    if not isinstance(size, int) or size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("software manifest artifact size invalid")
    return {
        "schema": SOFTWARE_MANIFEST_SCHEMA,
        "app": "Geometry Lotto Pro SSQ",
        "version": version,
        "artifact_url": artifact_url,
        "artifact_sha256": digest,
        "artifact_bytes": size,
    }


def _stage_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _apply_verified_artifact(
    target: Path,
    artifact: bytes,
    expected_sha256: str,
    *,
    validator: Callable[[Path], tuple[bool, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        raise FileNotFoundError(f"target executable does not exist: {target}")
    before = target.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    new_hash = hashlib.sha256(artifact).hexdigest()
    if new_hash != expected_sha256:
        raise ValueError("staged artifact SHA256 mismatch before replacement")

    token = uuid4().hex
    stage = target.parent / f".{target.name}.{token}.stage"
    rollback = target.parent / f".{target.name}.{token}.rollback"
    preserved_previous = target.with_name(target.name + ".previous")
    evidence: dict[str, Any] = {
        "status": "FAIL",
        "target": str(target),
        "before_sha256": before_hash,
        "expected_sha256": expected_sha256,
        "staged_sha256": new_hash,
        "replaced": False,
        "rolled_back": False,
        "previous_preserved": False,
    }

    try:
        _stage_bytes(stage, artifact)
        if _file_sha256(stage) != expected_sha256:
            raise RuntimeError("staged artifact failed SHA256 read-back")
        if _file_sha256(target) != before_hash:
            raise RuntimeError("target executable changed during staging")
        os.replace(target, rollback)
        if _file_sha256(rollback) != before_hash:
            raise RuntimeError("target executable changed before atomic replacement")
        try:
            os.replace(stage, target)
            evidence["replaced"] = True
            if _file_sha256(target) != expected_sha256:
                raise RuntimeError("installed artifact failed SHA256 read-back")
            validation = {"status": "SKIPPED"}
            if validator is not None:
                ok, validation = validator(target)
                if not ok:
                    raise RuntimeError("installed artifact exact self-test failed")
            evidence["post_replace_validation"] = validation
            if preserved_previous.exists():
                preserved_previous.unlink()
            os.replace(rollback, preserved_previous)
            evidence["previous_preserved"] = True
            evidence["previous_sha256"] = _file_sha256(preserved_previous)
            evidence["installed_sha256"] = _file_sha256(target)
            evidence["status"] = "PASS"
            return evidence
        except Exception as exc:
            evidence["install_error"] = f"{type(exc).__name__}: {exc}"
            try:
                if target.exists():
                    target.unlink()
                os.replace(rollback, target)
                evidence["rolled_back"] = _file_sha256(target) == before_hash
                evidence["restored_sha256"] = _file_sha256(target)
            except Exception as rollback_exc:
                evidence["rollback_error"] = f"{type(rollback_exc).__name__}: {rollback_exc}"
            return evidence
    finally:
        stage.unlink(missing_ok=True)
        if rollback.exists():
            # If replacement never started, restore original immediately.
            if not target.exists():
                try:
                    os.replace(rollback, target)
                    evidence["rolled_back"] = _file_sha256(target) == before_hash
                except Exception:
                    pass
            else:
                rollback.unlink(missing_ok=True)


def _exact_main_self_test(target: Path, expected_version: str | None = None) -> tuple[bool, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="ssq-updater-main-self-") as td:
        result = Path(td) / "self.json"
        try:
            proc = subprocess.run(
                [str(target), "--check", "self", "--result-file", str(result)],
                timeout=900,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            payload = json.loads(result.read_text(encoding="utf-8-sig")) if result.is_file() else {}
            ok = (
                proc.returncode == 0
                and payload.get("status") == "PASS"
                and payload.get("exe_sha256") == _file_sha256(target)
                and payload.get("game") == "SSQ"
                and (expected_version is None or payload.get("version") == expected_version)
            )
            return ok, {
                "status": "PASS" if ok else "FAIL",
                "exit_code": proc.returncode,
                "result": payload,
                "target_sha256": _file_sha256(target),
                "expected_version": expected_version,
                "reported_version": payload.get("version"),
            }
        except Exception as exc:
            return False, {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def _wait_pid_exit(pid: int, timeout_seconds: int = 120) -> dict[str, Any]:
    if pid <= 0:
        return {"status": "PASS", "waited": False}
    started = time.time()
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return {"status": "PASS", "waited": False, "reason": "process already absent"}
        try:
            remaining = max(0, int(timeout_seconds * 1000))
            result = ctypes.windll.kernel32.WaitForSingleObject(handle, remaining)
            ok = result == WAIT_OBJECT_0
            return {"status": "PASS" if ok else "FAIL", "waited": True, "pid": pid, "elapsed": time.time() - started}
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    deadline = started + timeout_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return {"status": "PASS", "waited": True, "pid": pid, "elapsed": time.time() - started}
        time.sleep(0.2)
    return {"status": "FAIL", "waited": True, "pid": pid, "elapsed": time.time() - started}


def _software_update(target: Path, manifest_url: str, wait_pid: int = 0) -> dict[str, Any]:
    wait = _wait_pid_exit(wait_pid)
    if wait.get("status") != "PASS":
        return {"status": "FAIL", "wait_for_main": wait, "error": "main process did not exit before replacement"}

    manifest_raw, manifest_receipt = _bounded_get(manifest_url, kind="manifest", max_bytes=MAX_MANIFEST_BYTES)
    manifest = _parse_software_manifest(manifest_raw)
    _require_forward_version(APP_VERSION, manifest["version"])
    artifact, artifact_receipt = _bounded_get(
        manifest["artifact_url"], kind="artifact", max_bytes=MAX_ARTIFACT_BYTES
    )
    artifact_hash = hashlib.sha256(artifact).hexdigest()
    if len(artifact) != manifest["artifact_bytes"]:
        raise ValueError("software artifact byte count does not match manifest")
    if artifact_hash != manifest["artifact_sha256"]:
        raise ValueError("software artifact SHA256 does not match manifest")

    replacement = _apply_verified_artifact(
        target,
        artifact,
        manifest["artifact_sha256"],
        validator=lambda path: _exact_main_self_test(path, expected_version=manifest["version"]),
    )
    return {
        "status": replacement.get("status", "FAIL"),
        "schema": "ssq-software-update-result-v1",
        "manifest": manifest,
        "manifest_receipt": manifest_receipt,
        "manifest_raw_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "artifact_receipt": artifact_receipt,
        "replacement": replacement,
        "wait_for_main": wait,
    }


def _software_self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ssq-updater-atomic-") as td:
        root = Path(td)
        target = root / "Geometry_Lotto_Pro_SSQ_Windows_Verified.exe"
        old = b"old-main-exe-bytes-v1"
        new = b"new-main-exe-bytes-v2"
        bad = b"bad-main-exe-bytes-v3"
        target.write_bytes(old)

        success = _apply_verified_artifact(
            target,
            new,
            hashlib.sha256(new).hexdigest(),
            validator=lambda p: (p.read_bytes() == new, {"status": "PASS" if p.read_bytes() == new else "FAIL"}),
        )
        success_ok = (
            success.get("status") == "PASS"
            and target.read_bytes() == new
            and target.with_name(target.name + ".previous").read_bytes() == old
        )

        before_failure = target.read_bytes()
        forced_rollback = _apply_verified_artifact(
            target,
            bad,
            hashlib.sha256(bad).hexdigest(),
            validator=lambda _p: (False, {"status": "FAIL", "injected": True}),
        )
        rollback_ok = (
            forced_rollback.get("status") == "FAIL"
            and forced_rollback.get("rolled_back") is True
            and target.read_bytes() == before_failure
        )
        checks = {
            "atomic_replace_success": success_ok,
            "previous_bytes_preserved": success.get("previous_preserved") is True,
            "post_replace_validation_bound": success.get("post_replace_validation", {}).get("status") == "PASS",
            "forced_validation_failure_rolls_back": rollback_ok,
            "rollback_hash_restored": forced_rollback.get("restored_sha256") == hashlib.sha256(before_failure).hexdigest(),
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "success_case": success,
            "rollback_case": forced_rollback,
        }


def _software_local_acceptance(
    target: Path,
    candidate: Path,
    *,
    expect_rollback: bool,
) -> dict[str, Any]:
    """Acceptance-only exact-artifact transaction. Never counts as release network."""
    if os.environ.get("GLP_UPDATER_ACCEPTANCE") != "1":
        raise RuntimeError("local software acceptance mode is disabled outside acceptance")
    target = target.resolve()
    candidate = candidate.resolve()
    if not target.is_file() or not candidate.is_file():
        raise FileNotFoundError("local acceptance target/candidate missing")
    before_hash = _file_sha256(target)
    artifact = candidate.read_bytes()
    candidate_hash = hashlib.sha256(artifact).hexdigest()
    transaction = _apply_verified_artifact(
        target,
        artifact,
        candidate_hash,
        validator=_exact_main_self_test,
    )
    after_hash = _file_sha256(target) if target.is_file() else ""
    if expect_rollback:
        ok = (
            transaction.get("status") == "FAIL"
            and transaction.get("rolled_back") is True
            and after_hash == before_hash
            and transaction.get("restored_sha256") == before_hash
        )
    else:
        ok = (
            transaction.get("status") == "PASS"
            and after_hash == candidate_hash
            and isinstance(transaction.get("post_replace_validation"), dict)
            and transaction["post_replace_validation"].get("status") == "PASS"
            and transaction.get("previous_preserved") is True
        )
    return {
        "status": "PASS" if ok else "FAIL",
        "validation_scope": "LOCAL_EXACT_ARTIFACT_ACCEPTANCE_ONLY",
        "release_network_status": "PENDING",
        "expect_rollback": bool(expect_rollback),
        "before_sha256": before_hash,
        "candidate_sha256": candidate_hash,
        "after_sha256": after_hash,
        "transaction": transaction,
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


def _run(mode: str, root: Path, *, target_exe: Path | None = None, manifest_url: str = "", wait_pid: int = 0) -> tuple[str, dict[str, Any]]:
    if mode == "software-self-test":
        result = _software_self_test()
        return result.get("status", "FAIL"), result
    if mode == "software-update":
        if target_exe is None or not manifest_url:
            raise ValueError("software-update requires --target-exe and --manifest-url")
        result = _software_update(target_exe, manifest_url, wait_pid=wait_pid)
        return result.get("status", "FAIL"), result
    if mode in {"software-local-install-acceptance", "software-local-rollback-acceptance"}:
        candidate_text = os.environ.get("GLP_UPDATER_ACCEPTANCE_CANDIDATE", "")
        if target_exe is None or not candidate_text:
            raise ValueError("local software acceptance requires target and acceptance candidate")
        result = _software_local_acceptance(
            target_exe,
            Path(candidate_text),
            expect_rollback=(mode == "software-local-rollback-acceptance"),
        )
        return result.get("status", "FAIL"), result

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
    parser.add_argument(
        "--mode",
        choices=[
            "self-test", "update", "repair", "offline-failclosed",
            "software-self-test", "software-update",
            "software-local-install-acceptance", "software-local-rollback-acceptance",
        ],
        required=True,
    )
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--target-exe", type=Path)
    parser.add_argument("--manifest-url", default="")
    parser.add_argument("--wait-pid", type=int, default=0)
    args = parser.parse_args()

    root = app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    report = _metadata(args.mode, root)
    try:
        status, service_result = _run(
            args.mode,
            root,
            target_exe=args.target_exe,
            manifest_url=args.manifest_url,
            wait_pid=args.wait_pid,
        )
        report["status"] = status
        report["service_result"] = service_result
        report["service_result_sha256"] = sha256_json(service_result)
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        attempts = getattr(exc, "updater_attempts", None)
        if attempts is not None:
            report["network_attempts"] = attempts

    args.result_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.result_file, report)
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
