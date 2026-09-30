from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ARCH_GATES=[
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui",
]
MARKERS={
    "self_test":"source_self_test.pass",
    "unit_test":"unit_tests.pass",
    "contract_test":"contract_tests.pass",
    "integration_test":"integration_tests.pass",
    "fault_injection":"fault_injection.pass",
    "real_network":"real_network.pass",
    "business_validation":"business_validation.pass",
    "counterexample_validation":"counterexample_validation.pass",
    "reversal_validation":"reversal_validation.pass",
    "windows_build":"windows_build.pass",
    "exact_exe":"exact_exe_self_test.pass",
    "exact_exe_network":"exact_exe_network.pass",
    "gui_smoke":"gui_smoke.pass",
    "physical_gui_click":"physical_gui_click.pass",
    "same_hash":"same_hash.pass",
}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def _science_ok(path:Path)->bool:
    if not path.exists(): return False
    value=json.loads(path.read_text(encoding="utf-8-sig"))
    return (
        value.get("status")=="PASS"
        and value.get("scientific_gate")=="PASS"
        and value.get("model_status")=="UNVALIDATED"
        and value.get("promotion_allowed") is False
        and all(value.get("integrity_checks",{}).values())
    )

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--evidence-dir",required=True)
    p.add_argument("--architecture",required=True)
    p.add_argument("--business",required=True)
    p.add_argument("--source-science",required=True)
    p.add_argument("--exe-science",required=True)
    p.add_argument("--candidate-exe",required=True)
    p.add_argument("--final-exe",required=True)
    p.add_argument("--physical-gui",required=True)
    p.add_argument("--repository-independent",choices=["PASS","FAIL"],required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    ed=Path(a.evidence_dir)
    arch=json.loads(Path(a.architecture).read_text(encoding="utf-8-sig"))
    business=json.loads(Path(a.business).read_text(encoding="utf-8-sig"))
    gates={k:arch.get("gates",{}).get(k,"UNKNOWN") for k in ARCH_GATES}
    for gate,marker in MARKERS.items():
        gates[gate]="PASS" if (ed/marker).exists() else "FAIL"
    gates["business_content"]="PASS" if business.get("status")=="PASS" else "FAIL"
    gates["oos_validation"]="PASS" if _science_ok(Path(a.source_science)) and _science_ok(Path(a.exe_science)) else "FAIL"
    gates["repository_independence"]=a.repository_independent

    candidate=Path(a.candidate_exe); final=Path(a.final_exe)
    ch=sha256(candidate) if candidate.exists() else None
    fh=sha256(final) if final.exists() else None
    if not ch or not fh or ch!=fh:
        gates["same_hash"]="FAIL"

    physical=json.loads(Path(a.physical_gui).read_text(encoding="utf-8-sig")) if Path(a.physical_gui).exists() else {}
    if physical.get("status")!="PASS" or physical.get("exe_sha256")!=fh or physical.get("button_count")!=4:
        gates["physical_gui_click"]="FAIL"

    bad={k:v for k,v in gates.items() if v!="PASS"}
    report={
        "schema":"investment-finance-current-run-gates-v2",
        "status":"PASS" if not bad else "FAIL",
        "gates":gates,
        "candidate_sha256":ch,
        "final_sha256":fh,
        "source_science_status":"PASS" if _science_ok(Path(a.source_science)) else "FAIL",
        "exe_science_status":"PASS" if _science_ok(Path(a.exe_science)) else "FAIL",
        "failures":bad,
    }
    Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if not bad else 4

if __name__=="__main__":
    raise SystemExit(main())
