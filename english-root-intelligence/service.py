from __future__ import annotations
import hashlib, tempfile
from pathlib import Path
from core import APP_NAME, APP_VERSION, MANIFEST_URL, self_test as legacy_self_test
from contracts import validate_manifest, validate_roots
from engine import EnglishRootEngine
from evidence import EvidenceLedger
from net_client import NetClient
from storage import RootStorage

class EnglishRootService:
    def __init__(self,storage:RootStorage,net:NetClient,evidence:EvidenceLedger):
        self.storage=storage; self.net=net; self.evidence=evidence; self.engine=EnglishRootEngine(storage)
    def analyze(self,word):
        r=self.engine.analyze(word); self.evidence.record("ENGINE","PASS",word=r.get("word"),confidence=r.get("confidence")); return r
    def today_roots(self,count=3): return self.engine.today_roots(count)
    def stats(self): return self.engine.stats()
    def mark_practiced(self,m): return self.storage.mark_practiced(m)
    def one_click_update(self):
        try:
            manifest,mrec=self.net.get_json(MANIFEST_URL); validate_manifest(manifest)
            raw,drec=self.net.get_bytes(manifest["data_url"])
            digest=hashlib.sha256(raw).hexdigest()
            if digest.lower()!=manifest["sha256"].lower(): raise ValueError("update SHA256 mismatch")
            value=validate_roots(__import__("json").loads(raw.decode("utf-8-sig"))); self.storage.replace_roots(raw)
            p=self.storage.load_progress(); p["last_update"]=drec.fetched_at; self.storage.save_progress(p)
            self.evidence.record("NETWORK","PASS",manifest_source=mrec.__dict__,data_source=drec.__dict__,payload_hash=digest)
            return {"status":"PASS","version":value.get("version"),"roots":len(value["roots"]),"sha256":digest,"source":drec.__dict__}
        except Exception as e:
            self.evidence.record("NETWORK","FAIL",error=str(e)); raise
    def one_click_repair(self):
        r=self.storage.repair(); self.evidence.record("STORAGE",r["status"],checks=r["checks"]); return r

def create_service(root:Path|None=None,net:NetClient|None=None)->EnglishRootService:
    s=RootStorage(root); return EnglishRootService(s,net or NetClient(),EvidenceLedger(s.root/"evidence.jsonl"))

def self_test(root:Path|None=None): return legacy_self_test(root)
