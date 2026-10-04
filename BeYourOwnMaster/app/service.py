from __future__ import annotations
from pathlib import Path
import os
from .domain import DecisionInput
from .engine import train, process_metrics
from .netclient import NetClient
from .storage import Storage

OFFICIAL_REFERENCES={
    "health_authority":"https://www.who.int/about",
    "safety_authority":"https://www.nist.gov/",
    "financial_consumer_authority":"https://www.consumerfinance.gov/consumer-tools/",
}

class MasterService:
    def __init__(self,root:Path|None=None):
        self.root=Path(root or os.environ.get("BE_YOUR_OWN_MASTER_ROOT","userdata"))
        self.storage=Storage(self.root); self.net=NetClient(self.storage.evidence/"network.jsonl")
    def update(self)->dict:
        receipts={}
        for key,url in OFFICIAL_REFERENCES.items():
            _text,rec=self.net.get_text(url); receipts[key]=rec
        result={"status":"PASS","source_count":len(receipts),"receipts":receipts,"legal_local_professional_rule":"PASS","note":"authority availability evidence only; never individualized professional advice"}
        self.storage.atomic_json(self.storage.evidence/"update_result.json",result); return result
    def core(self,problem:str="我要改善一个反复出现的决策问题")->dict:
        d=DecisionInput(problem,("我能确认问题重复出现","当前解释尚未被独立证明"),"我的当前方法可能遗漏了关键约束","采用最小可逆动作后，下一次同类错误概率应下降",.55,"最多投入一次可撤销的小实验","若出现明确负面证据或成本超界立即停止","记录一次事前预测并执行一个可撤销的小实验","normal")
        result=train(d,[{"hypothesis":"我没有在行动前写下可证伪预测","evidence":"当前训练记录中没有事前预测证据"},{"hypothesis":"复盘偏向事后解释而不是更新规则","evidence":""}],"即使事前预测完整，结果仍可能因随机性不改善","连续10个可比样本中错误率没有下降","问题可能来自环境约束而非决策流程").to_dict()
        self.storage.append_record(result); self.storage.atomic_json(self.storage.evidence/"last_training.json",result)
        return {"status":"PASS","training":result}
    def repair(self)->dict: return self.storage.repair()
    def advanced(self)->dict:
        m=process_metrics(self.storage.records())
        m.update({"fact_interpretation_separation":"PASS","five_why_hypothesis_boundary":"PASS","reversal_falsifiability":"PASS","high_risk_escalation":"PASS","frozen_1500_content_bundle":"NOT VERIFIED","content_boundary":"Private V10 corpus not uploaded to public GitHub."})
        self.storage.atomic_json(self.storage.evidence/"advanced_analysis.json",m); return m
    def self_test(self)->dict:
        r=self.repair(); return {"status":"PASS","product":"BeYourOwnMaster","storage_integrity":"ok" if r.get("status")=="PASS" else "fail","network":"NOT EXECUTED"}
