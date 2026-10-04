from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
IMMUTABLE_MANIFEST=ROOT/"StockAIPro/recovered_exact/IMPORT_BYTE_MANIFEST.json"
PACKAGE_MANIFESTS=(
    ROOT/"StockAIPro/staging/Stock_AI_Pro/PACKAGE_MANIFEST.json",
    ROOT/"StockAIPro/staging/Stock_AI_Pro/versions/4.3.0/PACKAGE_MANIFEST.json",
)

def git_blob_sha(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

def git_bytes(rel:str)->bytes:
    return subprocess.check_output(["git","show",f"HEAD:{rel}"],cwd=ROOT)

def restore_rel(rel:str, expected_sha256:str|None=None, expected_bytes:int|None=None, expected_blob:str|None=None)->None:
    raw=git_bytes(rel)
    if expected_bytes is not None and len(raw)!=int(expected_bytes):
        raise RuntimeError(f"git blob byte length mismatch before restore: {rel}")
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest()!=expected_sha256:
        raise RuntimeError(f"git blob sha256 mismatch before restore: {rel}")
    if expected_blob is not None and git_blob_sha(raw)!=expected_blob:
        raise RuntimeError(f"git blob identity mismatch before restore: {rel}")
    path=ROOT/rel
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)

def restore_immutable_archive()->int:
    manifest=json.loads(IMMUTABLE_MANIFEST.read_text(encoding="utf-8"))
    files=manifest.get("files") or []
    if len(files)!=187:
        raise RuntimeError(f"immutable denominator drift: {len(files)}")
    for entry in files:
        restore_rel(
            str(entry["path"]),
            expected_sha256=str(entry["sha256"]),
            expected_bytes=int(entry["bytes"]),
            expected_blob=str(entry["git_blob"]),
        )
    return len(files)

def restore_package_manifest_files(manifest_path:Path)->int:
    obj=json.loads(manifest_path.read_text(encoding="utf-8"))
    files=obj.get("files")
    if not isinstance(files,dict) or not files:
        raise RuntimeError(f"empty package manifest: {manifest_path}")
    base=manifest_path.parent
    restored=0
    for rel, expected in files.items():
        if not isinstance(rel,str) or not isinstance(expected,str) or len(expected)!=64:
            raise RuntimeError(f"invalid package manifest entry: {manifest_path}:{rel!r}")
        target=(base/rel).resolve()
        target.relative_to(ROOT.resolve())
        repo_rel=target.relative_to(ROOT).as_posix()
        restore_rel(repo_rel, expected_sha256=expected.lower())
        restored+=1
    return restored

def main()->int:
    immutable=restore_immutable_archive()
    package_counts={}
    for manifest in PACKAGE_MANIFESTS:
        package_counts[manifest.relative_to(ROOT).as_posix()]=restore_package_manifest_files(manifest)
    print(json.dumps({
        "status":"PASS",
        "immutable_restored_files":immutable,
        "package_manifest_restored_files":package_counts,
        "method":"git-show-binary-to-write_bytes",
    },sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
