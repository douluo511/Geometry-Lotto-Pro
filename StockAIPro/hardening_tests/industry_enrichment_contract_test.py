from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
VERSION=ROOT/"staging"/"Stock_AI_Pro"/"versions"/"4.3.0"
sys.path.insert(0,str(VERSION))
import stock_ai.data_source as ds

class FakeAk:
    def __init__(self):
        self.lock=threading.Lock();self.barrier=threading.Barrier(4)
        self.active=0;self.peak=0;self.calls=[]
    def stock_individual_info_em(self,symbol):
        with self.lock:
            self.active+=1;self.peak=max(self.peak,self.active);self.calls.append(str(symbol))
        try:
            self.barrier.wait(timeout=5);time.sleep(0.02)
            return pd.DataFrame({"item":["行业"],"value":["测试行业"]})
        finally:
            with self.lock:self.active-=1

def main():
    fake=FakeAk();codes=[f"{i:06d}" for i in range(8)]
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);(root/"cache").mkdir();(root/"state").mkdir()
        with patch.object(ds,"ROOT",root),patch.object(ds,"_ak",return_value=fake),patch.object(
            ds,"load_config",return_value={"network":{"industry_workers":4}}):
            got=ds.enrich_industries(codes)
        assert set(fake.calls)==set(codes) and len(fake.calls)==len(codes),fake.calls
        assert fake.peak==4,f"bounded industry concurrency not proved: peak={fake.peak}"
        assert all(got[c]=="测试行业" for c in codes),got
        progress=json.loads((root/"state"/"industry_progress.json").read_text(encoding="utf-8"))
        assert progress["status"]=="COMPLETE" and progress["completed"]==len(codes),progress
        assert progress["workers"]==4 and progress["failed_count"]==0,progress
    evidence={"status":"PASS","codes":len(codes),"peak":fake.peak,"workers":4}
    (ROOT/"industry_enrichment_contract_evidence.json").write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(evidence));return 0
if __name__=="__main__":raise SystemExit(main())
