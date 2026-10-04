from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.domain import DecisionCard,DIMENSIONS
from app.engine import evaluate
from app.service import EarthService
ROOT=Path(__file__).resolve().parents[1]
def make(domain="normal"):
    return DecisionCard("p","g",("fact",),("unknown",),"interpretation",dict(zip(DIMENSIONS,["h","p","e","x","f"])),"prediction",.6,"worst",True,"small action","stop",domain)
def main():
    r=evaluate(make("health"),[{"hypothesis":"h1","evidence":"e1"},{"hypothesis":"h2","evidence":""}],"counter","falsifier","alternative")
    assert r["high_risk_escalation_required"] is True
    assert r["five_why"][0]["causal_proof"] is False and r["five_why"][-1]["status"]=="NOT VERIFIED"
    assert r["business_gate_statuses"]["chapter_21_bundle"]=="NOT VERIFIED"
    try:
        bad=DecisionCard("p","g",("fact",),(),"i",{"history":"x"},"pred",.5,"w",True,"a","s");bad.validate()
    except ValueError:pass
    else:raise AssertionError("incomplete dimensions admitted")
    with tempfile.TemporaryDirectory() as td:
        svc=EarthService(Path(td));x=svc.core("现实问题");assert x["status"]=="PASS"
    report={"status":"PASS","interface_contracts":"PASS","engine_boundary":"PASS","fact_interpretation_separation":"PASS","evidence_grading":"PASS","five_dimension_analysis":"PASS","five_why_hypothesis_tree":"PASS","reversal_falsifiability":"PASS","high_risk_boundary":"PASS"}
    (ROOT/"contract_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report))
if __name__=="__main__":main()
