from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urljoin, urlparse
import uuid

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


PRODUCT = "RealMoneyFinance"
MAX_BYTES = 150 * 1024 * 1024


class UpdateBlocked(RuntimeError):
    pass


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("strict three-component release SemVer required")
    return tuple(int(part) for part in value.split("."))


def config(root: Path) -> dict:
    path = root / "updater.json"
    if not path.exists():
        raise UpdateBlocked("production updater config missing")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("enabled") is not True or not cfg.get("manifest_url"):
        raise UpdateBlocked("signed production release endpoint is not configured")
    repo = cfg.get("repository", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or repo.lower() == "douluo511/geometry-lotto-pro":
        raise UpdateBlocked("an actual independent production repository is required")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg.get("trusted_public_key_hex", "")):
        raise UpdateBlocked("trusted production Ed25519 public key is not configured")
    parsed = urlparse(cfg["manifest_url"])
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("manifest must use authenticated-origin HTTPS without credentials")
    allowed = parsed.hostname == "github.com" and parsed.path.startswith("/" + repo + "/releases/download/")
    allowed |= parsed.hostname == "raw.githubusercontent.com" and parsed.path.startswith("/" + repo + "/")
    if not allowed:
        raise ValueError("manifest origin must belong to the configured production repository")
    return cfg


def verify_manifest(manifest: dict, cfg: dict, current_version: str | None) -> dict:
    signed = dict(manifest)
    signature = signed.pop("signature", None)
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(cfg["trusted_public_key_hex"])).verify(
        base64.b64decode(signature, validate=True), canonical,
    )
    if signed.get("schema_version") != 1 or signed.get("product") != PRODUCT or signed.get("repository") != cfg["repository"]:
        raise ValueError("signed manifest product/repository/schema identity mismatch")
    version = semver(signed.get("version"))
    if current_version is not None and version <= semver(current_version):
        raise ValueError("release is not a strict N-to-N+1 upgrade")
    if signed.get("release_id") != "v" + signed["version"]:
        raise ValueError("release tag/version identity mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", signed.get("source_sha", "")):
        raise ValueError("exact source commit required")
    artifact = signed.get("artifact", {})
    expected_url = f"https://github.com/{cfg['repository']}/releases/download/{signed['release_id']}/RealMoneyFinance.exe"
    if artifact.get("name") != "RealMoneyFinance.exe" or artifact.get("url") != expected_url:
        raise ValueError("artifact name/release repository mismatch")
    size = artifact.get("size")
    if type(size) is not int or not 2 <= size <= MAX_BYTES or not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", "")):
        raise ValueError("bounded artifact size and SHA-256 required")
    return signed


class ReleaseNetwork:
    """Bounded HTTPS requests with validation before every redirect."""
    def __init__(self, evidence: Path):
        self.session = requests.Session()
        self.evidence = evidence

    def request(self, url: str, *, stream=False):
        trusted_hosts = {"github.com", "api.github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        for redirect in range(5):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in trusted_hosts or parsed.username or parsed.password or parsed.port:
                raise ValueError("untrusted HTTPS redirect/origin")
            for attempt in range(3):
                try:
                    response = self.session.get(url, timeout=(10, 30), stream=stream, allow_redirects=False)
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        response.close()
                        raise requests.HTTPError("retryable HTTP status")
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    self.evidence.parent.mkdir(parents=True, exist_ok=True)
                    with self.evidence.open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"url": url, "attempt": attempt + 1, "error": repr(exc)}) + "\n")
                    if attempt == 2:
                        raise
                    time.sleep(0.25 * 2 ** attempt)
            if response.status_code in (301, 302, 303, 307, 308):
                next_url = urljoin(url, response.headers["Location"])
                response.close()
                url = next_url
                continue
            return response
        raise ValueError("redirect limit exceeded")

    def json(self, url: str) -> dict:
        with self.request(url, stream=True) as response:
            if "json" not in response.headers.get("Content-Type", "").lower() and "raw.githubusercontent.com" not in url:
                raise ValueError("release metadata Content-Type is not JSON")
            payload = bytearray()
            for chunk in response.iter_content(65536):
                payload.extend(chunk)
                if len(payload) > 1024 * 1024:
                    raise ValueError("release metadata is oversized")
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
                    raise ValueError("artifact exceeds declared size")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if received != expected_size:
            raise ValueError("artifact is truncated")


def verify_real_release(cfg: dict, signed: dict, network: ReleaseNetwork) -> None:
    release = network.json(f"https://api.github.com/repos/{cfg['repository']}/releases/tags/{signed['release_id']}")
    if release.get("draft") is not False or release.get("prerelease") is not False or release.get("tag_name") != signed["release_id"]:
        raise ValueError("real formal production Release identity required")
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == "RealMoneyFinance.exe"]
    if len(assets) != 1 or assets[0].get("browser_download_url") != signed["artifact"]["url"] or assets[0].get("size") != signed["artifact"]["size"]:
        raise ValueError("production release asset does not match signed manifest")
    ref = network.json(f"https://api.github.com/repos/{cfg['repository']}/git/ref/tags/{signed['release_id']}")["object"]
    for depth in range(5):
        if ref.get("type") == "commit":
            if ref.get("sha") != signed["source_sha"]:
                raise ValueError("real release tag commit differs from signed exact source")
            return
        if ref.get("type") != "tag" or not re.fullmatch(r"[0-9a-f]{40}", ref.get("sha", "")):
            raise ValueError("release tag does not resolve to a source commit")
        ref = network.json(f"https://api.github.com/repos/{cfg['repository']}/git/tags/{ref['sha']}")["object"]
    raise ValueError("annotated tag resolution limit exceeded")


def release_context(cfg: dict, current_version: str, network: ReleaseNetwork,
                    current_source: str, current_hash: str, current_size: int) -> dict:
    old_url = f"https://github.com/{cfg['repository']}/releases/download/v{current_version}/release-manifest.json"
    previous = verify_manifest(network.json(old_url), cfg, None)
    if previous["version"] != current_version or previous["source_sha"] != current_source or previous["artifact"]["sha256"] != current_hash or previous["artifact"]["size"] != current_size:
        raise ValueError("current Exact EXE is not the formally signed production Release N")
    verify_real_release(cfg, previous, network)
    signed = verify_manifest(network.json(cfg["manifest_url"]), cfg, current_version)
    verify_real_release(cfg, signed, network)
    return signed


def wait_parent(pid: int | None, timeout=300) -> None:
    if not pid:
        return
    if os.name != "nt" or pid == os.getpid():
        raise ValueError("separate Windows parent process required")
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
        raise OSError("cannot validate/wait for parent process")
    try:
        if kernel.WaitForSingleObject(handle, timeout * 1000) != 0:
            raise TimeoutError("application did not close before update")
    finally:
        kernel.CloseHandle(handle)


def health(target: Path, root: Path, expected: dict) -> None:
    nonce = uuid.uuid4().hex
    report = root / "evidence" / ("update-health-" + nonce + ".json")
    env = os.environ.copy()
    env["REAL_MONEY_FINANCE_ROOT"] = str(root)
    completed = subprocess.run([str(target), "--self-test", "--health-report", str(report), "--health-nonce", nonce],
                               env=env, timeout=60, capture_output=True)
    if completed.returncode != 0 or not report.exists():
        raise RuntimeError("updated Exact EXE did not produce a successful health report")
    obj = json.loads(report.read_text(encoding="utf-8"))
    required = {"status": "PASS", "product": PRODUCT, "storage_integrity": "ok", "nonce": nonce,
                "version": expected["version"], "source_sha": expected["source_sha"], "exe_sha256": expected["sha256"]}
    if any(obj.get(key) != value for key, value in required.items()) or digest(target) != expected["sha256"]:
        raise RuntimeError("updated EXE health/version/source/hash identity mismatch")


def launch(target: Path, root: Path, expected: dict) -> dict:
    nonce = uuid.uuid4().hex
    ack = root / "evidence" / ("startup-" + nonce + ".json")
    env = os.environ.copy()
    env["REAL_MONEY_FINANCE_ROOT"] = str(root)
    process = subprocess.Popen([str(target), "--startup-ack", str(ack), "--startup-nonce", nonce],
                               cwd=str(target.parent), env=env)
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("application exited before a verified GUI startup acknowledgment")
            if ack.exists():
                obj = json.loads(ack.read_text(encoding="utf-8"))
                required = {"status": "PASS", "product": PRODUCT, "nonce": nonce, "gui_mapped": True,
                            "version": expected["version"], "source_sha": expected["source_sha"], "exe_sha256": expected["sha256"]}
                if any(obj.get(key) != value for key, value in required.items()) or digest(target) != expected["sha256"]:
                    raise RuntimeError("GUI startup product/version/source/hash/nonce identity mismatch")
                return obj
            time.sleep(0.1)
        raise TimeoutError("application GUI startup acknowledgment was not produced")
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        raise


class InstallLock:
    def __init__(self, path):
        self.path = path
    def __enter__(self):
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


def restore(target: Path, backup: Path, expected_hash: str) -> None:
    if digest(backup) != expected_hash:
        raise RuntimeError("backup identity corrupt; rollback cannot be accepted")
    temporary = target.with_suffix(".rollback.tmp")
    shutil.copy2(backup, temporary)
    os.replace(temporary, target)
    if digest(target) != expected_hash:
        raise RuntimeError("restored EXE identity mismatch")


def recover(target: Path, journal: Path) -> dict | None:
    if not journal.exists():
        return
    previous = json.loads(journal.read_text(encoding="utf-8"))
    if previous.get("stage") in ("PREPARED", "REPLACED", "ROLLBACK_FAILED"):
        expected_backup = journal.parent / "previous.exe"
        if previous.get("target") != str(target) or previous.get("backup") != str(expected_backup):
            raise RuntimeError("untrusted recovery journal path")
        restore(target, expected_backup, previous["old_sha256"])
        atomic_json(journal, {**previous, "stage": "RECOVERED"})
        return previous


def apply_update(target: Path, root: Path, cfg: dict, current_version: str, current_source: str,
                 network: ReleaseNetwork, *, parent_pid=None, health_check=health, launch_app=launch) -> dict:
    target = target.resolve()
    if target.name != "RealMoneyFinance.exe" or not target.is_file() or target.is_symlink():
        raise ValueError("trusted local RealMoneyFinance.exe installation target required")
    update_dir = target.parent / ".rmf-updates"
    update_dir.mkdir(exist_ok=True)
    journal = update_dir / "journal.json"
    with InstallLock(update_dir / "install.lock"):
        wait_parent(parent_pid)
        recovered = recover(target, journal)
        if recovered:
            current_version = recovered.get("old_version", current_version)
            current_source = recovered.get("old_source_sha", current_source)
        initial_hash = digest(target)
        try:
            manifest = release_context(cfg, current_version, network, current_source, initial_hash, target.stat().st_size)
            failed_path = update_dir / "failed_release_ids.json"
            failed = json.loads(failed_path.read_text(encoding="utf-8")) if failed_path.exists() else {"ids": []}
            if manifest["release_id"] in failed["ids"]:
                raise UpdateBlocked("previously failed release is quarantined")
        except Exception:
            if parent_pid:
                health_check(target, root, {"version": current_version, "source_sha": current_source, "sha256": initial_hash})
                launch_app(target, root, {"version": current_version, "source_sha": current_source, "sha256": initial_hash})
            raise
        staged = update_dir / "download.exe"
        backup = update_dir / "previous.exe"
        transaction_started = False
        try:
            network.download(manifest["artifact"]["url"], staged, manifest["artifact"]["size"])
            with staged.open("rb") as artifact_stream:
                header = artifact_stream.read(2)
            if staged.stat().st_size != manifest["artifact"]["size"] or digest(staged) != manifest["artifact"]["sha256"] or header != b"MZ":
                raise ValueError("downloaded Windows artifact/hash identity mismatch")
            old_hash = digest(target)
            shutil.copy2(target, backup)
            if digest(backup) != old_hash:
                raise RuntimeError("backup hash mismatch")
            state = {"target": str(target), "backup": str(backup), "old_sha256": old_hash,
                     "old_version": current_version, "old_source_sha": current_source,
                     "release_id": manifest["release_id"], "source_sha": manifest["source_sha"],
                     "new_version": manifest["version"], "new_sha256": manifest["artifact"]["sha256"],
                     "startup_verified": False, "stage": "PREPARED"}
            atomic_json(journal, state)
            try:
                transaction_started = True
                os.replace(staged, target)
                state["stage"] = "REPLACED"
                atomic_json(journal, state)
                expected = {"version": manifest["version"], "source_sha": manifest["source_sha"], "sha256": manifest["artifact"]["sha256"]}
                health_check(target, root, expected)
                state["stage"] = "COMMITTED"
                atomic_json(journal, state)
            except Exception as exc:
                failed["ids"] = sorted(set([*failed["ids"], manifest["release_id"]]))
                atomic_json(failed_path, failed)
                try:
                    restore(target, backup, old_hash)
                    health_check(target, root, {"version": current_version, "source_sha": current_source, "sha256": old_hash})
                    atomic_json(journal, {**state, "stage": "ROLLED_BACK", "error": repr(exc)})
                    launch_app(target, root, {"version": current_version, "source_sha": current_source, "sha256": old_hash})
                except Exception as rollback_exc:
                    atomic_json(journal, {**state, "stage": "ROLLBACK_FAILED", "error": repr(exc), "rollback_error": repr(rollback_exc)})
                    raise RuntimeError("update failed and rollback needs recovery") from rollback_exc
                raise RuntimeError("update failed; previous application restored and health-checked") from exc
            try:
                startup = launch_app(target, root, expected)
                if not isinstance(startup, dict) or startup.get("status") != "PASS":
                    raise RuntimeError("post-commit GUI startup has no verified acknowledgment")
                atomic_json(journal, {**state, "stage": "STARTED", "startup_verified": True})
            except Exception as startup_exc:
                atomic_json(journal, {**state, "stage": "STARTUP_FAILED", "startup_verified": False,
                                      "error": repr(startup_exc)})
                raise RuntimeError("post-commit GUI startup failed; healthy committed version retained for recovery") from startup_exc
            return {"status": "PASS", "version": manifest["version"], "source_sha": manifest["source_sha"],
                    "exe_sha256": digest(target), "release_id": manifest["release_id"], "repository": cfg["repository"],
                    "startup_verified": True}
        except Exception:
            if parent_pid and not transaction_started:
                health_check(target, root, {"version": current_version, "source_sha": current_source, "sha256": initial_hash})
                launch_app(target, root, {"version": current_version, "source_sha": current_source, "sha256": initial_hash})
            raise
        finally:
            staged.unlink(missing_ok=True)
