from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha256(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--exe",required=True)
    p.add_argument("--evidence",required=True)
    p.add_argument("--marker",required=True)
    a=p.parse_args()
    exe=Path(a.exe); evidence=Path(a.evidence); marker=Path(a.marker)
    if not exe.exists() or not evidence.exists():
        return 2
    value=json.loads(evidence.read_text(encoding="utf-8-sig"))
    buttons=value.get("buttons")
    ok=(
        value.get("status")=="PASS"
        and isinstance(buttons,list) and len(buttons)==4
        and all(x.get("status")=="PASS" and x.get("visual_changed") is True for x in buttons)
    )
    if not ok:
        return 3
    value["exe_sha256"]=sha256(exe)
    value["button_count"]=4
    evidence.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(value["exe_sha256"],encoding="ascii")
    print(json.dumps({"status":"PASS","exe_sha256":value["exe_sha256"],"button_count":4}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
