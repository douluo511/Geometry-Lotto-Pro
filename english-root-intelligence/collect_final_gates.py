from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from gate_common import current_report, gate_status, run_identity
from physical_gui_evidence import validate_physical
from release_gate import HARD_GATES, BUSINESS_GATES
from updater_evidence import validate_atomic_checks

ROOT = Path(__file__).resolve().parent

def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NOT VERIFIED", "_path": str(path), "reason": "missing evidence"}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"status": "FAIL", "_path": str(path), "reason": "evidence is not an object"}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "_path": str(path)}

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
    p.add_argument("--updater-exe", required=True)
    p.add_argument("--final-updater-exe", required=True)
    p.add_argument("--repository-evidence", required=True)
    p.add_argument("--updater-windows", required=True)
    p.add_argument("--software-release-evidence", required=True)
    p.add_argument("--final-artifact-evidence", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    github_sha = (os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA"))
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
    updater = read(ROOT / "updater_gate.json")
    updater_windows = read(Path(a.updater_windows))
    repository = read(Path(a.repository_evidence))
    release = read(Path(a.software_release_evidence))
    final_artifact = read(Path(a.final_artifact_evidence))
    static = read(ROOT / "static_compile_gate.json")

    reports = {
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
        "updater": updater,
        "updater_windows": updater_windows,
        "repository": repository,
        "release": release,
        "final_artifact": final_artifact,
        "static_compile": static,
    }
    current = {name: current_report(report, github_sha) for name, report in reports.items()}

    gates = {k: ("PASS" if str(v).upper() == "PASS" else "FAIL") for k, v in (arch.get("gates") or {}).items()}
    arch_names = [
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient",
        "storage", "engine", "evidence", "service", "ui",
    ]
    for name in arch_names:
        gates.setdefault(name, "FAIL")
        if not current["architecture"]:
            gates[name] = "FAIL"

    gates["unit_test"] = "PASS" if current["unit"] and passed(unit) else "FAIL"
    gates["contract_test"] = "PASS" if current["contract"] and passed(contract) else "FAIL"
    gates["integration_test"] = "PASS" if current["integration"] and passed(integration) else "FAIL"
    gates["fault_injection"] = "PASS" if current["fault"] and passed(fault) else "FAIL"

    distinct = set(real.get("distinct_source_ids") or [])
    gates["real_network"] = "PASS" if (
        current["real_network"]
        and passed(real)
        and str(real.get("network_gate", "")).upper() == "PASS"
        and int(real.get("source_count", 0)) >= 4
        and len(distinct) >= 4
        and len(real.get("sources") or []) >= 4
        and all(bool(row.get("raw_b64")) and bool(row.get("attempt_ledger")) for row in real.get("sources") or [])
    ) else "FAIL"

    bv_bound = current["business_validation"]
    gates["business_validation"] = "PASS" if bv_bound and str(business_validation.get("business_validation", "")).upper() == "PASS" else "FAIL"
    gates["counterexample_validation"] = "PASS" if bv_bound and str(business_validation.get("counterexample_validation", "")).upper() == "PASS" else "FAIL"
    gates["reversal_validation"] = "PASS" if bv_bound and str(business_validation.get("reversal_validation", "")).upper() == "PASS" else "FAIL"

    source_exe = Path(a.exe)
    final_exe = Path(a.final_exe)
    source_hash = sha256(source_exe)
    final_hash = sha256(final_exe)
    exact_hash = exact.get("exe_sha256")
    gates["self_test"] = "PASS" if current["exact_candidate"] and str((exact.get("self_test") or {}).get("status", "")).upper() == "PASS" else "FAIL"
    gates["windows_build"] = "PASS" if current["exact_candidate"] and str(exact.get("windows_build", "")).upper() == "PASS" else "FAIL"
    gates["exact_exe"] = "PASS" if current["exact_candidate"] and str(exact.get("exact_exe", "")).upper() == "PASS" and source_hash == exact_hash else "FAIL"

    buttons = physical.get("buttons") or []
    physical_ok = validate_physical(physical, github_sha) and physical.get("exe_sha256") == source_hash
    gates["gui_smoke"] = "PASS" if (
        str((exact.get("gui_smoke") or {}).get("status", "")).upper() == "PASS" and physical_ok
    ) else "FAIL"
    gates["same_hash"] = "PASS" if source_hash and source_hash == final_hash == exact_hash else "FAIL"
    gates["business_content"] = "PASS" if current["business"] and passed(business) else "FAIL"
    gates["repository_independence"] = gate_status(repository, github_sha)
    if gates["repository_independence"] == "PASS" and (
        repository.get("repository") == "douluo511/Geometry-Lotto-Pro"
        or not repository.get("checks") or any(row.get("status") != "PASS" for row in repository["checks"].values())
    ):
        gates["repository_independence"] = "FAIL"
    updater_hash = sha256(Path(a.updater_exe))
    final_updater_hash = sha256(Path(a.final_updater_exe))
    updater_windows_ok = (current["updater_windows"] and passed(updater_windows)
                          and updater_windows.get("exit_code") == 0
                          and int(updater_windows.get("pid") or 0) > 0
                          and (updater_windows.get("self_test") or {}).get("status") == "PASS"
                          and updater_hash and updater_hash == updater_windows.get("updater_exe_sha256"))
    gates["updater_process"] = "PASS" if updater_windows_ok else "FAIL"
    gates["updater_exact_exe"] = "PASS" if updater_windows_ok else "FAIL"
    gates["updater_atomic_rollback"] = "PASS" if current["updater"] and validate_atomic_checks(updater) else "FAIL"
    gates["updater_real_network"] = gate_status(release, github_sha)
    gates["updater_same_hash"] = "PASS" if updater_windows_ok and updater_windows.get("same_hash") is True and updater_hash == final_updater_hash else "FAIL"
    gates["static_compile"] = "PASS" if current["static_compile"] and passed(static) else "FAIL"
    gates["final_artifact"] = gate_status(final_artifact, github_sha)

    gates = {name: gates.get(name, "FAIL") for name in HARD_GATES}
    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "schema": "english-root-mother-gate-input-v1",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "github_sha": github_sha,
        **run_identity(),
        "gates": gates,
        "failures": failures,
        "exe_sha256": source_hash,
        "final_exe_sha256": final_hash,
        "updater_exe_sha256": updater_hash,
        "final_updater_exe_sha256": final_updater_hash,
        "engineering_gate_count": len(HARD_GATES) - len(BUSINESS_GATES),
        "business_gate_count": len(BUSINESS_GATES),
        "engineering_completion": 100 * sum(value == "PASS" for key, value in gates.items() if key not in BUSINESS_GATES) / (len(HARD_GATES) - len(BUSINESS_GATES)),
        "business_completion": 100 * sum(gates[key] == "PASS" for key in BUSINESS_GATES) / len(BUSINESS_GATES),
        "current_run_binding": current,
        "evidence_status": {name: report.get("status", "NOT VERIFIED") for name, report in reports.items()},
        "rule": "Only current-run explicit PASS evidence counts; missing/warning/pending/skipped/unavailable/unknown fail closed.",
    }
    report["combined_completion"] = min(report["engineering_completion"], report["business_completion"])
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
