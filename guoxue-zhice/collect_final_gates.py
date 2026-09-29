from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent
def read(path:Path)->dict[str,Any]:
    if not path.exists(): return {"status":"MISSING"}
    try:
        v=json.loads(path.read_text(encoding="utf-8-sig"))
        return v if isinstance(v,dict) else {"status":"INVALID"}
    except Exception as exc: return {"status":"INVALID","error":f"{type(exc).__name__}: {exc}"}
def sha256(path:Path)->str|None:
    if not path.exists(): return None
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--exe",required=True); p.add_argument("--final-exe",required=True); p.add_argument("--physical-gui",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    current=os.environ.get("GITHUB_SHA")
    reports={
      "architecture":read(ROOT/"architecture_gate.json"),"business":read(ROOT/"business_gate.json"),
      "unit":read(ROOT/"unit_gate.json"),"contract":read(ROOT/"contract_gate.json"),"fault":read(ROOT/"fault_gate.json"),
      "integration":read(ROOT/"integration_gate.json"),"real_network":read(ROOT/"real_network_evidence.json"),
      "business_validation":read(ROOT/"business_validation_gate.json"),"exact":read(ROOT/"exact_candidate_gate.json"),
      "physical":read(Path(a.physical_gui)),
    }
    bound={k:(v.get("github_sha")==current) for k,v in reports.items()}
    gates={k:("PASS" if str(v).upper()=="PASS" else "FAIL") for k,v in (reports["architecture"].get("gates") or {}).items()}
    for name in ["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui"]:
        gates.setdefault(name,"FAIL")
        if not bound["architecture"]: gates[name]="FAIL"
    gates["unit_test"]="PASS" if bound["unit"] and reports["unit"].get("status")=="PASS" else "FAIL"
    gates["contract_test"]="PASS" if bound["contract"] and reports["contract"].get("status")=="PASS" else "FAIL"
    gates["fault_injection"]="PASS" if bound["fault"] and reports["fault"].get("status")=="PASS" else "FAIL"
    gates["integration_test"]="PASS" if bound["integration"] and reports["integration"].get("status")=="PASS" else "FAIL"
    gates["real_network"]="PASS" if bound["real_network"] and reports["real_network"].get("status")=="PASS" and reports["real_network"].get("network_gate")=="PASS" else "FAIL"
    bv=reports["business_validation"]
    gates["business_validation"]="PASS" if bound["business_validation"] and bv.get("business_validation")=="PASS" else "FAIL"
    gates["counterexample_validation"]="PASS" if bound["business_validation"] and bv.get("counterexample_validation")=="PASS" else "FAIL"
    gates["reversal_validation"]="PASS" if bound["business_validation"] and bv.get("reversal_validation")=="PASS" else "FAIL"
    exact=reports["exact"]; source=Path(a.exe); final=Path(a.final_exe); sh=sha256(source); fh=sha256(final)
    gates["self_test"]="PASS" if bound["exact"] and (exact.get("self_test") or {}).get("status")=="PASS" else "FAIL"
    gates["windows_build"]="PASS" if bound["exact"] and exact.get("windows_build")=="PASS" else "FAIL"
    gates["exact_exe"]="PASS" if bound["exact"] and exact.get("exact_exe")=="PASS" and exact.get("exe_sha256")==sh else "FAIL"
    physical=reports["physical"]; buttons=physical.get("buttons") or []
    physical_ok=bound["physical"] and physical.get("status")=="PASS" and physical.get("exe_sha256")==sh and len(buttons)==4 and all(x.get("status")=="PASS" and x.get("visual_changed") is True for x in buttons)
    gates["gui_smoke"]="PASS" if physical_ok and (exact.get("gui_smoke") or {}).get("status")=="PASS" else "FAIL"
    gates["same_hash"]="PASS" if sh and sh==fh==exact.get("exe_sha256") else "FAIL"
    gates["business_content"]="PASS" if bound["business"] and reports["business"].get("status")=="PASS" else "FAIL"
    failures={k:v for k,v in gates.items() if v!="PASS"}
    report={"schema":"guoxue-mother-gate-input-v1","status":"PASS" if not failures else "FAIL","hard_fail_count":len(failures),"github_sha":current,"gates":gates,"failures":failures,"exe_sha256":sh,"final_exe_sha256":fh,"current_run_binding":bound}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False))
    return 0 if report["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
