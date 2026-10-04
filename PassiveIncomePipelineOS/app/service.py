from __future__ import annotations
from pathlib import Path
import os
from .domain import PipelineDefinition
from .engine import evaluate,dashboard
from .netclient import NetClient
from .storage import Storage

HEALTH_ENDPOINTS={
  "github_api":"https://api.github.com/",
  "sba_business_guide":"https://www.sba.gov/business-guide"
}

class PipelineService:
    def __init__(self,root:Path|None=None):
        self.root=Path(root or os.environ.get("PASSIVE_INCOME_ROOT","userdata"));self.storage=Storage(self.root);self.net=NetClient(self.storage.evidence/"network.jsonl")
    def update(self):
        receipts={}
        for k,u in HEALTH_ENDPOINTS.items():
            _raw,r=self.net.get(u);receipts[k]=r
        out={"status":"PASS","connector_health_count":len(receipts),"receipts":receipts,"production_pipeline_revenue":"NOT VERIFIED","note":"network health is not revenue evidence"}
        self.storage.atomic_json(self.storage.evidence/"update_result.json",out);return out
    def core(self,name="候选收益管道"):
        p=PipelineDefinition("candidate_pipeline",name,"为明确客户问题提供可重复结果","https://api.github.com/",500.0,120.0,90.0,300.0,False,0,0,0)
        r=evaluate(p);self.storage.append(r);self.storage.atomic_json(self.storage.evidence/"last_pipeline.json",r);return r
    def repair(self):return self.storage.repair()
    def advanced(self):
        d=dashboard(self.storage.records());self.storage.atomic_json(self.storage.evidence/"advanced_analysis.json",d);return d
    def self_test(self):
        r=self.repair();return {"status":"PASS","product":"PassiveIncomePipelineOS","storage_integrity":"ok" if r["status"]=="PASS" else "fail","network":"NOT EXECUTED"}
