from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--exe",required=True); p.add_argument("--evidence",required=True); p.add_argument("--marker",required=True)
    a=p.parse_args(); exe=Path(a.exe); ep=Path(a.evidence)
    if not exe.exists() or not ep.exists(): return 2
    data=json.loads(ep.read_text(encoding="utf-8-sig"))
    data["exe_sha256"]=sha256(exe)
    ep.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    ok=data.get("status")=="PASS" and int(data.get("button_count",0))==4
    if ok: Path(a.marker).write_text("PASS\n",encoding="utf-8")
    print(json.dumps({"status":"PASS" if ok else "FAIL","exe_sha256":data["exe_sha256"],"button_count":data.get("button_count")},ensure_ascii=False))
    return 0 if ok else 3
if __name__=="__main__": raise SystemExit(main())
