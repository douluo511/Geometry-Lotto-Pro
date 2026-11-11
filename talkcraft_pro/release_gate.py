from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

HARD_GATES=["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui","self_test","unit_test","contract_test","integration_test","fault_injection","real_network","business_validation","counterexample_validation","reversal_validation","windows_build","exact_exe","exact_exe_network","gui_smoke","physical_gui_click","same_hash","business_content","repository_independence"]
def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def evaluate(gate_input:Path,candidate:Path,final:Path)->dict:
    raw=json.loads(gate_input.read_text(encoding="utf-8-sig")); statuses=dict(raw.get("gates",{}))
    ch=sha256(candidate) if candidate.exists() else None; fh=sha256(final) if final.exists() else None
    if not ch or not fh: statuses["exact_exe"]="FAIL"
    if not ch or ch!=fh: statuses["same_hash"]="FAIL"
    normalized={k:statuses.get(k,"UNKNOWN") for k in HARD_GATES}; failures={k:v for k,v in normalized.items() if v!="PASS"}
    return {"final_gate":"PASS" if not failures else "FAIL","hard_fail_count":len(failures),"generated_at":datetime.now(timezone.utc).isoformat(),"gates":normalized,"candidate_sha256":ch,"final_sha256":fh,"failures":failures}
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--gate-input",required=True); p.add_argument("--candidate-exe",required=True); p.add_argument("--final-exe",required=True); p.add_argument("--out",required=True)
    a=p.parse_args(); r=evaluate(Path(a.gate_input),Path(a.candidate_exe),Path(a.final_exe)); Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(r,ensure_ascii=False)); return 0 if r["final_gate"]=="PASS" else 10
if __name__=="__main__": raise SystemExit(main())
