from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ARCH_GATES=["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui"]
MARKERS={
 "self_test":"self_test.pass","unit_test":"unit_tests.pass","contract_test":"contract_tests.pass",
 "integration_test":"integration_tests.pass","fault_injection":"fault_injection.pass",
 "real_network":"real_network.pass","business_validation":"business_validation.pass",
 "counterexample_validation":"counterexample_validation.pass","reversal_validation":"reversal_validation.pass",
 "windows_build":"windows_build.pass","exact_exe":"exact_exe_self_test.pass",
 "gui_smoke":"gui_smoke.pass","physical_gui_click":"physical_gui_click.pass","same_hash":"same_hash.pass",
}
def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    p=argparse.ArgumentParser()
    for x in ("evidence_dir","architecture","business","candidate_exe","final_exe","physical_gui","out"): p.add_argument("--"+x.replace("_","-"),dest=x,required=True)
    p.add_argument("--repository-independent",choices=["PASS","FAIL"],default="FAIL")
    a=p.parse_args(); ed=Path(a.evidence_dir)
    arch=json.loads(Path(a.architecture).read_text(encoding="utf-8-sig")); business=json.loads(Path(a.business).read_text(encoding="utf-8-sig"))
    gates={k:arch.get("gates",{}).get(k,"UNKNOWN") for k in ARCH_GATES}
    for g,m in MARKERS.items(): gates[g]="PASS" if (ed/m).exists() else "FAIL"
    gates["business_content"]="PASS" if business.get("status")=="PASS" else "FAIL"
    gates["repository_independence"]=a.repository_independent
    cp,fp=Path(a.candidate_exe),Path(a.final_exe)
    ch=sha256(cp) if cp.exists() else None; fh=sha256(fp) if fp.exists() else None
    if not ch or not fh: gates["exact_exe"]="FAIL"
    if not ch or ch!=fh: gates["same_hash"]="FAIL"
    physical={}
    if Path(a.physical_gui).exists(): physical=json.loads(Path(a.physical_gui).read_text(encoding="utf-8-sig"))
    if physical.get("status")!="PASS" or physical.get("exe_sha256")!=fh or physical.get("button_count")!=4: gates["physical_gui_click"]="FAIL"
    failures={k:v for k,v in gates.items() if v!="PASS"}
    r={"schema":"talkcraft-current-run-gates-v1","status":"PASS" if not failures else "FAIL","gates":gates,"candidate_sha256":ch,"final_sha256":fh,"failures":failures}
    Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(r,ensure_ascii=False))
    return 0 if not failures else 4
if __name__=="__main__": raise SystemExit(main())
