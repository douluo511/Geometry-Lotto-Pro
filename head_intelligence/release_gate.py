from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

HARD_GATES=[
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui",
    "self_test","unit_test","contract_test","integration_test","fault_injection",
    "real_network","business_validation","counterexample_validation","reversal_validation",
    "windows_build","exact_exe","gui_smoke","physical_gui_click","same_hash","business_content",
    "updater_process","updater_exact_exe","updater_atomic_rollback","updater_real_network","updater_same_hash","repository_independence",
]
MARKERS={
    "self_test":"python_self_test.pass",
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
    "gui_smoke":"gui_smoke.pass",
    "physical_gui_click":"physical_gui_click.pass",
    "same_hash":"same_hash.pass",
}

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def evaluate(evidence_dir:Path,candidate_exe:Path,final_exe:Path,gate_input:Path)->dict:
    raw=json.loads(gate_input.read_text(encoding="utf-8-sig"))
    statuses=dict(raw.get("gates",{}))
    for gate,marker in MARKERS.items():
        if not (evidence_dir/marker).exists():
            statuses[gate]="FAIL"
    ce=candidate_exe.exists(); fe=final_exe.exists()
    ch=sha256(candidate_exe) if ce else None
    fh=sha256(final_exe) if fe else None
    if not ce or not fe:
        statuses["exact_exe"]="FAIL"
    if not (ch and fh and ch==fh):
        statuses["same_hash"]="FAIL"
    normalized={k:statuses.get(k,"UNKNOWN") for k in HARD_GATES}
    bad={k:v for k,v in normalized.items() if v!="PASS"}
    return {
        "final_gate":"PASS" if not bad else "FAIL",
        "hard_fail_count":len(bad),
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "gates":normalized,
        "candidate_sha256":ch,
        "final_sha256":fh,
        "source_gate_status":raw.get("status","UNKNOWN"),
        "failures":bad,
    }

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--evidence-dir",required=True)
    p.add_argument("--candidate-exe",required=True)
    p.add_argument("--final-exe",required=True)
    p.add_argument("--gate-input",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    r=evaluate(Path(a.evidence_dir),Path(a.candidate_exe),Path(a.final_exe),Path(a.gate_input))
    Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False))
    return 0 if r["final_gate"]=="PASS" else 10

if __name__=="__main__":
    raise SystemExit(main())
