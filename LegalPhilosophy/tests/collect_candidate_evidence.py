from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(name: str) -> dict:
    path=ROOT/name
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def hash_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def coverage(required: list[str], statuses: dict[str,str]) -> dict:
    frozen={name:statuses.get(name,"NOT VERIFIED") for name in required}
    passed=sum(value=="PASS" for value in frozen.values())
    total=len(required)
    return {
        "status":"PASS" if total and passed==total else "NOT VERIFIED",
        "passed":passed,
        "required":total,
        "percent":round(100*passed/total,1) if total else 0.0,
        "gate_statuses":frozen,
    }


def main() -> int:
    contract=read("ACCEPTANCE_CONTRACT.json")
    governance=read("governance_evidence.json")
    con=read("contract_evidence.json")
    fault=read("fault_injection_evidence.json")
    updater=read("updater_contract_evidence.json")
    network=read("real_network_evidence.json")
    business=read("business_qualification_evidence.json")
    build=read("windows_build_evidence.json")
    exact=read("exact_exe_evidence.json")
    gui=read("gui_click_evidence.json")
    source_sha=os.environ.get("SOURCE_SHA")
    exe=ROOT/"dist"/"LegalPhilosophy.exe"
    current_hash=hash_file(exe)
    same_hash="PASS" if current_hash and exact.get("exe_sha256_before")==current_hash and exact.get("exe_sha256_after")==current_hash and gui.get("exe_sha256_before")==current_hash and gui.get("exe_sha256_after")==current_hash else "NOT VERIFIED"

    engineering_statuses={
        "requirements_purpose_model":governance.get("requirements_purpose_model","NOT VERIFIED"),
        "five_why":governance.get("five_why","NOT VERIFIED"),
        "risk_boundary":governance.get("risk_boundary","NOT VERIFIED"),
        "domain_model":governance.get("domain_model","NOT VERIFIED"),
        "architecture":governance.get("architecture","NOT VERIFIED"),
        "function_inventory":governance.get("function_inventory","NOT VERIFIED"),
        "interface_contracts":con.get("interface_contracts","NOT VERIFIED"),
        "data_sources":network.get("status","NOT VERIFIED"),
        "netclient":"PASS" if con.get("status")=="PASS" and fault.get("status")=="PASS" and network.get("status")=="PASS" else "NOT VERIFIED",
        "storage":"PASS" if fault.get("corrupt_canonical_repair_preserves_evidence")=="PASS" and network.get("raw_canonical_integrity")=="PASS" else "NOT VERIFIED",
        "engine":con.get("engine_boundary","NOT VERIFIED"),
        "validation":business.get("status","NOT VERIFIED"),
        "evidence":"PASS" if all(read(x) for x in ("governance_evidence.json","contract_evidence.json","fault_injection_evidence.json","real_network_evidence.json","business_qualification_evidence.json")) else "NOT VERIFIED",
        "service":network.get("study_service","NOT VERIFIED"),
        "ui":gui.get("physical_gui","NOT VERIFIED"),
        "self_test":exact.get("status","NOT VERIFIED"),
        "contract_test":con.get("status","NOT VERIFIED"),
        "fault_injection":fault.get("status","NOT VERIFIED"),
        "real_network":network.get("status","NOT VERIFIED"),
        "windows_build":build.get("status","NOT VERIFIED") if build.get("source_sha")==source_sha else "NOT VERIFIED",
        "exact_exe":exact.get("status","NOT VERIFIED") if exact.get("source_sha")==source_sha else "NOT VERIFIED",
        "physical_gui":gui.get("physical_gui","NOT VERIFIED"),
        "updater_contract":updater.get("status","NOT VERIFIED"),
        "positive_production_update":"BLOCKED",
        "repository_independence":"BLOCKED",
        "real_release_n_to_n_plus_1":"BLOCKED",
        "same_hash_current_bytes":same_hash,
        "formal_release_redownload_same_hash":"NOT VERIFIED",
    }
    eng=coverage(contract.get("engineering_required",[]),engineering_statuses)
    biz=coverage(contract.get("business_required",[]),business.get("gate_statuses",{}))
    final="PASS" if eng["status"]=="PASS" and biz["status"]=="PASS" else "FAIL"
    report={
        "status":"CANDIDATE_ONLY" if final!="PASS" else "FINAL_ELIGIBLE_PENDING_FORMAL_RELEASE",
        "source_sha":source_sha,
        "main_sha256":current_hash,
        "updater_sha256":hash_file(ROOT/"dist"/"LegalPhilosophyUpdater.exe"),
        "engineering_completion":eng,
        "business_completion":biz,
        "business_qualification_status":business.get("business_qualification_status","NOT VERIFIED"),
        "business_gaps":business.get("gaps",{}),
        "final_gate":final,
        "delivery_allowed":final=="PASS",
        "note":"New re-authored lineage. Historical Law_Philosophy_Principles.exe evidence is not inherited.",
    }
    (ROOT/"candidate_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
