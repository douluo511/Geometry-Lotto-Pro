from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json
from .storage import data_root, atomic_json

def sha256_bytes(data:bytes)->str: return hashlib.sha256(data).hexdigest()

def record(name:str,payload:dict)->Path:
    body={"schema":"earth-online-evidence-v1","recorded_at":datetime.now(timezone.utc).isoformat(),**payload}
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,default=str).encode("utf-8")
    body["payload_sha256"]=sha256_bytes(raw)
    path=data_root()/"evidence"/name
    atomic_json(path,body)
    return path
