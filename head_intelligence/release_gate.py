from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from head_intelligence.gate_evidence import current_binding, read_receipt, untracked
from head_intelligence.repository_independence_gate import evaluate_inventory

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
UPDATER_CHECKS={
    "manifest_https_trust_fail_closed", "manifest_and_artifact_contract",
    "bad_hash_fail_closed", "truncated_download_fail_closed", "non_monotonic_no_replace",
    "normal_atomic_update", "untyped_health_pass_rolls_back", "wrong_version_health_rolls_back",
    "offline_manifest_fail_closed", "download_interruption_fail_closed",
    "permission_replace_failure_rolls_back", "main_program_occupied_fail_closed",
    "health_failure_rolls_back", "rollback_failure_retains_recovery_state",
    "restart_recovery_restores_previous_exe",
}
REAL_RELEASE_CHECKS={
    "schema", "declared_status", "dedicated_repository_binding", "source_binding",
    "monotonic_versions", "release_assets", "updater_transaction", "manifest_receipt",
    "artifact_receipt", "independent_updater_execution", "physical_one_click_update",
    "post_update_self_test", "official_release_n", "official_release_n1", "official_tag_source_binding",
}

def named_checks_pass(checks, names):
    return (isinstance(checks, dict) and names.issubset(checks)
            and all(isinstance(x, dict) and x.get("status") == "PASS" for x in checks.values()))

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def derive_updater_gates(evidence_dir: Path, candidate_exe: Path, final_exe: Path, source_sha: str, workflow_run: str, *, check_untracked=True) -> dict:
    def load(name):
        try:
            value=json.loads((evidence_dir/name).read_text(encoding="utf-8-sig"))
            return value if isinstance(value,dict) and (not check_untracked or untracked(evidence_dir/name)) and value.get("workflow_run")==str(workflow_run) else {}
        except Exception:return {}
    integration=load("updater_gate.json")
    windows=load("updater_windows_gate.json")
    real=load("software_release_validation.json")
    bound=bool(source_sha and len(source_sha)==40 and all(c in "0123456789abcdef" for c in source_sha))
    checks=integration.get("checks") or {}
    integration_ok=(bound and integration.get("schema")=="head-intelligence-updater-gate-v1" and integration.get("status")=="PASS" and integration.get("github_sha")==source_sha and named_checks_pass(checks, UPDATER_CHECKS))
    updater=candidate_exe.with_name("HeadIntelligence_Updater.exe")
    final_updater=final_exe.with_name("HeadIntelligence_Updater.exe")
    uh=sha256(updater) if updater.is_file() else None
    fh=sha256(final_updater) if final_updater.is_file() else None
    native_receipt=(read_receipt(evidence_dir/"process-gates"/"updater_exact_exe.json",gate="updater_exact_exe",source_sha=source_sha,workflow_run=workflow_run,artifact_hash=uh,check_untracked=check_untracked)
                    and read_receipt(evidence_dir/"process-gates"/"updater_build.json",gate="updater_build",source_sha=source_sha,workflow_run=workflow_run,artifact_hash=uh,check_untracked=check_untracked))
    windows_ok=(bound and native_receipt and windows.get("schema")=="head-intelligence-updater-windows-gate-v1" and windows.get("github_sha")==source_sha and windows.get("status")=="PASS" and windows.get("updater_exact_exe")=="PASS" and windows.get("self_test",{}).get("status")=="PASS" and windows.get("self_test",{}).get("schema")=="head-intelligence-updater-self-test-v1" and windows.get("self_test",{}).get("checks")=={"version_parser":"PASS", "https_trust":"PASS"} and windows.get("updater_exe_sha256")==uh and uh is not None)
    real_state="BLOCKED" if not real or real.get("status")=="BLOCKED" else "FAIL"
    if (bound and real.get("schema")=="head-intelligence-real-software-release-validation-v1" and real.get("status")=="PASS" and real.get("source_sha")==source_sha and real.get("github_sha")==source_sha and real.get("repository")!="douluo511/Geometry-Lotto-Pro" and named_checks_pass(real.get("checks"), REAL_RELEASE_CHECKS)):real_state="PASS"
    return {"updater_process":"PASS" if integration_ok else "FAIL", "updater_atomic_rollback":"PASS" if integration_ok else "FAIL", "updater_exact_exe":"PASS" if windows_ok else "FAIL", "updater_same_hash":"PASS" if windows_ok and uh==fh and windows.get("same_hash") is True and windows.get("final_updater_sha256")==fh else "FAIL", "updater_real_network":real_state}

def evaluate(evidence_dir:Path,candidate_exe:Path,final_exe:Path,gate_input:Path,*,check_untracked=True)->dict:
    raw=json.loads(gate_input.read_text(encoding="utf-8-sig"))
    statuses=dict(raw.get("gates",{}))
    source_sha=str(raw.get("source_sha") or ""); workflow_run=str(raw.get("workflow_run") or "")
    statuses.update(derive_updater_gates(evidence_dir,candidate_exe,final_exe,source_sha,workflow_run,check_untracked=check_untracked))
    if not read_receipt(evidence_dir/"process-gates"/"architecture.json",gate="architecture",source_sha=source_sha,workflow_run=workflow_run,check_untracked=check_untracked):
        for gate in HARD_GATES[:14]:statuses[gate]="NOT VERIFIED"
    if not read_receipt(evidence_dir/"process-gates"/"business_content.json",gate="business_content",source_sha=source_sha,workflow_run=workflow_run,check_untracked=check_untracked):statuses["business_content"]="NOT VERIFIED"
    for gate,marker in MARKERS.items():
        if not read_receipt(evidence_dir/"process-gates"/f"{gate}.json",gate=gate,source_sha=source_sha,workflow_run=workflow_run,check_untracked=check_untracked):
            statuses[gate]="NOT VERIFIED"
    ce=candidate_exe.exists(); fe=final_exe.exists()
    ch=sha256(candidate_exe) if ce else None
    fh=sha256(final_exe) if fe else None
    if not ce or not fe:
        statuses["exact_exe"]="FAIL"
    if not (ch and fh and ch==fh):
        statuses["same_hash"]="FAIL"
    for gate, artifact_hash in (("windows_build",ch),("exact_exe",ch),("gui_smoke",ch),("same_hash",ch),("physical_gui_click",fh)):
        if not artifact_hash or not read_receipt(evidence_dir/"process-gates"/f"{gate}.json",gate=gate,source_sha=source_sha,workflow_run=workflow_run,artifact_hash=artifact_hash,check_untracked=check_untracked):statuses[gate]="NOT VERIFIED"
    try:
        repository=json.loads((evidence_dir/"repository_independence.json").read_text(encoding="utf-8-sig"))
        repo_bound=(repository.get("schema")=="head-intelligence-repository-independence-v1" and repository.get("source_sha")==source_sha and repository.get("workflow_run")==workflow_run and (not check_untracked or untracked(evidence_dir/"repository_independence.json")))
        statuses["repository_independence"]=evaluate_inventory(repository.get("repository"),[item["path"] for item in repository.get("files",[])])[0] if repo_bound else "NOT VERIFIED"
    except (OSError,ValueError,TypeError,KeyError):statuses["repository_independence"]="NOT VERIFIED"
    try:
        physical=json.loads((evidence_dir/"physical_gui_click.json").read_text(encoding="utf-8-sig"))
        if not (physical.get("schema")=="head-intelligence-physical-gui-v2" and physical.get("status")=="PASS" and physical.get("workflow_run")==workflow_run and (not check_untracked or untracked(evidence_dir/"physical_gui_click.json"))
                and physical.get("source_sha")==raw.get("source_sha") and physical.get("exe_sha256")==fh
                and physical.get("button_count")==4 and physical.get("operation_binding")=="PASS"):
            statuses["physical_gui_click"]="FAIL"
        elif physical.get("release_mode")!="ConfiguredRelease":
            statuses["physical_gui_click"]="BLOCKED"
    except (OSError, ValueError, TypeError):
        statuses["physical_gui_click"]="FAIL"
    normalized={k:(statuses[k] if statuses.get(k) in {"PASS","FAIL","NOT VERIFIED","BLOCKED"} else "NOT VERIFIED") for k in HARD_GATES}
    bad={k:v for k,v in normalized.items() if v!="PASS"}
    return {
        "final_gate":"PASS" if not bad else "FAIL",
        "hard_fail_count":len(bad),
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "gates":normalized,
        "candidate_sha256":ch,
        "final_sha256":fh,
        "source_gate_status":raw.get("status","NOT VERIFIED"),
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
    binding=current_binding()
    raw=json.loads(Path(a.gate_input).read_text(encoding="utf-8-sig"))
    if raw.get("source_sha")!=binding["source_sha"] or raw.get("workflow_run")!=binding["workflow_run"]:raise RuntimeError("Final Gate source/run binding mismatch")
    r=evaluate(Path(a.evidence_dir),Path(a.candidate_exe),Path(a.final_exe),Path(a.gate_input))
    Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False))
    return 0 if r["final_gate"]=="PASS" else 10

if __name__=="__main__":
    raise SystemExit(main())
