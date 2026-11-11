from __future__ import annotations
import json, os, sys
from pathlib import Path

CURRENT_VERSION="1.0.0-reauthored"
CURRENT_REPOSITORY="douluo511/AI-Music-Production-System"

def main()->int:
    manifest=os.environ.get("AI_MUSIC_RELEASE_MANIFEST")
    if not manifest:
        print(json.dumps({"status":"BLOCKED","reason":"independent production repository/release manifest/trusted signing context not configured"}))
        return 3
    p=Path(manifest)
    if not p.is_file():
        print(json.dumps({"status":"FAIL","reason":"release manifest missing"})); return 2
    try:
        obj=json.loads(p.read_text(encoding="utf-8"))
        required=("repository","version","asset_url","asset_sha256","signature")
        if any(not obj.get(k) for k in required): raise ValueError("manifest fields missing")
        if obj["repository"]!=CURRENT_REPOSITORY: raise ValueError("wrong independent repository")
        if not str(obj["asset_url"]).startswith("https://"): raise ValueError("asset must be https")
        if len(str(obj["asset_sha256"]))!=64: raise ValueError("invalid sha256")
        print(json.dumps({"status":"BLOCKED","reason":"manifest shape verified; cryptographic signer and real N->N+1 release execution still not configured"}))
        return 3
    except Exception as exc:
        print(json.dumps({"status":"FAIL","reason":f"{type(exc).__name__}: {exc}"})); return 2

if __name__=="__main__":
    raise SystemExit(main())
