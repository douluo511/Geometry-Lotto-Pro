"""Derive diagnostics from actual current-run bytes; this is not a full acceptance denominator."""
from pathlib import Path
import hashlib
import json
import os


def read(name):
    try:
        return json.loads(Path(name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def file_hash(path):
    try:
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None


def main():
    source_sha=os.environ["SOURCE_SHA"]
    contract=read("contract_evidence.json")
    network=read("real_network_evidence.json")
    build=read("windows_build_evidence.json")
    exact=read("exact_exe_evidence.json")
    gui=read("gui_click_evidence.json")
    updater_contract=read("updater_contract_evidence.json")
    main_hash=file_hash("dist/RealMoneyFinance.exe")
    hashes=[build.get("main_sha256"), exact.get("exe_sha256_before"), exact.get("exe_sha256_after"),
            gui.get("exe_sha256_before"), gui.get("exe_sha256_after"), main_hash]
    same_hash="PASS" if main_hash and all(value==main_hash for value in hashes) else "NOT VERIFIED"
    gates={
        "contract": contract.get("status", "NOT VERIFIED"),
        "real_network": network.get("status", "NOT VERIFIED"),
        "cross_source_validation": network.get("cross_source_validation", {}).get("status", "NOT VERIFIED"),
        "windows_build": build.get("status", "NOT VERIFIED") if build.get("source_sha")==source_sha else "NOT VERIFIED",
        "exact_exe": exact.get("exact_exe", "NOT VERIFIED") if exact.get("source_sha")==source_sha else "NOT VERIFIED",
        "exact_exe_real_network": gui.get("exact_exe_real_network", {}).get("status", "NOT VERIFIED"),
        "physical_gui_core_repair_advanced": gui.get("physical_gui_core_repair_advanced", "NOT VERIFIED"),
        "physical_gui_startup_ack": gui.get("physical_gui_startup_ack", "NOT VERIFIED"),
        "physical_gui_update_negative": gui.get("physical_gui_update_negative", "NOT VERIFIED"),
        "physical_gui_update_positive": "BLOCKED",
        "independent_updater_contract_faults": updater_contract.get("status", "NOT VERIFIED"),
        "real_production_release_n_to_n_plus_1": "BLOCKED",
        "repository_independence": "BLOCKED",
        "same_hash_build_exact_gui_current_bytes": same_hash,
        "cost_slippage_liquidity_corporate_action": "NOT VERIFIED",
        "leakage_survivorship_time_splits": "NOT VERIFIED",
        "oos_walk_forward_bootstrap_ablation_stability_multiple_testing": "NOT VERIFIED",
    }
    manifest={"status":"CANDIDATE_ONLY", "source_sha":source_sha, "workflow_run_id":os.environ.get("GITHUB_RUN_ID"),
              "main_sha256":main_hash, "updater_sha256":file_hash("dist/RealMoneyFinanceUpdater.exe"), "gates":gates,
              "engineering_completion":{"status":"NOT VERIFIED", "frozen_denominator":None},
              "business_completion":{"status":"NOT VERIFIED", "frozen_denominator":None},
              "known_non_pass_gate_count":sum(value!="PASS" for value in gates.values()),
              "capital_deployment_ready":False, "final_gate":"FAIL", "delivery_allowed":False,
              "note":"Known diagnostic gates are not a frozen full engineering/business denominator."}
    Path("candidate_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
