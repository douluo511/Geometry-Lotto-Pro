from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"StockAIPro/recovered_exact/IMPORT_BYTE_MANIFEST.json"

def git_blob_sha(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

def main()->int:
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    files=manifest.get("files") or []
    if len(files)!=187:
        raise RuntimeError(f"immutable denominator drift: {len(files)}")
    restored=0
    for entry in files:
        rel=str(entry["path"])
        raw=subprocess.check_output(["git","show",f"HEAD:{rel}"],cwd=ROOT)
        if len(raw)!=int(entry["bytes"]):
            raise RuntimeError(f"git blob byte length mismatch before restore: {rel}")
        if hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise RuntimeError(f"git blob sha256 mismatch before restore: {rel}")
        if git_blob_sha(raw)!=entry["git_blob"]:
            raise RuntimeError(f"git blob identity mismatch before restore: {rel}")
        path=ROOT/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        restored+=1
    print(json.dumps({"status":"PASS","restored_files":restored,"method":"git-show-binary-to-write_bytes"}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
