from __future__ import annotations
from pathlib import Path
import json, os

def data_root() -> Path:
    explicit=os.environ.get("EARTH_ONLINE_DATA_ROOT")
    if explicit: return Path(explicit).expanduser().resolve()
    base=os.environ.get("APPDATA") or str(Path.home())
    return Path(base)/"EarthOnlineLifeBase"

def atomic_json(path:Path,obj:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    os.replace(tmp,path)

def append_record(obj:dict)->Path:
    root=data_root(); path=root/"records"/f'{obj["record_id"]}.json'
    if path.exists(): raise FileExistsError(path)
    atomic_json(path,obj); return path

def list_records()->list[dict]:
    out=[]
    for p in sorted((data_root()/"records").glob("*.json")):
        try: out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception: continue
    return out

def health()->dict:
    root=data_root(); root.mkdir(parents=True,exist_ok=True)
    probe=root/".write_probe"; probe.write_text("ok",encoding="utf-8"); probe.unlink()
    return {"status":"PASS","data_root":str(root),"record_count":len(list_records())}
