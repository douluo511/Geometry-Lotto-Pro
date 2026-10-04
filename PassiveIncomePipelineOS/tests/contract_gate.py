from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.domain import PipelineDefinition
from app.engine import evaluate
from app.service import PipelineService
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=PipelineDefinition("abc","x","value","https://example.com",100,20,60,100,False,0,0,0)
    r=evaluate(p)
    assert r["business_gate_statuses"]["real_payment"]=="NOT VERIFIED"
    assert r["production_income_verified"] is False and r["projection_is_not_income"] is True
    paid=PipelineDefinition("paid","x","value","https://example.com",100,120,60,100,True,1,1,0)
    assert evaluate(paid)["business_gate_statuses"]["positive_unit_economics"]=="FAIL"
    repeat=PipelineDefinition("repeat","x","value","https://example.com",100,20,60,100,True,2,2,1)
    rr=evaluate(repeat);assert rr["business_gate_statuses"]["positive_unit_economics"]=="PASS" and rr["business_gate_statuses"]["repeatability"]=="PASS"
    try:PipelineDefinition("bad","x","value","http://example.com",1,1,1,1).validate()
    except ValueError:pass
    else:raise AssertionError("HTTP connector admitted")
    with tempfile.TemporaryDirectory() as td:
        svc=PipelineService(Path(td));x=svc.core("candidate");assert x["production_income_verified"] is False
    report={"status":"PASS","interface_contracts":"PASS","engine_boundary":"PASS","projection_not_income":"PASS","negative_economics_fails":"PASS","repeatability_requires_repeat_payment":"PASS"}
    (ROOT/"contract_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report))
if __name__=="__main__":main()
