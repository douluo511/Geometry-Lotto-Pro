from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from head_intelligence.release_gate import derive_updater_gates
from head_intelligence.gate_evidence import current_binding, read_receipt, untracked
from head_intelligence.repository_independence_gate import evaluate_inventory

ARCH_GATES=["purpose_model","five_why","risk_boundary","domain_model","architecture","function_contract","interface_contract","data_source","netclient","storage","engine","evidence","service","ui"]
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

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--evidence-dir",required=True)
    p.add_argument("--architecture",required=True)
    p.add_argument("--business",required=True)
    p.add_argument("--candidate-exe",required=True)
    p.add_argument("--final-exe",required=True)
    p.add_argument("--physical-gui",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--source-sha",required=True)
    a=p.parse_args()
    binding=current_binding()
    if binding["source_sha"]!=a.source_sha:raise RuntimeError("collector source argument does not match the checked-out head")
    ed=Path(a.evidence_dir)
    arch=json.loads(Path(a.architecture).read_text(encoding="utf-8-sig"))
    business=json.loads(Path(a.business).read_text(encoding="utf-8-sig"))
    gates={k:arch.get("gates",{}).get(k,"NOT VERIFIED") for k in ARCH_GATES}
    if not read_receipt(ed/"process-gates"/"architecture.json",gate="architecture",source_sha=a.source_sha,workflow_run=binding["workflow_run"],workflow_attempt=binding["workflow_attempt"]):
        gates={key:"NOT VERIFIED" for key in ARCH_GATES}
    for gate,marker in MARKERS.items():
        gates[gate]="PASS" if read_receipt(ed/"process-gates"/f"{gate}.json",gate=gate,source_sha=a.source_sha,workflow_run=binding["workflow_run"],workflow_attempt=binding["workflow_attempt"]) else "NOT VERIFIED"
    gates["business_content"]="PASS" if business.get("status")=="PASS" and read_receipt(ed/"process-gates"/"business_content.json",gate="business_content",source_sha=a.source_sha,workflow_run=binding["workflow_run"],workflow_attempt=binding["workflow_attempt"]) else "NOT VERIFIED"
    try:
        repository=json.loads((ed/"repository_independence.json").read_text(encoding="utf-8-sig"))
        repository_bound=(untracked(ed/"repository_independence.json") and repository.get("schema")=="head-intelligence-repository-independence-v1" and repository.get("source_sha")==a.source_sha and repository.get("workflow_run")==binding["workflow_run"] and repository.get("workflow_attempt")==binding["workflow_attempt"])
        gates["repository_independence"]=evaluate_inventory(repository.get("repository"),[item["path"] for item in repository.get("files",[])])[0] if repository_bound else "NOT VERIFIED"
    except (OSError,ValueError):gates["repository_independence"]="NOT VERIFIED"
    candidate=Path(a.candidate_exe); final=Path(a.final_exe)
    ch=sha256(candidate) if candidate.exists() else None
    fh=sha256(final) if final.exists() else None
    gates.update(derive_updater_gates(ed,candidate,final,a.source_sha,binding["workflow_run"],binding["workflow_attempt"]))
    for gate,artifact_hash in (("windows_build",ch),("exact_exe",ch),("gui_smoke",ch),("same_hash",ch),("physical_gui_click",fh)):
        if not artifact_hash or not read_receipt(ed/"process-gates"/f"{gate}.json",gate=gate,source_sha=a.source_sha,workflow_run=binding["workflow_run"],workflow_attempt=binding["workflow_attempt"],artifact_hash=artifact_hash):gates[gate]="NOT VERIFIED"
    if not ch or not fh or ch!=fh:
        gates["same_hash"]="FAIL"
    physical=json.loads(Path(a.physical_gui).read_text(encoding="utf-8-sig")) if Path(a.physical_gui).exists() else {}
    if physical.get("status")!="PASS" or physical.get("exe_sha256")!=fh or physical.get("source_sha")!=a.source_sha or physical.get("workflow_run")!=binding["workflow_run"] or physical.get("workflow_attempt")!=binding["workflow_attempt"] or physical.get("button_count")!=4 or physical.get("operation_binding")!="PASS" or not untracked(Path(a.physical_gui)):
        gates["physical_gui_click"]="FAIL"
    elif physical.get("release_mode") != "ConfiguredRelease":
        gates["physical_gui_click"]="BLOCKED"
    bad={k:v for k,v in gates.items() if v!="PASS"}
    report={
      "schema":"head-intelligence-current-run-gates-v2",
      "source_sha":a.source_sha,
      "workflow_run":binding["workflow_run"],
      "workflow_attempt":binding["workflow_attempt"],
      "status":"PASS" if not bad else "FAIL",
      "gates":gates,
      "candidate_sha256":ch,
      "final_sha256":fh,
      "failures":bad,
    }
    Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if not bad else 4

if __name__=="__main__":
    raise SystemExit(main())
