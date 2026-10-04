from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urljoin, urlparse

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCT = "InvestmentFinancePro"
EXE_NAME = "InvestmentFinancePro.exe"
MONOREPO = "douluo511/Geometry-Lotto-Pro"
MAX_BYTES = 200 * 1024 * 1024
TRUSTED_HOSTS = {
    "github.com", "api.github.com", "raw.githubusercontent.com",
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
}

class UpdateBlocked(RuntimeError):
    pass

def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("strict three-component SemVer required")
    return tuple(int(x) for x in value.split("."))

def _trusted_manifest_url(url: str, repository: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        return False
    return (
        (parsed.hostname == "github.com" and parsed.path.startswith(f"/{repository}/releases/download/"))
        or (parsed.hostname == "raw.githubusercontent.com" and parsed.path.startswith(f"/{repository}/"))
    )

def load_config(root: Path) -> dict:
    path = root / "updater.json"
    if not path.exists():
        raise UpdateBlocked("production updater config missing")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    repository = cfg.get("repository", "")
    if cfg.get("enabled") is not True:
        raise UpdateBlocked("production software update is disabled")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or repository.lower() == MONOREPO.lower():
        raise UpdateBlocked("independent production repository is required")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg.get("trusted_public_key_hex", "")):
        raise UpdateBlocked("trusted production Ed25519 public key is not configured")
    for key in ("current_manifest_url", "next_manifest_url"):
        if not _trusted_manifest_url(cfg.get(key, ""), repository):
            raise ValueError(f"{key} must be trusted HTTPS bound to the production repository")
    return cfg

def verify_manifest(manifest: dict, cfg: dict, *, expected_version: str | None = None, newer_than: str | None = None) -> dict:
    signed = dict(manifest)
    signature = signed.pop("signature", None)
    if not isinstance(signature, str):
        raise ValueError("signed release manifest required")
    canonical = json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(cfg["trusted_public_key_hex"])).verify(
        base64.b64decode(signature, validate=True), canonical
    )
    if signed.get("schema_version") != 1 or signed.get("product") != PRODUCT or signed.get("repository") != cfg["repository"]:
        raise ValueError("release manifest product/repository/schema mismatch")
    version = signed.get("version")
    version_tuple = semver(version)
    if expected_version is not None and version != expected_version:
        raise ValueError("current formal release version mismatch")
    if newer_than is not None and version_tuple <= semver(newer_than):
        raise ValueError("next release must be strictly newer than installed Release N")
    if signed.get("release_id") != "v" + version:
        raise ValueError("release tag/version mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", signed.get("source_sha", "")):
        raise ValueError("exact source commit required")
    artifact = signed.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("release artifact object required")
    expected_url = f"https://github.com/{cfg['repository']}/releases/download/{signed['release_id']}/{EXE_NAME}"
    if artifact.get("name") != EXE_NAME or artifact.get("url") != expected_url:
        raise ValueError("release artifact identity mismatch")
    size = artifact.get("size")
    if type(size) is not int or size < 2 or size > MAX_BYTES:
        raise ValueError("bounded release artifact size required")
    if not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", "")):
        raise ValueError("release artifact SHA-256 required")
    return signed

class ReleaseNetwork:
    def __init__(self, evidence_path: Path):
        self.session = requests.Session()
        self.evidence_path = evidence_path

    def request(self, url: str, *, stream: bool = False):
        for _redirect in range(5):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS or parsed.username or parsed.password or parsed.port:
                raise ValueError("untrusted software-update origin or redirect")
            response = None
            for attempt in range(3):
                try:
                    response = self.session.get(url, timeout=(10, 30), stream=stream, allow_redirects=False)
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        response.close()
                        raise requests.HTTPError(f"retryable status {response.status_code}")
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.evidence_path.open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"url": url, "attempt": attempt + 1, "error": repr(exc)}) + "\n")
                    if attempt == 2:
                        raise
                    time.sleep(0.25 * (2 ** attempt))
            if response is None:
                raise RuntimeError("network response unavailable")
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise ValueError("redirect without Location")
                url = urljoin(url, location)
                continue
            return response
        raise ValueError("software-update redirect limit exceeded")

    def json(self, url: str) -> dict:
        with self.request(url, stream=True) as response:
            payload = bytearray()
            for chunk in response.iter_content(65536):
                payload.extend(chunk)
                if len(payload) > 1024 * 1024:
                    raise ValueError("release metadata too large")
        obj = json.loads(payload)
        if not isinstance(obj, dict):
            raise ValueError("release metadata object required")
        return obj

    def download(self, url: str, target: Path, expected_size: int) -> None:
        received = 0
        with self.request(url, stream=True) as response, target.open("wb") as stream:
            for chunk in response.iter_content(65536):
                received += len(chunk)
                if received > expected_size or received > MAX_BYTES:
                    raise ValueError("release artifact exceeds declared size")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if received != expected_size:
            raise ValueError("release artifact truncated")

def _resolve_release_tag(cfg: dict, signed: dict, network) -> None:
    release = network.json(f"https://api.github.com/repos/{cfg['repository']}/releases/tags/{signed['release_id']}")
    if release.get("draft") is not False or release.get("prerelease") is not False or release.get("tag_name") != signed["release_id"]:
        raise ValueError("formal non-draft production Release required")
    assets = [x for x in release.get("assets", []) if x.get("name") == EXE_NAME]
    if len(assets) != 1 or assets[0].get("browser_download_url") != signed["artifact"]["url"] or assets[0].get("size") != signed["artifact"]["size"]:
        raise ValueError("formal Release asset mismatch")
    obj = network.json(f"https://api.github.com/repos/{cfg['repository']}/git/ref/tags/{signed['release_id']}").get("object", {})
    for _ in range(5):
        if obj.get("type") == "commit":
            if obj.get("sha") != signed["source_sha"]:
                raise ValueError("formal release tag source commit mismatch")
            return
        if obj.get("type") != "tag" or not re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")):
            raise ValueError("formal release tag cannot resolve to exact source")
        obj = network.json(f"https://api.github.com/repos/{cfg['repository']}/git/tags/{obj['sha']}").get("object", {})
    raise ValueError("annotated release tag resolution limit exceeded")

def release_context(cfg: dict, current_version: str, current_source: str, target: Path, network) -> dict:
    current = verify_manifest(network.json(cfg["current_manifest_url"]), cfg, expected_version=current_version)
    if current.get("source_sha") != current_source:
        raise ValueError("installed source is not formal Release N source")
    if current["artifact"]["sha256"] != digest(target) or current["artifact"]["size"] != target.stat().st_size:
        raise ValueError("installed Exact EXE is not formal Release N bytes")
    _resolve_release_tag(cfg, current, network)
    nxt = verify_manifest(network.json(cfg["next_manifest_url"]), cfg, newer_than=current_version)
    _resolve_release_tag(cfg, nxt, network)
    return nxt

class InstallLock:
    def __init__(self, path: Path):
        self.path = path
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0)
        if self.stream.read(1) == b"":
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self
    def __exit__(self, *args):
        self.stream.close()

def wait_parent(pid: int | None, timeout_seconds: int = 300) -> None:
    if pid is None:
        return
    if os.name != "nt" or pid == os.getpid():
        raise ValueError("separate Windows application PID required")
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise OSError("cannot validate application process")
    try:
        if kernel.WaitForSingleObject(handle, timeout_seconds * 1000) != 0:
            raise TimeoutError("application did not exit before replacement")
    finally:
        kernel.CloseHandle(handle)

def _restore(target: Path, backup: Path, old_hash: str) -> None:
    if not backup.is_file() or digest(backup) != old_hash:
        raise RuntimeError("trusted rollback backup unavailable")
    temp = target.with_suffix(".rollback.tmp")
    shutil.copy2(backup, temp)
    os.replace(temp, target)
    if digest(target) != old_hash:
        raise RuntimeError("rollback hash mismatch")

def recover(target: Path, journal: Path) -> bool:
    if not journal.exists():
        return False
    state = json.loads(journal.read_text(encoding="utf-8"))
    if state.get("stage") not in {"PREPARED", "REPLACED", "ROLLBACK_FAILED"}:
        return False
    backup = journal.parent / "previous.exe"
    if state.get("target") != str(target) or state.get("backup") != str(backup):
        raise RuntimeError("untrusted recovery journal path")
    _restore(target, backup, state["old_sha256"])
    atomic_json(journal, {**state, "stage": "RECOVERED"})
    return True

def health(target: Path, root: Path, expected: dict) -> None:
    report = root / "evidence" / "post_update_self_test.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["INVESTMENT_FINANCE_ROOT"] = str(root)
    completed = subprocess.run(
        [str(target), "--self-test", "--report", str(report)],
        env=env, timeout=90, capture_output=True,
    )
    if completed.returncode != 0 or not report.exists():
        raise RuntimeError("updated Exact EXE self-test failed")
    obj = json.loads(report.read_text(encoding="utf-8-sig"))
    if obj.get("status") != "PASS" or digest(target) != expected["sha256"]:
        raise RuntimeError("updated Exact EXE health/hash identity mismatch")

def apply_update(target: Path, root: Path, cfg: dict, current_version: str, current_source: str, network, *, parent_pid: int | None = None, health_check=health) -> dict:
    target = target.resolve()
    if target.name != EXE_NAME or not target.is_file() or target.is_symlink():
        raise ValueError(f"trusted local {EXE_NAME} required")
    update_dir = target.parent / ".investment-finance-updates"
    update_dir.mkdir(exist_ok=True)
    journal = update_dir / "journal.json"
    with InstallLock(update_dir / "install.lock"):
        wait_parent(parent_pid)
        recover(target, journal)
        old_hash = digest(target)
        manifest = release_context(cfg, current_version, current_source, target, network)
        staged = update_dir / "download.exe"
        backup = update_dir / "previous.exe"
        try:
            network.download(manifest["artifact"]["url"], staged, manifest["artifact"]["size"])
            if staged.stat().st_size != manifest["artifact"]["size"] or digest(staged) != manifest["artifact"]["sha256"]:
                raise ValueError("downloaded release size/hash mismatch")
            with staged.open("rb") as stream:
                if stream.read(2) != b"MZ":
                    raise ValueError("downloaded release is not a Windows executable")
            shutil.copy2(target, backup)
            if digest(backup) != old_hash:
                raise RuntimeError("backup hash mismatch")
            state = {
                "stage": "PREPARED", "target": str(target), "backup": str(backup),
                "old_sha256": old_hash, "old_version": current_version,
                "old_source_sha": current_source, "new_version": manifest["version"],
                "new_source_sha": manifest["source_sha"], "new_sha256": manifest["artifact"]["sha256"],
            }
            atomic_json(journal, state)
            os.replace(staged, target)
            atomic_json(journal, {**state, "stage": "REPLACED"})
            health_check(target, root, {"version": manifest["version"], "source_sha": manifest["source_sha"], "sha256": manifest["artifact"]["sha256"]})
            atomic_json(journal, {**state, "stage": "COMMITTED"})
            return {
                "status": "PASS", "stage": "COMMITTED", "version": manifest["version"],
                "source_sha": manifest["source_sha"], "sha256": manifest["artifact"]["sha256"],
                "backup_sha256": old_hash,
            }
        except Exception as exc:
            if backup.exists() and digest(target) != old_hash:
                try:
                    _restore(target, backup, old_hash)
                    atomic_json(journal, {
                        "stage": "ROLLED_BACK", "target": str(target), "backup": str(backup),
                        "old_sha256": old_hash, "error": repr(exc),
                    })
                except Exception as rollback_exc:
                    atomic_json(journal, {
                        "stage": "ROLLBACK_FAILED", "target": str(target), "backup": str(backup),
                        "old_sha256": old_hash, "error": repr(exc), "rollback_error": repr(rollback_exc),
                    })
                    raise RuntimeError("software update failed and rollback needs recovery") from rollback_exc
                raise RuntimeError("software update failed; previous application restored") from exc
            raise
        finally:
            staged.unlink(missing_ok=True)

def self_test() -> dict:
    checks = {}
    for good in ("0.0.0", "0.4.0", "10.20.30"):
        checks[f"semver:{good}"] = semver(good) >= (0, 0, 0)
    for bad in ("v0.4.0", "0.4", "01.2.3", "1.2.3-beta"):
        try:
            semver(bad)
            checks[f"reject:{bad}"] = False
        except ValueError:
            checks[f"reject:{bad}"] = True
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        try:
            load_config(Path(td))
            checks["missing_config_blocked"] = False
        except UpdateBlocked:
            checks["missing_config_blocked"] = True
    return {"status": "PASS" if all(checks.values()) else "FAIL", "product": PRODUCT, "checks": checks}
