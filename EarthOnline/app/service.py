from __future__ import annotations
from pathlib import Path
import os
from .domain import DecisionCard
from .engine import evaluate,metrics
from .netclient import NetClient
from .storage import Storage
REFERENCES={
  "health_boundary":"https://www.who.int/about",
  "safety_evidence":"https://www.nist.gov/",
  "consumer_finance":"https://www.consumerfinance.gov/consumer-tools/"
}
class EarthService:
    def __init__(self,root:Path|None=None):
        self.root=Path(root or os.environ.get("EARTH_ONLINE_ROOT","userdata"));self.storage=Storage(self.root);self.net=NetClient(self.storage.evidence/"network.jsonl")
    def update(self):
        receipts={}
        for k,u in REFERENCES.items():_b,r=self.net.get(u);receipts[k]=r
        out={"status":"PASS","reference_count":len(receipts),"receipts":receipts,"boundary":"source availability does not turn high-risk guidance into professional advice"}
        self.storage.atomic_json(self.storage.evidence/"update_result.json",out);return out
    def core(self,problem="我要做一个重要决定"):
        c=DecisionCard(problem,"降低错误成本并得到可验证下一步",("可确认事实A","当前解释仍是工作假设"),("关键未知仍需验证",),"当前路径可能遗漏关键约束",{"history":"过去路径与基准率是什么","power":"谁有权力、信息和激励","economics":"谁获益、谁付成本、机会成本是什么","execution":"资源、节奏、后勤和退出是否足够","philosophy":"真正目标与前提是否值得"}, "最小实验后可观察信号应更清楚",.55,"错误方向造成时间和资源浪费",True,"执行一个低成本可撤销的小实验","出现明确反证或成本超界立即停止","normal")
        r=evaluate(c,[{"hypothesis":"我没有把事实与解释分开","evidence":"当前决策卡首次显式拆分"},{"hypothesis":"主要问题可能是执行而非认知","evidence":""}],"即使分析完整，现实结果仍可能因随机性或环境约束变差","连续可比样本未改善且替代解释更能预测","环境约束或资源不足可能是主因")
        self.storage.append(r);self.storage.atomic_json(self.storage.evidence/"last_decision.json",r);return r
    def repair(self):return self.storage.repair()
    def advanced(self):
        r=metrics(self.storage.records());self.storage.atomic_json(self.storage.evidence/"advanced_analysis.json",r);return r
    def self_test(self):
        r=self.repair();return {"status":"PASS","product":"EarthOnline","storage_integrity":"ok" if r["status"]=="PASS" else "fail","network":"NOT EXECUTED"}
