from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "MISSING", "_path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"status": "INVALID", "_path": str(path)}
    except Exception as exc:
        return {"status": "INVALID", "error": f"{type(exc).__name__}: {exc}", "_path": str(path)}


def passed(report: dict, key: str = "status") -> bool:
    return str(report.get(key, "")).upper() == "PASS"


def sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--final-exe", required=True)
    p.add_argument("--physical-gui", required=True)
    p.add_argument("--repository-evidence", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    github_sha = (os.environ.get("PSYCHOLOGY_SOURCE_SHA") or os.environ.get("GITHUB_SHA"))
    arch = read(ROOT / "architecture_gate.json")
    business = read(ROOT / "business_gate.json")
    unit = read(ROOT / "unit_gate.json")
    contract = read(ROOT / "contract_gate.json")
    fault = read(ROOT / "fault_gate.json")
    integration = read(ROOT / "integration_gate.json")
    real = read(ROOT / "real_network_evidence.json")
    business_validation = read(ROOT / "business_validation_gate.json")
    exact = read(ROOT / "exact_candidate_gate.json")
    physical = read(Path(a.physical_gui))

    updater_fault = read(ROOT / "updater_gate.json")
    updater_exact = read(ROOT / "updater_exact_candidate_gate.json")
    real_release = read(ROOT / "real_release_validation.json")
    independent = read(Path(a.repository_evidence))
    current_run_reports = {
        "updater_fault": updater_fault, "updater_exact": updater_exact,
        "real_release": real_release, "independent": independent,
        "architecture": arch,
        "business": business,
        "unit": unit,
        "contract": contract,
        "fault": fault,
        "integration": integration,
        "real_network": real,
        "business_validation": business_validation,
        "exact_candidate": exact,
        "physical_gui": physical,
    }
    current_run_binding = {
        name: (bool(github_sha) and report.get("github_sha") == github_sha
                 and bool(os.environ.get("GITHUB_RUN_ID"))
                 and report.get("github_run_id") == os.environ.get("GITHUB_RUN_ID")
                 and report.get("github_run_attempt") == os.environ.get("GITHUB_RUN_ATTEMPT"))
        for name, report in current_run_reports.items()
    }

    gates = {
        k: ("PASS" if str(v).upper() == "PASS" else "FAIL")
        for k, v in (arch.get("gates") or {}).items()
    }
    for required in [
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient", "storage",
        "engine", "evidence", "service", "ui",
    ]:
        gates.setdefault(required, "FAIL")

    arch_bound = current_run_binding["architecture"]
    for name in [
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient", "storage",
        "engine", "evidence", "service", "ui",
    ]:
        if not arch_bound:
            gates[name] = "FAIL"

    gates["self_test"] = "PASS" if current_run_binding["exact_candidate"] and str((exact.get("self_test") or {}).get("status", "")).upper() == "PASS" else "FAIL"
    gates["unit_test"] = "PASS" if current_run_binding["unit"] and passed(unit) else "FAIL"
    gates["contract_test"] = "PASS" if current_run_binding["contract"] and passed(contract) else "FAIL"
    gates["integration_test"] = "PASS" if current_run_binding["integration"] and passed(integration) else "FAIL"
    gates["fault_injection"] = "PASS" if current_run_binding["fault"] and passed(fault) else "FAIL"

    distinct_sources = set(real.get("distinct_source_ids") or [])
    gates["real_network"] = "PASS" if (
        current_run_binding["real_network"]
        and passed(real)
        and str(real.get("network_gate", "")).upper() == "PASS"
        and int(real.get("source_count", 0)) >= 2
        and len(distinct_sources) >= 2
    ) else "FAIL"

    bv_bound = current_run_binding["business_validation"]
    gates["business_validation"] = "PASS" if bv_bound and str(business_validation.get("business_validation", "")).upper() == "PASS" else "FAIL"
    gates["counterexample_validation"] = "PASS" if bv_bound and str(business_validation.get("counterexample_validation", "")).upper() == "PASS" else "FAIL"
    gates["reversal_validation"] = "PASS" if bv_bound and str(business_validation.get("reversal_validation", "")).upper() == "PASS" else "FAIL"

    source_exe = Path(a.exe)
    final_exe = Path(a.final_exe)
    source_hash = sha256(source_exe)
    final_hash = sha256(final_exe)
    exact_hash = exact.get("exe_sha256")
    current_sha_ok = current_run_binding["exact_candidate"]
    physical_hash_ok = (
        current_run_binding["physical_gui"]
        and physical.get("exe_sha256") == source_hash
    )

    gates["windows_build"] = "PASS" if str(exact.get("windows_build", "")).upper() == "PASS" and current_sha_ok else "FAIL"
    gates["exact_exe"] = "PASS" if str(exact.get("exact_exe", "")).upper() == "PASS" and source_hash == exact_hash else "FAIL"
    gates["gui_smoke"] = "PASS" if (
        str((exact.get("gui_smoke") or {}).get("status", "")).upper() == "PASS"
        and physical_hash_ok
        and passed(physical)
        and len(physical.get("buttons") or []) == 4
        and all(str(x.get("status", "")).upper() == "PASS" and x.get("visual_changed") is True for x in (physical.get("buttons") or []))
    ) else "FAIL"
    gates["same_hash"] = "PASS" if source_hash and source_hash == final_hash == exact_hash else "FAIL"
    gates["business_content"] = "PASS" if current_run_binding["business"] and passed(business) else "FAIL"
    def evidence_state(report, bound):
        state = str(report.get("status", "NOT VERIFIED"))
        return state if bound and state in {"PASS", "FAIL", "NOT VERIFIED", "BLOCKED"} else "NOT VERIFIED"
    for key in ("updater_process", "updater_exact_exe", "updater_same_hash"):
        valid = current_run_binding["updater_exact"] and passed(updater_exact) and updater_exact.get("gates", {}).get(key) == "PASS"
        gates[key] = "PASS" if valid else "NOT VERIFIED"
    required_faults = {"manifest_https_trust_fail_closed", "manifest_and_artifact_contract", "bad_hash_fail_closed", "truncated_download_fail_closed", "non_monotonic_no_replace", "normal_atomic_update", "offline_manifest_fail_closed", "download_interruption_fail_closed", "permission_replace_failure_rolls_back", "main_program_occupied_fail_closed", "health_failure_rolls_back", "rollback_failure_retains_recovery_state", "restart_recovery_restores_previous_exe"}
    fault_checks = updater_fault.get("checks", {})
    gates["updater_atomic_rollback"] = "PASS" if current_run_binding["updater_fault"] and passed(updater_fault) and required_faults <= set(fault_checks) and all(fault_checks[x].get("status") == "PASS" for x in required_faults) else "NOT VERIFIED"
    gates["updater_real_network"] = evidence_state(real_release, current_run_binding["real_release"])
    gates["repository_independence"] = evidence_state(independent, current_run_binding["independent"])
    if gates["repository_independence"] == "PASS" and independent.get("repository") == "douluo511/Geometry-Lotto-Pro":
        gates["repository_independence"] = "FAIL"
    gui_operations_pass = gates["gui_smoke"] == "PASS" and physical.get("operation_binding") == "PASS"
    gates["gui_smoke"] = "PASS" if gui_operations_pass and physical.get("acceptance_mode") == "ConfiguredRelease" and physical.get("software_update_release") == "PASS" else ("BLOCKED" if gui_operations_pass and physical.get("acceptance_mode") == "BlockedRelease" else "FAIL")

    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "schema": "psychology-mother-gate-input-v2",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "github_sha": github_sha,
        "gates": gates,
        "failures": failures,
        "exe_sha256": source_hash,
        "final_exe_sha256": final_hash,
        "current_run_binding": current_run_binding,
        "evidence_status": {
            "architecture": arch.get("status", "MISSING"),
            "business_content": business.get("status", "MISSING"),
            "unit": unit.get("status", "MISSING"),
            "contract": contract.get("status", "MISSING"),
            "fault": fault.get("status", "MISSING"),
            "integration": integration.get("status", "MISSING"),
            "real_network": real.get("status", "MISSING"),
            "business_validation": business_validation.get("status", "MISSING"),
            "exact_candidate": exact.get("status", "MISSING"),
            "physical_gui": physical.get("status", "MISSING"),
        },
        "rule": "Only explicit current-run evidence-backed PASS counts; missing/warning/pending/skipped/unavailable/unknown all fail closed.",
    }
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
