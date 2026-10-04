from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, os

def write_receipt(root:Path,name:str,payload:dict)->Path:
    root.mkdir(parents=True,exist_ok=True)
    body={"time":datetime.now(timezone.utc).isoformat(),**payload}
    p=root/name
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(body,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,p)
    return p
