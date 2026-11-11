from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.domain import ExperimentInput
from app.engine import assess
from app.service import NonHardWorkService
ROOT=Path(__file__).resolve().parents[1]
def main():
    no_pay=ExperimentInput("p","problem","payer","hyp","failure",100,7,100,10,10,2,0,0)
    r=assess(no_pay)
    assert r["business_gate_statuses"]["real_payment"]=="NOT VERIFIED"
    assert r["business_gate_statuses"]["unit_economics"]=="NOT VERIFIED"
    assert r["scale_authorized"] is False and r["profit_guarantee"] is False
    loss=ExperimentInput("p","problem","payer","hyp","failure",100,7,100,80,30,2,1,0)
    r2=assess(loss); assert r2["business_gate_statuses"]["unit_economics"]=="FAIL"
    good=ExperimentInput("p","problem","payer","hyp","failure",100,7,100,20,10,2,2,1)
    r3=assess(good); assert r3["business_gate_statuses"]["unit_economics"]=="PASS" and r3["business_gate_statuses"]["repeatability"]=="PASS"
    try: ExperimentInput("p","problem","payer","hyp","failure",100,7,float("nan"),1,1,1,0,0).validate()
    except ValueError: pass
    else: raise AssertionError("NaN admitted")
    with tempfile.TemporaryDirectory() as td:
        svc=NonHardWorkService(Path(td)); c=svc.core("real test"); assert c["status"]=="PASS" and c["business_gate_statuses"]["real_payment"]=="NOT VERIFIED"
    report={"status":"PASS","interface_contracts":"PASS","engine_boundary":"PASS","no_payment_not_promoted":"PASS","negative_unit_economics_fails":"PASS","repeat_payment_gate":"PASS"}
    (ROOT/"contract_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report))
if __name__=="__main__":main()
