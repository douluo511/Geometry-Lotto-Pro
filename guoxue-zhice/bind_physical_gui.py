from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--exe",required=True); p.add_argument("--evidence",required=True); a=p.parse_args()
    exe=Path(a.exe); path=Path(a.evidence); report=json.loads(path.read_text(encoding="utf-8-sig")); buttons=report.get("buttons") or []
    ok=str(report.get("status","")).upper()=="PASS" and len(buttons)==4 and all(str(x.get("status","")).upper()=="PASS" and x.get("visual_changed") is True for x in buttons)
    if not ok: return 2
    report["schema"]="guoxue-physical-gui-bound-v1"; report["github_sha"]=os.environ.get("GITHUB_SHA"); report["exe_sha256"]=sha256(exe)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({"status":"PASS","github_sha":report["github_sha"],"exe_sha256":report["exe_sha256"],"button_count":4}))
    return 0
if __name__=="__main__": raise SystemExit(main())
