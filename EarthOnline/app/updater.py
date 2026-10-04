from __future__ import annotations
import argparse,json
from pathlib import Path
from .storage import Storage
def check_context(root):
    p=Path(root)/"updater.json"
    if not p.is_file():return {"status":"BLOCKED","reason":"independent production repository/release/signing context unavailable"}
    x=json.loads(p.read_text(encoding="utf-8"))
    if x.get("enabled") is not True:return {"status":"BLOCKED","reason":"production updater disabled"}
    if x.get("repository") in {None,"","douluo511/Geometry-Lotto-Pro"}:return {"status":"BLOCKED","reason":"shared monorepo cannot satisfy updater identity"}
    if not x.get("manifest_url") or not x.get("trusted_public_key_hex"):return {"status":"FAIL","reason":"incomplete updater trust config"}
    return {"status":"NOT VERIFIED","reason":"real Release N→N+1 not executed"}
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",required=True);p.add_argument("--self-test",action="store_true");a=p.parse_args()
    root=Path(a.root).resolve();root.mkdir(parents=True,exist_ok=True);r=check_context(root);Storage.atomic_json(root/"updater_result.json",r);print(json.dumps(r,ensure_ascii=False))
    if a.self_test and r["status"]=="BLOCKED":return 0
    return 3 if r["status"]=="BLOCKED" else (0 if r["status"]=="PASS" else 2)
if __name__=="__main__":raise SystemExit(main())
