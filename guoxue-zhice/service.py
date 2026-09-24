from __future__ import annotations
import datetime as dt, tempfile
from pathlib import Path
from domain import APP_VERSION, sha256_bytes, validate_manifest
from engine import GoalEngine, ReviewEngine
from evidence import EvidenceLedger
from net_client import NetClient
from storage import Store

MANIFEST_URLS=["https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/guoxue-zhice/data/update_manifest.json","https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/guoxue-zhice-v0.1/guoxue-zhice/data/update_manifest.json"]

class GuoxueService:
    def __init__(self, root: Path|None=None, *, store: Store|None=None, net_client=None):
        self.store=store or Store(root); self.net=net_client or NetClient()
        self.goal=GoalEngine(self.store); self.review=ReviewEngine(self.store); self.evidence=EvidenceLedger(self.store.evidence_path)
    def analyze_goal(self, goal):
        result=self.goal.analyze(goal); self.evidence.record("analysis","PASS",goal=goal,status=result["status"]); return result
    def save_review(self, goal, action, result, lesson):
        item=self.review.save(goal,action,result,lesson); self.evidence.record("review","PASS",timestamp=item["timestamp"]); return item
    def stats(self):
        value=self.goal.stats(); value["evidence_events"]=len(self.evidence.recent(300)); return value
    def one_click_repair(self):
        result=self.store.repair(); self.evidence.record("repair",result["status"],checks=result["checks"]); return result
    def _fetch_manifest(self):
        failures=[]
        for url in MANIFEST_URLS:
            try:
                value,meta=self.net.get_json(url); manifest=validate_manifest(value); self.evidence.record("manifest_fetch","PASS",**meta); return manifest,meta
            except Exception as exc:
                failures.append(f"{url}: {exc}"); self.evidence.record("manifest_fetch","FAIL",source=url,error=str(exc))
        raise RuntimeError("无法获取有效更新清单；"+" | ".join(failures))
    def one_click_update(self):
        manifest,manifest_meta=self._fetch_manifest()
        raw,data_meta=self.net.get_bytes(str(manifest["data_url"]),("application/json","text/plain","application/octet-stream"))
        digest=sha256_bytes(raw)
        if digest.lower()!=str(manifest["sha256"]).lower():
            self.evidence.record("payload_hash","FAIL",expected=str(manifest["sha256"]).lower(),actual=digest.lower(),source=data_meta.get("source"))
            raise ValueError("更新包 SHA256 校验失败")
        installed=self.store.replace_knowledge(raw)
        state=self.store.load_state(); state["last_update"]=dt.datetime.now().isoformat(timespec="seconds"); self.store.save_state(state)
        result={"status":"PASS","version":manifest["version"],"classics":len(self.store.load_knowledge()["classics"]),"sha256":installed,"source":data_meta["source"],"http_status":data_meta["http_status"],"manifest_source":manifest_meta["source"],"payload_hash":data_meta["payload_sha256"]}
        self.evidence.record("update","PASS",**result); return result

def self_test(root: Path|None=None):
    temp=tempfile.TemporaryDirectory() if root is None else None
    try:
        work=Path(temp.name) if temp else Path(root); service=GuoxueService(work)
        a=service.analyze_goal("我要和长期合作伙伴谈价格，怎样判断底线和筹码并控制风险？")
        service.save_review("谈合作","先确认替代方案","对方给出更清晰条件","下次先验证对方真实时间压力")
        repair=service.one_click_repair(); stats=service.stats()
        checks={"seed_database":stats["classics"]>=20,"goal_classification":"谈判与合作" in a["scenarios"],"multi_source_methods":len(a["methods"])>=3,"five_whys":len(a["five_whys"])==5,"reverse_validation":len(a["reverse_validation"])>=3,"review_saved":stats["reviews"]>=1,"repair_gate":repair["status"]=="PASS","evidence_written":stats["evidence_events"]>=2}
        return {"status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"version":APP_VERSION}
    finally:
        if temp: temp.cleanup()
