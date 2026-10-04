from __future__ import annotations
import json,os,tempfile
from pathlib import Path

class Storage:
    def __init__(self,root:Path):
        self.root=Path(root);self.canonical=self.root/"canonical";self.evidence=self.root/"evidence"
        for p in (self.canonical,self.evidence):p.mkdir(parents=True,exist_ok=True)
    @staticmethod
    def atomic_bytes(path:Path,data:bytes):
        path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
        try:
            with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            try:Path(tmp).unlink(missing_ok=True)
            except OSError:pass
    @classmethod
    def atomic_json(cls,path:Path,obj):
        cls.atomic_bytes(path,(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode())
    def append(self,obj:dict):
        p=self.canonical/"pipeline_runs.jsonl"
        with p.open("a",encoding="utf-8") as f:f.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+"\n");f.flush();os.fsync(f.fileno())
    def records(self):
        p=self.canonical/"pipeline_runs.jsonl"
        if not p.exists():return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    def repair(self):
        p=self.canonical/"pipeline_runs.jsonl";q=None
        if p.exists():
            try:self.records()
            except Exception as exc:
                q=self.evidence/"quarantined-pipeline-runs.jsonl";self.atomic_bytes(q,p.read_bytes());p.unlink()
                self.atomic_json(self.evidence/"repair_fault.json",{"status":"PASS","reason":repr(exc),"quarantined":str(q)})
        r={"status":"PASS","quarantined":str(q) if q else None,"user_data_deleted":False}
        self.atomic_json(self.evidence/"repair_result.json",r);return r
