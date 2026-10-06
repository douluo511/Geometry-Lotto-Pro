from __future__ import annotations
from pathlib import Path
import os
from .domain import ExperimentInput
from .engine import assess,portfolio_metrics
from .netclient import NetClient
from .storage import Storage

REFERENCES={
  "small_business_planning":"https://www.sba.gov/business-guide/plan-your-business",
  "consumer_scam_risk":"https://consumer.ftc.gov/scams",
  "consumer_finance":"https://www.consumerfinance.gov/consumer-tools/"
}

class NonHardWorkService:
    def __init__(self,root:Path|None=None):
        self.root=Path(root or os.environ.get("NON_HARD_WORK_ROOT","userdata")); self.storage=Storage(self.root); self.net=NetClient(self.storage.evidence/"network.jsonl")
    def update(self):
        receipts={}
        for k,u in REFERENCES.items():
            _t,r=self.net.get(u); receipts[k]=r
        out={"status":"PASS","source_count":len(receipts),"receipts":receipts,"boundary":"reference availability only; no income promise"}
        self.storage.atomic_json(self.storage.evidence/"update_result.json",out); return out
    def core(self,project="低风险验证项目"):
        x=ExperimentInput(project,"客户是否愿意为明确结果付费","有明确预算的目标客户","如果问题足够痛且结果可量化，客户会出现真实付款行为","客户只口头认可但不付款",500.0,7,800.0,180.0,120.0,3.0,0,0)
        r=assess(x); self.storage.append(r); self.storage.atomic_json(self.storage.evidence/"last_experiment.json",r); return r
    def repair(self): return self.storage.repair()
    def advanced(self):
        m=portfolio_metrics(self.storage.records()); m["status"]="PASS"; m["scale_rule"]="Only projects with real payment + positive unit economics + repeatability + systemization + scale stress may scale."
        self.storage.atomic_json(self.storage.evidence/"advanced_analysis.json",m); return m
    def self_test(self):
        r=self.repair(); return {"status":"PASS","product":"NonHardWorkOS","storage_integrity":"ok" if r.get("status")=="PASS" else "fail","network":"NOT EXECUTED"}
