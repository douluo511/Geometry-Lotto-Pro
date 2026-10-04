"""Freeze current exact-head evidence against the project acceptance contract.

Only literal PASS counts toward completion. This manifest never promotes workflow success,
candidate artifacts, BLOCKED paths, or historical evidence to Final.
"""
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


def all_evidence_present(names):
    return all(Path(name).is_file() for name in names)


def coverage(required, statuses):
    frozen = {name: statuses.get(name, "NOT VERIFIED") for name in required}
    passed = sum(value == "PASS" for value in frozen.values())
    total = len(required)
    percent = round(100.0 * passed / total, 1) if total else 0.0
    return {
        "status": "PASS" if total and passed == total else "NOT VERIFIED",
        "passed": passed,
        "required": total,
        "percent": percent,
        "gate_statuses": frozen,
    }


def main():
    source_sha = os.environ["SOURCE_SHA"]
    acceptance = read("ACCEPTANCE_CONTRACT.json")
    if acceptance.get("schema_version") != 1:
        raise RuntimeError("missing or unsupported frozen acceptance contract")

    contract = read("contract_evidence.json")
    fault = read("fault_injection_evidence.json")
    network = read("real_network_evidence.json")
    business = read("business_qualification_evidence.json")
    business_real = business.get("real_market_research_qualification", {}) if business.get("status") == "PASS" else {}
    business_gates = business_real.get("gates", {})
    build = read("windows_build_evidence.json")
    exact = read("exact_exe_evidence.json")
    gui = read("gui_click_evidence.json")
    updater_contract = read("updater_contract_evidence.json")

    main_hash = file_hash("dist/RealMoneyFinance.exe")
    hashes = [
        build.get("main_sha256"),
        exact.get("exe_sha256_before"),
        exact.get("exe_sha256_after"),
        gui.get("exe_sha256_before"),
        gui.get("exe_sha256_after"),
        main_hash,
    ]
    same_hash = "PASS" if main_hash and all(value == main_hash for value in hashes) else "NOT VERIFIED"

    diagnostic_gates = {
        "contract": contract.get("status", "NOT VERIFIED"),
        "fault_injection": fault.get("status", "NOT VERIFIED"),
        "real_network": network.get("status", "NOT VERIFIED"),
        "cross_source_validation": network.get("cross_source_validation", {}).get("status", "NOT VERIFIED"),
        "windows_build": build.get("status", "NOT VERIFIED") if build.get("source_sha") == source_sha else "NOT VERIFIED",
        "exact_exe": exact.get("exact_exe", "NOT VERIFIED") if exact.get("source_sha") == source_sha else "NOT VERIFIED",
        "exact_exe_real_network": gui.get("exact_exe_real_network", {}).get("status", "NOT VERIFIED"),
        "physical_gui_core_repair_advanced": gui.get("physical_gui_core_repair_advanced", "NOT VERIFIED"),
        "physical_gui_startup_ack": gui.get("physical_gui_startup_ack", "NOT VERIFIED"),
        "physical_gui_update_negative": gui.get("physical_gui_update_negative", "NOT VERIFIED"),
        "physical_gui_update_positive": "BLOCKED",
        "independent_updater_contract_faults": updater_contract.get("status", "NOT VERIFIED"),
        "real_production_release_n_to_n_plus_1": "BLOCKED",
        "repository_independence": "BLOCKED",
        "same_hash_build_exact_gui_current_bytes": same_hash,
    }

    evidence_present = all_evidence_present([
        "contract_evidence.json",
        "fault_injection_evidence.json",
        "updater_contract_evidence.json",
        "real_network_evidence.json",
        "business_qualification_evidence.json",
        "windows_build_evidence.json",
        "exact_exe_evidence.json",
        "gui_click_evidence.json",
    ])

    engineering_statuses = {
        "requirements_purpose_model": "NOT VERIFIED",
        "five_why": "NOT VERIFIED",
        "risk_boundary": "PASS" if contract.get("status") == "PASS" else "NOT VERIFIED",
        "domain_model": "NOT VERIFIED",
        "architecture": "NOT VERIFIED",
        "function_inventory": "NOT VERIFIED",
        "interface_contracts": contract.get("status", "NOT VERIFIED"),
        "data_sources": network.get("status", "NOT VERIFIED"),
        "netclient": "PASS" if fault.get("status") == "PASS" and network.get("status") == "PASS" else "NOT VERIFIED",
        "storage": contract.get("storage", "NOT VERIFIED"),
        "engine": contract.get("engine_boundary", "NOT VERIFIED"),
        "evidence": "PASS" if evidence_present else "NOT VERIFIED",
        "service": "PASS" if gui.get("physical_gui_core_repair_advanced") == "PASS" else "NOT VERIFIED",
        "ui": gui.get("physical_gui_core_repair_advanced", "NOT VERIFIED"),
        "self_test": exact.get("exact_exe", "NOT VERIFIED") if exact.get("source_sha") == source_sha else "NOT VERIFIED",
        "contract_test": contract.get("status", "NOT VERIFIED"),
        "fault_injection": fault.get("status", "NOT VERIFIED"),
        "real_network": network.get("status", "NOT VERIFIED"),
        "cross_source_validation": network.get("cross_source_validation", {}).get("status", "NOT VERIFIED"),
        "windows_build": build.get("status", "NOT VERIFIED") if build.get("source_sha") == source_sha else "NOT VERIFIED",
        "exact_exe": exact.get("exact_exe", "NOT VERIFIED") if exact.get("source_sha") == source_sha else "NOT VERIFIED",
        "physical_gui": "PASS" if (
            gui.get("physical_gui_core_repair_advanced") == "PASS"
            and gui.get("physical_gui_startup_ack") == "PASS"
        ) else "NOT VERIFIED",
        "updater_contract": updater_contract.get("status", "NOT VERIFIED"),
        "positive_production_update": "BLOCKED",
        "repository_independence": "BLOCKED",
        "real_release_n_to_n_plus_1": "BLOCKED",
        "same_hash_current_bytes": same_hash,
        "formal_release_redownload_same_hash": "NOT VERIFIED",
    }

    base_name = business_real.get("base_feature_set")
    base_result = business_real.get("feature_results", {}).get(base_name, {}) if base_name else {}
    base_walk = base_result.get("walk_forward", {})
    baseline_comparison = "PASS" if (
        isinstance(base_walk.get("buy_and_hold_baseline_mean_net_return"), (int, float))
        and isinstance(base_walk.get("cash_baseline_mean_return"), (int, float))
    ) else "NOT VERIFIED"

    business_statuses = {
        "public_l1_identity_boundary": "PASS" if contract.get("status") == "PASS" else "NOT VERIFIED",
        "observable_activity_analysis": "PASS" if (
            network.get("status") == "PASS" and bool(network.get("activity_state"))
        ) else "NOT VERIFIED",
        "source_freshness": "NOT VERIFIED",
        "cost_slippage_calibration": business_gates.get("cost_slippage_model", "NOT VERIFIED"),
        "liquidity_capacity": business_gates.get("liquidity_capacity", "NOT VERIFIED"),
        "corporate_action_point_in_time": business_gates.get("corporate_action_adjustment", "NOT VERIFIED"),
        "leakage_point_in_time": business_gates.get("leakage_safe_time_split", "NOT VERIFIED"),
        "survivorship_precommitted_universe": business_gates.get("survivorship_selection_control", "NOT VERIFIED"),
        "walk_forward_holdout_power": business_gates.get("oos_walk_forward", "NOT VERIFIED"),
        "dependence_aware_bootstrap": business_gates.get("bootstrap", "NOT VERIFIED"),
        "ablation_replication": business_gates.get("ablation", "NOT VERIFIED"),
        "regime_stability": business_gates.get("stability", "NOT VERIFIED"),
        "multiple_testing_search_family": business_gates.get("multiple_testing_correction", "NOT VERIFIED"),
        "baseline_comparison": baseline_comparison,
        "economic_signal_qualification_decision": (
            "PASS" if business_real.get("business_qualification_status") == "PASS"
            and isinstance(business_real.get("economic_signal_qualified"), bool)
            else "NOT VERIFIED"
        ),
        "capital_deployment_safety": (
            "PASS" if business_real.get("capital_deployment_ready") is False else "NOT VERIFIED"
        ),
    }

    engineering = coverage(acceptance.get("engineering_required", []), engineering_statuses)
    business_completion = coverage(acceptance.get("business_required", []), business_statuses)
    final_gate = "PASS" if engineering["status"] == "PASS" and business_completion["status"] == "PASS" else "FAIL"

    manifest = {
        "status": "CANDIDATE_ONLY" if final_gate != "PASS" else "FINAL_ELIGIBLE_PENDING_FORMAL_RELEASE",
        "source_sha": source_sha,
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "acceptance_contract_sha256": file_hash("ACCEPTANCE_CONTRACT.json"),
        "main_sha256": main_hash,
        "updater_sha256": file_hash("dist/RealMoneyFinanceUpdater.exe"),
        "diagnostic_gates": diagnostic_gates,
        "engineering_completion": engineering,
        "business_completion": business_completion,
        "business_method_execution_status": business.get("status", "NOT VERIFIED"),
        "business_qualification_status": business_real.get("business_qualification_status", "NOT VERIFIED"),
        "business_qualification_gaps": business_real.get("qualification_gaps", {}),
        "economic_signal_qualified": business_real.get("economic_signal_qualified", False),
        "capital_deployment_ready": business_real.get("capital_deployment_ready", False),
        "final_gate": final_gate,
        "delivery_allowed": final_gate == "PASS",
        "note": "Frozen required-gate denominator; only literal PASS counts complete. Candidate/workflow success is not Final.",
    }
    Path("candidate_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
