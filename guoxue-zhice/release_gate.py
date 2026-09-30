from __future__ import annotations
import argparse, json
from pathlib import Path
HARD_GATES=["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui","self_test","unit_test","contract_test","integration_test","fault_injection","real_network","business_validation","counterexample_validation","reversal_validation","windows_build","exact_exe","gui_smoke","same_hash","business_content","repository_independence"]
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    value=json.loads(Path(a.input).read_text(encoding="utf-8-sig")); gates=value.get("gates") or {}; failures={k:gates.get(k,"MISSING") for k in HARD_GATES if str(gates.get(k,"")).upper()!="PASS"}
    report={"final_gate":"PASS" if not failures else "FAIL","hard_fail_count":len(failures),"gates":{k:gates.get(k,"MISSING") for k in HARD_GATES},"failures":failures}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False))
    return 0 if report["final_gate"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
