from __future__ import annotations
import json, os
from pathlib import Path

class Storage:
    def __init__(self,root:Path):
        self.root=Path(root)
        self.projects=self.root/"projects"
        self.audio=self.root/"audio"
        self.evidence=self.root/"evidence"
        for p in (self.projects,self.audio,self.evidence): p.mkdir(parents=True,exist_ok=True)

    def atomic_json(self,path:Path,obj:dict)->Path:
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,path)
        return path

    def health(self)->dict:
        probe=self.root/"repair_probe.tmp"
        probe.write_text("ok",encoding="utf-8")
        ok=probe.read_text(encoding="utf-8")=="ok"
        probe.unlink(missing_ok=True)
        return {"status":"PASS" if ok else "FAIL","user_data_deleted":False}
