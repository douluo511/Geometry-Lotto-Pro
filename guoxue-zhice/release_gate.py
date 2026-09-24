from __future__ import annotations
import argparse, json
from pathlib import Path
REQUIRED_GATES=["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui","self_test","contract_test","fault_injection","real_network","windows_build","exact_exe","gui_smoke","same_hash"]
def evaluate(value):
    gates=value.get("gates") if isinstance(value,dict) else None
    if not isinstance(gates,dict): return {"final_gate":"FAIL","hard_fail_count":len(REQUIRED_GATES),"failures":["gates missing"]}
    failures=[name for name in REQUIRED_GATES if gates.get(name)!="PASS"]
    return {"final_gate":"PASS" if not failures else "FAIL","hard_fail_count":len(failures),"failures":failures,"gates":{name:gates.get(name,"MISSING") for name in REQUIRED_GATES}}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    result=evaluate(json.loads(Path(a.input).read_text(encoding="utf-8-sig"))); Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(result,ensure_ascii=False)); return 0 if result["final_gate"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
