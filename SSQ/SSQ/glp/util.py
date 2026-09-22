from __future__ import annotations
import hashlib,json,os,tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode('utf-8'))
def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path,(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode('utf-8'))
def zscores(values: Iterable[float]) -> list[float]:
    vals=[float(v) for v in values]
    if not vals:return []
    mean=sum(vals)/len(vals); var=sum((v-mean)**2 for v in vals)/len(vals)
    if var <= 1e-15:return [0.0 for _ in vals]
    sd=var**0.5; return [(v-mean)/sd for v in vals]
def app_data_dir() -> Path:
    override=os.environ.get('GLP_DATA_DIR')
    if override:return Path(override).expanduser().resolve()
    base=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))
    return (base/'GeometryLottoPro'/'SSQ').resolve()
def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()+'Z'
