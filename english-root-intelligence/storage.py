from __future__ import annotations
import json, os, shutil
from pathlib import Path
from core import Store, bundled_path
from contracts import validate_roots

class RootStorage:
    def __init__(self,root:Path|None=None): self.store=Store(root)
    @property
    def root(self): return self.store.root
    def load_roots(self): return self.store.load_roots()
    def load_progress(self): return self.store.load_progress()
    def mark_practiced(self,m): return self.store.mark_practiced(m)
    def bump_analysis(self): return self.store.bump_analysis()
    def save_progress(self,v): return self.store.save_progress(v)
    def replace_roots(self,raw:bytes)->dict:
        value=validate_roots(json.loads(raw.decode("utf-8-sig")))
        path=self.store.roots_path; stage=path.with_suffix(".staging"); backup=path.with_suffix(".backup")
        stage.write_bytes(raw)
        with stage.open("rb") as f: os.fsync(f.fileno())
        validate_roots(json.loads(stage.read_text(encoding="utf-8")))
        shutil.copy2(path,backup)
        try:
            os.replace(stage,path); self.store.load_roots()
        except Exception:
            if backup.exists(): shutil.copy2(backup,path)
            raise
        return value
    def repair(self):
        checks=[]
        try: roots=self.store.load_roots(); checks.append(("Knowledge DB","PASS",f'{len(roots["roots"])} roots'))
        except Exception as e:
            shutil.copy2(bundled_path("data","roots.json"),self.store.roots_path); self.store.load_roots(); checks.append(("Knowledge DB","REPAIRED",str(e)))
        try: p=self.store.load_progress(); checks.append(("User Progress","PASS",f'{len(p.get("practiced",{}))} practiced roots'))
        except Exception as e:
            self.store.save_progress({"schema":1,"practiced":{},"analyses":0,"last_update":None}); checks.append(("User Progress","REPAIRED",str(e)))
        try: self.store.load_roots(); self.store.load_progress(); status="PASS"
        except Exception as e: checks.append(("Final Gate","FAIL",str(e))); status="FAIL"
        return {"status":status,"checks":checks}
