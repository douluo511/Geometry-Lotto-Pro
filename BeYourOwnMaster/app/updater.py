from __future__ import annotations
import argparse, json
from pathlib import Path
from .storage import Storage

def check_context(root:Path)->dict:
    cfg=root/"updater.json"
    if not cfg.is_file(): return {"status":"BLOCKED","reason":"independent production repository/release manifest/trusted signing key not configured"}
    obj=json.loads(cfg.read_text(encoding="utf-8"))
    if obj.get("enabled") is not True: return {"status":"BLOCKED","reason":"production updater disabled"}
    repo=str(obj.get("repository") or "")
    if not repo or repo=="douluo511/Geometry-Lotto-Pro": return {"status":"BLOCKED","reason":"shared monorepo cannot satisfy production updater identity"}
    missing=[x for x in ("manifest_url","trusted_public_key_hex") if not obj.get(x)]
    if missing: return {"status":"FAIL","reason":f"missing updater fields: {missing}"}
    return {"status":"NOT VERIFIED","reason":"real signed Release N→N+1 transaction not executed"}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--root",required=True); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    root=Path(a.root).resolve(); root.mkdir(parents=True,exist_ok=True); result=check_context(root)
    Storage.atomic_json(root/"updater_result.json",result); print(json.dumps(result,ensure_ascii=False))
    if a.self_test and result.get("status")=="BLOCKED": return 0
    return 3 if result.get("status")=="BLOCKED" else (0 if result.get("status")=="PASS" else 2)
if __name__=="__main__": raise SystemExit(main())
