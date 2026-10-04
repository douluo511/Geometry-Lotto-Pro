from __future__ import annotations
from pathlib import Path
import base64, hashlib, json, os, shutil, stat, urllib.parse, urllib.request, zipfile, time
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

UPDATER_VERSION = "1.2.0"
MAX_ARCHIVE_FILES = 5000
MAX_UNCOMPRESSED_BYTES = 1_500_000_000
MAX_COMPRESSION_RATIO = 5000.0
MAX_DOWNLOAD_BYTES = 1_000_000_000


def _atomic_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="\n") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _ensure_free_space(path: Path, needed_bytes: int, multiplier: float=2.2):
    path.mkdir(parents=True, exist_ok=True)
    free=shutil.disk_usage(path).free
    required=max(50_000_000,int(max(0,needed_bytes)*multiplier))
    if free<required:
        raise RuntimeError(f"磁盘空间不足: free={free}, required={required}")
    return free

def _verify_internal_package_manifest(src: Path):
    p=src/"PACKAGE_MANIFEST.json"
    if not p.exists():
        raise ValueError("update missing PACKAGE_MANIFEST.json")
    m=json.loads(p.read_text(encoding="utf-8"))
    files=m.get("files") or {}
    if not isinstance(files,dict) or not files:
        raise ValueError("internal package manifest has no controlled files")
    for name,expected in files.items():
        f=_safe_target(src,str(name))
        if not f.is_file(): raise ValueError("internal manifest missing file: "+str(name))
        if sha256(f)!=str(expected).lower(): raise ValueError("internal manifest hash mismatch: "+str(name))
    if int(m.get("file_count",len(files)))!=len(files):
        raise ValueError("internal package manifest file_count mismatch")
    return True

def canonical_manifest(m):
    x = {k: v for k, v in m.items() if k != "signature"}
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest_signature(m, public_key_pem: bytes):
    sig = base64.b64decode(m.get("signature", ""), validate=True)
    pub = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(pub, Ed25519PublicKey):
        raise ValueError("Updater public key is not Ed25519")
    pub.verify(sig, canonical_manifest(m))
    return True


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def version_tuple(v):
    parts = []
    for part in str(v).lstrip("v").split(".")[:3]:
        digits = "".join(c for c in part if c.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def release_id(manifest: dict) -> str:
    rid = str(manifest.get("release_id") or "").strip()
    if rid:
        return rid
    # Legacy signed manifests remain usable but still get a deterministic identity.
    return f"legacy:{manifest.get('version')}:{str(manifest.get('sha256',''))[:16]}"


def validate_manifest(m: dict):
    for key in ["version", "package_url", "sha256"]:
        if not m.get(key):
            raise ValueError(f"manifest missing {key}")
    digest = str(m["sha256"]).lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("manifest sha256 invalid")
    size = int(m.get("size", 0) or 0)
    if size < 0:
        raise ValueError("manifest size invalid")
    if size > MAX_DOWNLOAD_BYTES:
        raise ValueError("manifest package exceeds download safety limit")
    min_updater = str(m.get("min_updater_version") or "1.0.0")
    if version_tuple(min_updater) > version_tuple(UPDATER_VERSION):
        raise RuntimeError(f"此更新要求 Updater>={min_updater}，当前={UPDATER_VERSION}")
    url = str(m["package_url"])
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in {"https", "file", "relative"}:
        raise ValueError("package_url must use HTTPS/file/relative scheme")
    return True


def _safe_target(base: Path, name: str):
    target = (base / name).resolve()
    base = base.resolve()
    if target != base and base not in target.parents:
        raise ValueError("unsafe archive path: " + name)
    return target


def safe_extract(zpath: Path, dest: Path, max_files: int = MAX_ARCHIVE_FILES,
                 max_uncompressed_bytes: int = MAX_UNCOMPRESSED_BYTES,
                 max_ratio: float = MAX_COMPRESSION_RATIO):
    with zipfile.ZipFile(zpath) as z:
        infos = z.infolist()
        if len(infos) > int(max_files):
            raise ValueError("archive contains too many files")
        total = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("unsafe archive member: " + name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError("archive symlink is not allowed: " + name)
            _safe_target(dest, name)
            total += int(info.file_size)
            if total > int(max_uncompressed_bytes):
                raise ValueError("archive uncompressed size exceeds safety limit")
            if info.compress_size > 0 and info.file_size / info.compress_size > float(max_ratio):
                raise ValueError("archive compression ratio exceeds safety limit")
        z.extractall(dest)


def read_current(root: Path):
    return json.loads((root / "current.json").read_text(encoding="utf-8"))


def write_current(root: Path, obj):
    p = root / "current.json"
    _atomic_write_text(p, json.dumps(obj, ensure_ascii=False, indent=2))


def _write_journal(root: Path, state: str, **detail):
    p = root / "staging" / "update_journal.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    obj = {"state": state, "updater_version": UPDATER_VERSION, "updated_at_unix": time.time(), **detail}
    _atomic_write_text(p, json.dumps(obj, ensure_ascii=False, indent=2))
    return obj


def _pending_manifest_path(root: Path):
    return root / "staging" / "pending_release.json"


def _read_pending_manifest(root: Path):
    p = _pending_manifest_path(root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _record_failed_release(cur: dict, rid: str):
    failed = [str(x) for x in (cur.get("failed_release_ids") or []) if x]
    if rid and rid not in failed:
        failed.append(rid)
    cur["failed_release_ids"] = failed[-50:]


def local_file_path(url: str) -> Path:
    """Resolve local offline fixtures, including the legacy Windows URI form.

    Production web requests keep their separate HTTPS validation. File transport
    does not admit remote hosts or query/fragment interpretation.
    """
    parsed = urllib.parse.urlsplit(str(url))
    if parsed.scheme.lower() != "file" or parsed.query or parsed.fragment:
        raise ValueError("invalid local file URI")
    if os.name == "nt" and len(parsed.netloc) > 1 and parsed.netloc[1] == ":":
        # Existing fixture tests use file://C:\path instead of Path.as_uri().
        path_text = (parsed.netloc + parsed.path).replace("\\", "/")
    else:
        if parsed.netloc.lower() not in {"", "localhost"}:
            raise ValueError("offline file URI must refer to the local machine")
        path_text = parsed.path
    path = Path(urllib.request.url2pathname(path_text))
    if not path_text or not path.is_absolute():
        raise ValueError("offline file URI requires an absolute path")
    return path


def fetch_manifest(url, timeout=15):
    if url.startswith("file://"):
        return json.loads(local_file_path(url).read_text(encoding="utf-8"))
    if not str(url).lower().startswith("https://"):
        raise ValueError("manifest_url must use HTTPS or file://")
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    if urllib.parse.urlparse(str(r.url)).scheme.lower()!="https":
        raise ValueError("manifest HTTPS request redirected to insecure URL")
    return r.json()


def download(url, dest: Path, timeout=30, root=None):
    if url.startswith("relative://"):
        if root is None:
            raise ValueError("relative URL requires root")
        shutil.copy2(Path(root) / url[len("relative://"):], dest)
        return
    if url.startswith("file://"):
        shutil.copy2(local_file_path(url), dest)
        return
    if not str(url).lower().startswith("https://"):
        raise ValueError("update package must use HTTPS/file/relative")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        if urllib.parse.urlparse(str(r.url)).scheme.lower()!="https":
            raise ValueError("update HTTPS request redirected to insecure URL")
        declared=int(r.headers.get("content-length",0) or 0)
        if declared>MAX_DOWNLOAD_BYTES: raise ValueError("download exceeds safety limit")
        written=0
        with dest.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    written+=len(chunk)
                    if written>MAX_DOWNLOAD_BYTES: raise ValueError("download exceeds safety limit")
                    f.write(chunk)


def _locate_version_root(extracted: Path):
    children = [p for p in extracted.iterdir()]
    return children[0] if len(children) == 1 and children[0].is_dir() else extracted


def stage_update(root: Path, manifest: dict, public_key: bytes):
    verify_manifest_signature(manifest, public_key)
    validate_manifest(manifest)
    ver = str(manifest["version"]).lstrip("v")
    rid = release_id(manifest)
    cur = read_current(root) if (root / "current.json").exists() else {}
    active=str(cur.get("active_version") or "0.0.0")
    if active and version_tuple(ver)<=version_tuple(active):
        raise RuntimeError(f"拒绝自动降级/重复安装: active={active}, candidate={ver}")
    if rid in set(cur.get("failed_release_ids") or []):
        raise RuntimeError("该发布版本此前 Health Check 失败，已阻止自动重复安装")

    staging = root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    _ensure_free_space(staging,int(manifest.get("size",0) or 0))
    pkg = staging / f"{ver}.zip"
    _write_journal(root, "DOWNLOADING", version=ver, release_id=rid)
    download(manifest["package_url"], pkg, root=root)
    expected_size = int(manifest.get("size", pkg.stat().st_size))
    if expected_size and expected_size != pkg.stat().st_size:
        _write_journal(root, "REJECTED", version=ver, release_id=rid, reason="size_mismatch")
        raise ValueError("package size mismatch")
    if sha256(pkg) != str(manifest["sha256"]).lower():
        _write_journal(root, "REJECTED", version=ver, release_id=rid, reason="sha256_mismatch")
        raise ValueError("package sha256 mismatch")

    extracted = staging / f"{ver}.extracted"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir()
    safe_extract(pkg, extracted)
    src = _locate_version_root(extracted)
    for required in ["VERSION", "requirements.txt", "app.py", "stock_ai"]:
        if not (src / required).exists():
            raise ValueError("update missing " + required)
    package_version = (src / "VERSION").read_text(encoding="utf-8").strip().split("-")[0].lstrip("v")
    if version_tuple(package_version) != version_tuple(ver):
        _write_journal(root, "REJECTED", version=ver, release_id=rid, reason="version_mismatch")
        raise ValueError(f"package VERSION mismatch: manifest={ver}, package={package_version}")
    internal_manifest=src/"PACKAGE_MANIFEST.json"
    if int(manifest.get("manifest_schema_version",1) or 1)>=2 or bool(manifest.get("require_internal_manifest",False)):
        _verify_internal_package_manifest(src)
    elif internal_manifest.exists():
        _verify_internal_package_manifest(src)
    _ensure_free_space(root/"versions",sum(f.stat().st_size for f in src.rglob("*") if f.is_file()))

    final = root / "versions" / ver
    temp = root / "versions" / f".{ver}.installing"
    if temp.exists():
        shutil.rmtree(temp)
    shutil.copytree(src, temp)
    if final.exists():
        shutil.rmtree(final)
    os.replace(temp, final)
    pending = {k: v for k, v in manifest.items() if k != "signature"}
    pending["release_id"] = rid
    p = _pending_manifest_path(root)
    _atomic_write_text(p, json.dumps(pending, ensure_ascii=False, indent=2))
    _write_journal(root, "STAGED", version=ver, release_id=rid, package_sha256=manifest["sha256"])
    return ver


def activate_pending(root: Path, version: str):
    cur = read_current(root)
    old = cur.get("active_version")
    pending = _read_pending_manifest(root)
    rid = str(pending.get("release_id") or f"version:{version}")
    nxt = dict(cur)
    nxt.update({
        "active_version": version,
        "previous_version": old,
        "pending_health": True,
        "pending_release_id": rid,
    })
    write_current(root, nxt)
    _write_journal(root, "ACTIVATING", version=version, previous_version=old, release_id=rid)
    return old


def mark_healthy(root: Path):
    cur = read_current(root)
    rid = str(cur.pop("pending_release_id", "") or "")
    cur["pending_health"] = False
    if rid:
        cur["last_accepted_release_id"] = rid
    write_current(root, cur)
    _write_journal(root, "COMMITTED", version=cur.get("active_version"), release_id=rid)
    try:
        _pending_manifest_path(root).unlink()
    except FileNotFoundError:
        pass


def rollback(root: Path, reason: str = "healthcheck_failed"):
    cur = read_current(root)
    prev = cur.get("previous_version")
    if not prev:
        return False
    failed = str(cur.get("pending_release_id") or "")
    nxt = dict(cur)
    if failed:
        _record_failed_release(nxt, failed)
    current_active = cur.get("active_version")
    nxt.update({
        "active_version": prev,
        "previous_version": current_active,
        "pending_health": False,
    })
    nxt.pop("pending_release_id", None)
    write_current(root, nxt)
    _write_journal(root, "ROLLED_BACK", version=current_active, rollback_to=prev,
                   release_id=failed, reason=reason)
    return True


def recover_interrupted_update(root: Path):
    """Recover only states that are provably unusable without guessing health."""
    cur = read_current(root)
    active = str(cur.get("active_version") or "")
    if cur.get("pending_health") and not (root / "versions" / active).exists():
        return rollback(root, reason="active_version_missing_after_interruption")
    return False


def check_and_stage(root: Path, config: dict):
    if not config.get("enabled") or not config.get("manifest_url"):
        return None
    m = fetch_manifest(config["manifest_url"], float(config.get("timeout_seconds", 15)))
    pub = (root / "updater_public_key.pem").read_bytes()
    verify_manifest_signature(m, pub)
    validate_manifest(m)
    cur = read_current(root)
    rid = release_id(m)
    if rid in set(cur.get("failed_release_ids") or []):
        raise RuntimeError("该 release_id 已被本机回滚并列入失败清单，等待新的发布版本")
    if version_tuple(m["version"]) <= version_tuple(cur["active_version"]):
        return None
    return stage_update(root, m, pub)
