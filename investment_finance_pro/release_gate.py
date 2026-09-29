from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

HARD_GATES=[
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui",
    "self_test","unit_test","contract_test","integration_test","fault_injection",
    "real_network","business_validation","oos_validation",
    "counterexample_validation","reversal_validation",
    "windows_build","exact_exe","exact_exe_network","gui_smoke",
    "physical_gui_click","same_hash","business_content",
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

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest().lower()

def evaluate(payload:dict,evidence_dir:Path,tested:Path,final:Path)->dict:
    source=payload.get("gates",{})
    gates={name:source.get(name,"UNKNOWN") for name in HARD_GATES}
    for gate,marker in MARKERS.items():
        if not (evidence_dir/marker).exists():
            gates[gate]="FAIL"
    tested_hash=sha256_file(tested) if tested.exists() else None
    final_hash=sha256_file(final) if final.exists() else None
    if not tested_hash or not final_hash:
        gates["exact_exe"]="FAIL"
    if not tested_hash or tested_hash!=final_hash:
        gates["same_hash"]="FAIL"
    failures={k:v for k,v in gates.items() if v!="PASS"}
    return {
        "final_gate":"PASS" if not failures else "FAIL",
        "hard_fail_count":len(failures),
        "gates":gates,
        "tested_sha256":tested_hash,
        "final_sha256":final_hash,
        "source_gate_status":payload.get("status","UNKNOWN"),
        "failures":failures,
    }

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--evidence-dir",required=True)
    p.add_argument("--tested-exe",required=True)
    p.add_argument("--final-exe",required=True)
    p.add_argument("--report",required=True)
    a=p.parse_args()
    result=evaluate(
        json.loads(Path(a.input).read_text(encoding="utf-8-sig")),
        Path(a.evidence_dir),
        Path(a.tested_exe),
        Path(a.final_exe),
    )
    Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["final_gate"]=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
