from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
from app.build_info import PRODUCT,SOURCE_SHA,VERSION
from app.service import MasterService
from app.storage import Storage
from app.ui import MasterUI

def exe_hash():
    p=Path(sys.executable)
    return hashlib.sha256(p.read_bytes()).hexdigest() if getattr(sys,"frozen",False) and p.is_file() else None

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--root"); p.add_argument("--self-test",action="store_true"); p.add_argument("--health-report"); p.add_argument("--health-nonce"); p.add_argument("--ui-self-test",action="store_true")
    a=p.parse_args(); root=Path(a.root or os.environ.get("BE_YOUR_OWN_MASTER_ROOT","userdata")).resolve(); svc=MasterService(root)
    if a.self_test:
        result=svc.self_test()
        result.update({"product":PRODUCT,"version":VERSION,"source_sha":SOURCE_SHA,"exe_sha256":exe_hash(),"nonce":a.health_nonce})
        if a.health_report: Storage.atomic_json(Path(a.health_report),result)
        print(json.dumps(result,ensure_ascii=False)); return 0 if result.get("status")=="PASS" else 2
    if a.ui_self_test:
        ui=MasterUI(svc); result={"status":"PASS","title":ui.root.title(),"buttons":["核心训练","一键更新","一键修复","高级分析"]}
        ui.root.update_idletasks(); ui.root.destroy(); print(json.dumps(result,ensure_ascii=False)); return 0
    MasterUI(svc).run(); return 0

if __name__=="__main__": raise SystemExit(main())
