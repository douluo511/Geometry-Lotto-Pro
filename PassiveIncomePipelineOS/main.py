from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
from app.build_info import PRODUCT,SOURCE_SHA,VERSION
from app.service import PipelineService
from app.storage import Storage
from app.ui import UI

def exe_hash():
    p=Path(sys.executable)
    return hashlib.sha256(p.read_bytes()).hexdigest() if getattr(sys,"frozen",False) and p.is_file() else None

def main():
    p=argparse.ArgumentParser();p.add_argument("--root");p.add_argument("--self-test",action="store_true");p.add_argument("--health-report");p.add_argument("--health-nonce");p.add_argument("--ui-self-test",action="store_true");a=p.parse_args()
    root=Path(a.root or os.environ.get("PASSIVE_INCOME_ROOT","userdata")).resolve();svc=PipelineService(root)
    if a.self_test:
        r=svc.self_test();r.update({"product":PRODUCT,"version":VERSION,"source_sha":SOURCE_SHA,"exe_sha256":exe_hash(),"nonce":a.health_nonce})
        if a.health_report:Storage.atomic_json(Path(a.health_report),r)
        print(json.dumps(r,ensure_ascii=False));return 0 if r.get("status")=="PASS" else 2
    if a.ui_self_test:
        ui=UI(svc);r={"status":"PASS","title":ui.root.title(),"buttons":["收益总览","一键更新","一键修复","高级分析"]};ui.root.update_idletasks();ui.root.destroy();print(json.dumps(r,ensure_ascii=False));return 0
    UI(svc).run();return 0
if __name__=="__main__":raise SystemExit(main())
