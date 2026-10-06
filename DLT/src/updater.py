from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import requests

from glp.constants import APP_VERSION
from glp.service import LottoService
from glp.storage import Store
from glp.util import atomic_json, utc_now

SCHEMA = "dlt-independent-updater-v1"
ACCEPTANCE_SCHEMA = "dlt-updater-exact-acceptance-v1"
MANIFEST_SCHEMA = "dlt-software-update-manifest-v1"
TRUSTED_OWNER = "douluo511"
TRUSTED_REPOSITORY = "Geometry-Lotto-Pro-DLT"
TRUSTED_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ancestor_pids(limit: int = 12) -> list[int]:
    if os.name != "nt":
        p = int(os.getppid())
        return [p] if p > 0 else []
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        p = int(os.getppid())
        return [p] if p > 0 else []
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = bool(k32.Process32FirstW(snap, ctypes.byref(entry)))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = bool(k32.Process32NextW(snap, ctypes.byref(entry)))
    finally:
        k32.CloseHandle(snap)
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


def _metadata(mode: str) -> dict[str, Any]:
    exe = Path(sys.executable).resolve()
    ancestors = _ancestor_pids()
    expected_parent = int(os.environ.get("GLP_UPDATER_PARENT_PID", "0") or 0)
    return {
        "schema": SCHEMA,
        "mode": mode,
        "pid": os.getpid(),
        "parent_pid": ancestors[0] if ancestors else os.getppid(),
        "ancestor_pids": ancestors,
        "expected_parent_pid": expected_parent,
        "parent_pid_match": bool(expected_parent and expected_parent in ancestors),
        "updater_exe": str(exe),
        "updater_exe_sha256": _sha256_file(exe) if exe.is_file() else "",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "version": APP_VERSION,
    }


def _trusted_initial_url(url: str, kind: str) -> bool:
    p = urlsplit(str(url))
    if p.scheme.lower() != "https" or p.hostname not in TRUSTED_HOSTS or p.username or p.password or p.port not in (None, 443):
        return False
    prefix = f"/{TRUSTED_OWNER}/{TRUSTED_REPOSITORY}/"
    if p.hostname == "github.com":
        if kind == "artifact":
            return p.path.startswith(prefix + "releases/download/")
        return p.path.startswith(prefix + "releases/download/") or p.path.startswith(prefix + "raw/") or p.path.startswith(prefix + "blob/")
    if p.hostname == "raw.githubusercontent.com":
        return kind == "manifest" and p.path.startswith(prefix)
    return False


def _trusted_redirect(url: str) -> bool:
    p = urlsplit(str(url))
    return p.scheme.lower() == "https" and p.hostname in TRUSTED_HOSTS and not p.username and not p.password and p.port in (None, 443)


def _download(url: str, kind: str, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    if not _trusted_initial_url(url, kind):
        raise ValueError(f"{kind} URL violates trusted DLT release policy")
    session = requests.Session()
    current = url
    chain: list[dict[str, Any]] = []
    for hop in range(6):
        r = session.get(
            current,
            timeout=(5.0, 45.0),
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "GeometryLottoPro-DLT-Updater/1"},
        )
        try:
            if r.status_code in (301, 302, 303, 307, 308):
                location = str(r.headers.get("Location", "")).strip()
                if not location:
                    raise RuntimeError("redirect missing Location")
                nxt = urljoin(current, location)
                if not _trusted_redirect(nxt):
                    raise RuntimeError("redirect escaped trusted HTTPS hosts")
                chain.append({"status": int(r.status_code), "from": current, "to": nxt})
                current = nxt
                continue
            if int(r.status_code) != 200:
                raise RuntimeError(f"{kind} HTTP {r.status_code}")
            advertised = str(r.headers.get("Content-Length", "")).strip()
            if advertised and int(advertised) > max_bytes:
                raise RuntimeError(f"{kind} response exceeds size limit")
            body = bytearray()
            for chunk in r.iter_content(chunk_size=CHUNK_BYTES):
                if not chunk:
                    continue
                if len(body) + len(chunk) > max_bytes:
                    raise RuntimeError(f"{kind} response exceeds size limit")
                body.extend(chunk)
            if not body:
                raise RuntimeError(f"{kind} response is empty")
            raw = bytes(body)
            return raw, {
                "status": "PASS",
                "requested_url": url,
                "final_url": current,
                "http_status": int(r.status_code),
                "bytes": len(raw),
                "sha256": _sha256_bytes(raw),
                "redirect_chain": chain,
            }
        finally:
            r.close()
    raise RuntimeError("redirect chain exceeded hard limit")


def _version_key(value: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value).strip())
    if not m:
        raise ValueError(f"invalid stable software version: {value!r}")
    return tuple(int(m.group(i)) for i in (1, 2, 3))


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict) or value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("manifest schema mismatch")
    if value.get("app") != "Geometry Lotto Pro DLT":
        raise ValueError("manifest app identity mismatch")
    version = str(value.get("version", "")).strip()
    artifact_url = str(value.get("artifact_url", "")).strip()
    digest = str(value.get("artifact_sha256", "")).lower()
    size = value.get("artifact_bytes")
    _version_key(version)
    if not _trusted_initial_url(artifact_url, "artifact"):
        raise ValueError("artifact URL violates trusted release policy")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("artifact SHA256 invalid")
    if type(size) is not int or size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact size invalid")
    return {
        "schema": MANIFEST_SCHEMA,
        "app": "Geometry Lotto Pro DLT",
        "version": version,
        "artifact_url": artifact_url,
        "artifact_sha256": digest,
        "artifact_bytes": size,
    }


def _stage(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def apply_verified_artifact(
    target: Path,
    artifact: bytes,
    expected_sha256: str,
    validator: Callable[[Path], tuple[bool, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    target = target.resolve()
    if not target.is_file():
        raise FileNotFoundError(f"target executable missing: {target}")
    before = target.read_bytes()
    before_hash = _sha256_bytes(before)
    artifact_hash = _sha256_bytes(artifact)
    if artifact_hash != expected_sha256:
        raise ValueError("staged artifact SHA256 mismatch")

    token = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    staged = target.with_name(f".{target.name}.{token}.stage")
    rollback = target.with_name(f".{target.name}.{token}.rollback")
    previous = target.with_name(target.name + ".previous")
    evidence: dict[str, Any] = {
        "status": "FAIL",
        "target": str(target),
        "before_sha256": before_hash,
        "staged_sha256": artifact_hash,
        "expected_sha256": expected_sha256,
        "replaced": False,
        "rolled_back": False,
        "previous_preserved": False,
    }
    try:
        _stage(staged, artifact)
        if _sha256_file(staged) != expected_sha256:
            raise RuntimeError("staged read-back hash mismatch")
        if _sha256_file(target) != before_hash:
            raise RuntimeError("target changed during staging")
        os.replace(target, rollback)
        try:
            os.replace(staged, target)
            evidence["replaced"] = True
            if _sha256_file(target) != expected_sha256:
                raise RuntimeError("installed hash mismatch")
            validation = {"status": "SKIPPED"}
            if validator is not None:
                ok, validation = validator(target)
                if not ok:
                    raise RuntimeError("installed exact self-test failed")
            evidence["post_replace_validation"] = validation
            previous.unlink(missing_ok=True)
            os.replace(rollback, previous)
            evidence["previous_preserved"] = True
            evidence["previous_sha256"] = _sha256_file(previous)
            evidence["installed_sha256"] = _sha256_file(target)
            evidence["status"] = "PASS"
            return evidence
        except Exception as exc:
            evidence["install_error"] = f"{type(exc).__name__}: {exc}"
            target.unlink(missing_ok=True)
            if rollback.exists():
                os.replace(rollback, target)
            evidence["rolled_back"] = target.exists() and _sha256_file(target) == before_hash
            if target.exists():
                evidence["restored_sha256"] = _sha256_file(target)
            return evidence
    finally:
        staged.unlink(missing_ok=True)
        if rollback.exists():
            if not target.exists():
                os.replace(rollback, target)
            else:
                rollback.unlink(missing_ok=True)


def _validate_installed_main(path: Path) -> tuple[bool, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="dlt-updater-validate-") as td:
        result = Path(td) / "self.json"
        env = dict(os.environ)
        env["GLP_DATA_DIR"] = str(Path(td) / "data")
        p = subprocess.run(
            [str(path), "--self-test", "--result-file", str(result)],
            env=env,
            timeout=180,
            check=False,
            capture_output=True,
            text=True,
        )
        value = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
        proof = {
            "status": "PASS" if p.returncode == 0 and value.get("status") == "PASS" else "FAIL",
            "exit_code": p.returncode,
            "result": value,
            "stdout_tail": p.stdout[-2000:],
            "stderr_tail": p.stderr[-2000:],
        }
        return proof["status"] == "PASS", proof


def software_self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dlt-updater-atomic-") as td:
        root = Path(td)
        target = root / "Geometry_Lotto_Pro_DLT.exe"
        original = b"DLT_ORIGINAL_BYTES_v1\n"
        candidate = b"DLT_CANDIDATE_BYTES_v2\n"
        target.write_bytes(original)
        success = apply_verified_artifact(target, candidate, _sha256_bytes(candidate))
        target.write_bytes(original)

        def reject(_path: Path):
            return False, {"status": "FAIL", "reason": "injected validator failure"}

        rollback = apply_verified_artifact(target, candidate, _sha256_bytes(candidate), reject)
        checks = {
            "atomic_replace_success": success.get("status") == "PASS",
            "previous_bytes_preserved": success.get("previous_sha256") == _sha256_bytes(original),
            "installed_hash_bound": success.get("installed_sha256") == _sha256_bytes(candidate),
            "forced_validation_failure_rolls_back": rollback.get("status") == "FAIL" and rollback.get("rolled_back") is True,
            "rollback_hash_restored": rollback.get("restored_sha256") == _sha256_bytes(original),
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "success_case": success,
            "rollback_case": rollback,
        }


def run_software_update(manifest_url: str, target_exe: str, current_version: str) -> dict[str, Any]:
    manifest_raw, manifest_receipt = _download(manifest_url, "manifest", MAX_MANIFEST_BYTES)
    manifest = _parse_manifest(manifest_raw)
    if _version_key(manifest["version"]) <= _version_key(current_version):
        raise ValueError("software update must move to a newer stable version")
    artifact, artifact_receipt = _download(manifest["artifact_url"], "artifact", MAX_ARTIFACT_BYTES)
    if len(artifact) != manifest["artifact_bytes"]:
        raise ValueError("artifact byte count differs from manifest")
    if _sha256_bytes(artifact) != manifest["artifact_sha256"]:
        raise ValueError("artifact SHA256 differs from manifest")
    install = apply_verified_artifact(
        Path(target_exe),
        artifact,
        manifest["artifact_sha256"],
        validator=_validate_installed_main,
    )
    if install.get("status") != "PASS":
        raise RuntimeError("software update failed and was rolled back")
    return {
        "status": "PASS",
        "manifest": manifest,
        "manifest_receipt": manifest_receipt,
        "artifact_receipt": artifact_receipt,
        "install": install,
    }



def _wait_for_parent_exit(pid: int, timeout_seconds: int = 90) -> dict[str, Any]:
    if pid <= 0:
        return {"status": "SKIPPED", "pid": pid}
    started = time.monotonic()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return {"status": "PASS", "pid": pid, "detail": "parent already exited/unavailable"}
        try:
            rc = kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
        finally:
            kernel32.CloseHandle(handle)
        if rc == WAIT_OBJECT_0:
            return {"status": "PASS", "pid": pid, "wait_seconds": round(time.monotonic() - started, 3)}
        if rc == WAIT_TIMEOUT:
            raise TimeoutError(f"parent process {pid} did not exit within {timeout_seconds}s")
        raise RuntimeError(f"WaitForSingleObject failed: code={rc}")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return {"status": "PASS", "pid": pid, "wait_seconds": round(time.monotonic() - started, 3)}
        time.sleep(0.2)
    raise TimeoutError(f"parent process {pid} did not exit within {timeout_seconds}s")

def _write(path: str | None, value: dict[str, Any]) -> None:
    if not path:
        return
    atomic_json(Path(path), value)


def _console_summary(value: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded ASCII-serializable console view.

    Full evidence, including raw official-source bytes, is written to
    --result-file.  Console output is intentionally compact so Windows hosted
    runners cannot fail after a successful operation merely because their
    active code page cannot encode Chinese text.
    """
    result = {
        "schema": value.get("schema"),
        "status": value.get("status"),
        "mode": value.get("mode"),
        "pid": value.get("pid"),
        "parent_pid": value.get("parent_pid"),
        "parent_pid_match": value.get("parent_pid_match"),
        "updater_exe_sha256": value.get("updater_exe_sha256"),
        "github_sha": value.get("github_sha"),
        "github_run_id": value.get("github_run_id"),
        "version": value.get("version"),
    }
    if value.get("error_type") is not None:
        result["error_type"] = value.get("error_type")
    if value.get("error") is not None:
        result["error"] = str(value.get("error"))[:2000]
    service_result = value.get("service_result")
    if isinstance(service_result, dict):
        result["service_status"] = service_result.get("status")
        result["network_gate"] = service_result.get("network_gate")
        result["crosscheck_status"] = service_result.get("crosscheck_status")
        latest = service_result.get("latest")
        if isinstance(latest, dict):
            result["latest_issue"] = latest.get("issue")
        if service_result.get("draw_count") is not None:
            result["draw_count"] = service_result.get("draw_count")
    return result


def _console_line(value: dict[str, Any]) -> str:
    # ensure_ascii=True makes this safe even on legacy Windows cp1252 consoles.
    return json.dumps(_console_summary(value), ensure_ascii=True, sort_keys=True)


def main() -> int:
    p = argparse.ArgumentParser(prog="GeometryLottoProDLTUpdater")
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--software-self-test", action="store_true")
    modes.add_argument("--data-update", action="store_true")
    modes.add_argument("--data-repair", action="store_true")
    modes.add_argument("--software-update", action="store_true")
    p.add_argument("--result-file")
    p.add_argument("--manifest-url")
    p.add_argument("--target-exe")
    p.add_argument("--current-version", default=APP_VERSION)
    p.add_argument("--wait-parent-pid", type=int, default=0)
    args = p.parse_args()

    mode = (
        "self-test" if args.self_test else
        "software-self-test" if args.software_self_test else
        "data-update" if args.data_update else
        "data-repair" if args.data_repair else
        "software-update"
    )
    out = _metadata(mode)
    try:
        if args.self_test:
            with tempfile.TemporaryDirectory(prefix="dlt-updater-self-") as td:
                from glp.service import self_test as service_self_test
                result = service_self_test(Path(td))
            out.update(status="PASS" if result.get("status") == "PASS" else "FAIL", service_result=result)
        elif args.software_self_test:
            result = software_self_test()
            out.update(status=result["status"], service_result=result)
        elif args.data_update:
            result = LottoService().update()
            out.update(status="PASS" if result.get("network_gate") == "PASS" and result.get("crosscheck_status") == "PASS" else "FAIL", service_result=result)
        elif args.data_repair:
            result = LottoService().repair()
            out.update(status="PASS" if result.get("after", {}).get("status") == "PASS" else "FAIL", service_result=result)
        else:
            if not args.manifest_url or not args.target_exe:
                raise ValueError("--manifest-url and --target-exe are required for software update")
            parent_wait = _wait_for_parent_exit(args.wait_parent_pid) if args.wait_parent_pid else {"status": "SKIPPED"}
            result = run_software_update(args.manifest_url, args.target_exe, args.current_version)
            out.update(status=result["status"], parent_wait=parent_wait, service_result=result)
    except Exception as exc:
        out.update(status="FAIL", error_type=type(exc).__name__, error=str(exc), failed_at=utc_now())
    _write(args.result_file, out)
    print(_console_line(out))
    return 0 if out.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
