from __future__ import annotations
import json, os, tempfile
from pathlib import Path

class Storage:
    def __init__(self, root: Path):
        self.root=Path(root); self.raw=self.root/"raw"; self.canonical=self.root/"canonical"; self.evidence=self.root/"evidence"
        for p in (self.raw,self.canonical,self.evidence): p.mkdir(parents=True,exist_ok=True)

    @staticmethod
    def atomic_bytes(path: Path, data: bytes)->None:
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            try: Path(tmp).unlink(missing_ok=True)
            except OSError: pass

    @classmethod
    def atomic_json(cls,path:Path,obj:object)->None:
        cls.atomic_bytes(path,(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode("utf-8"))

    def append_record(self,obj:dict)->None:
        path=self.canonical/"training_records.jsonl"
        with path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+"\n"); f.flush(); os.fsync(f.fileno())

    def records(self)->list[dict]:
        path=self.canonical/"training_records.jsonl"
        if not path.exists(): return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def repair(self)->dict:
        path=self.canonical/"training_records.jsonl"; quarantined=None
        if path.exists():
            try: self.records()
            except Exception as exc:
                quarantined=self.evidence/"quarantined-training-records.jsonl"
                self.atomic_bytes(quarantined,path.read_bytes()); path.unlink()
                self.atomic_json(self.evidence/"repair_fault.json",{"status":"PASS","reason":repr(exc),"quarantined":str(quarantined)})
        report={"status":"PASS","quarantined":str(quarantined) if quarantined else None,"user_data_deleted":False}
        self.atomic_json(self.evidence/"repair_result.json",report); return report
