from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.domain import DecisionInput
from app.engine import train,reversal
from app.service import MasterService
from app.content import corpus_metrics, frozen_bundle_status
ROOT=Path(__file__).resolve().parents[1]
def main():
    d=DecisionInput("重大决定",("事实1",),"解释","预测",.6,"最大损失","停止线","可逆动作","large_financial_commitment").validate()
    r=train(d,[{"hypothesis":"假设A","evidence":"证据A"},{"hypothesis":"假设B","evidence":""}],"最强反例","连续样本推翻","替代解释")
    assert r.escalation_required is True and r.effectiveness_claim=="NOT VERIFIED"
    assert r.five_why[0]["causal_proof"] is False and r.five_why[-1]["status"]=="NOT VERIFIED"
    try: reversal("判断","","推翻条件","替代")
    except ValueError: pass
    else: raise AssertionError("empty counterexample admitted")
    try: DecisionInput("x",("f",),"i","p",float("nan"),"m","s","a").validate()
    except ValueError: pass
    else: raise AssertionError("NaN confidence admitted")
    metrics=corpus_metrics()
    assert frozen_bundle_status()=="PASS"
    assert metrics["story_card_count"]==1200 and metrics["real_case_count"]==300 and metrics["total_training_entries"]==1500
    with tempfile.TemporaryDirectory() as td:
        svc=MasterService(Path(td))
        assert svc.core("测试真实问题")["status"]=="PASS"
        advanced=svc.advanced()
        assert advanced["thirty_day_effectiveness"]=="NOT VERIFIED"
        assert advanced["frozen_1500_content_bundle"]=="PASS"
    report={"status":"PASS","interface_contracts":"PASS","engine_boundary":"PASS","fact_interpretation_separation":"PASS","five_why_hypothesis_boundary":"PASS","reversal_falsifiability":"PASS","high_risk_escalation":"PASS","frozen_1500_content_bundle":"PASS"}
    (ROOT/"contract_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__": main()
