from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from bind_physical_gui import validate_gui

ROOT = Path(__file__).resolve().parent
VALID_STATES = {"PASS", "FAIL", "NOT VERIFIED", "BLOCKED"}


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NOT VERIFIED"}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"status": "FAIL", "error": "not an object"}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def state(value: Any, default: str = "NOT VERIFIED") -> str:
    text = str(value or default).upper()
    return text if text in VALID_STATES else "FAIL"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--final-exe", required=True)
    p.add_argument("--physical-gui", required=True)
    p.add_argument("--updater-gate", required=True)
    p.add_argument("--updater-windows", required=True)
    p.add_argument("--repository-evidence", required=True)
    p.add_argument("--software-release-evidence", required=True)
    p.add_argument("--final-artifact-evidence", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    current = (os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA"))
    reports = {
        "architecture": read(ROOT / "architecture_gate.json"),
        "business": read(ROOT / "business_gate.json"),
        "unit": read(ROOT / "unit_gate.json"),
        "contract": read(ROOT / "contract_gate.json"),
        "fault": read(ROOT / "fault_gate.json"),
        "integration": read(ROOT / "integration_gate.json"),
        "real_network": read(ROOT / "real_network_evidence.json"),
        "business_validation": read(ROOT / "business_validation_gate.json"),
        "exact": read(ROOT / "exact_candidate_gate.json"),
        "physical": read(Path(args.physical_gui)),
        "updater": read(Path(args.updater_gate)),
        "updater_windows": read(Path(args.updater_windows)),
        "repository": read(Path(args.repository_evidence)),
        "software_release": read(Path(args.software_release_evidence)),
        "final_artifact": read(Path(args.final_artifact_evidence)),
    }

    bound = {
        name: (report.get("github_sha") == current)
        for name, report in reports.items()
    }

    gates = {
        k: ("PASS" if str(v).upper() == "PASS" else "FAIL")
        for k, v in (reports["architecture"].get("gates") or {}).items()
    }
    for name in [
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient",
        "storage", "engine", "evidence", "service", "ui",
    ]:
        gates.setdefault(name, "FAIL")
        if not bound["architecture"]:
            gates[name] = "FAIL"

    def report_pass(name: str) -> bool:
        return bound.get(name, False) and reports[name].get("status") == "PASS"

    gates["unit_test"] = "PASS" if report_pass("unit") else "FAIL"
    gates["contract_test"] = "PASS" if report_pass("contract") else "FAIL"
    gates["fault_injection"] = "PASS" if report_pass("fault") else "FAIL"
    gates["integration_test"] = "PASS" if report_pass("integration") else "FAIL"

    rn = reports["real_network"]
    gates["real_network"] = (
        "PASS" if bound["real_network"] and rn.get("status") == "PASS" and rn.get("network_gate") == "PASS"
        else "FAIL"
    )

    bv = reports["business_validation"]
    gates["business_validation"] = "PASS" if bound["business_validation"] and bv.get("business_validation") == "PASS" else "FAIL"
    gates["counterexample_validation"] = "PASS" if bound["business_validation"] and bv.get("counterexample_validation") == "PASS" else "FAIL"
    gates["reversal_validation"] = "PASS" if bound["business_validation"] and bv.get("reversal_validation") == "PASS" else "FAIL"

    exact = reports["exact"]
    source = Path(args.exe)
    final = Path(args.final_exe)
    sh = sha256(source)
    fh = sha256(final)
    gates["self_test"] = "PASS" if bound["exact"] and (exact.get("self_test") or {}).get("status") == "PASS" else "FAIL"
    gates["windows_build"] = "PASS" if bound["exact"] and exact.get("windows_build") == "PASS" else "FAIL"
    gates["exact_exe"] = "PASS" if bound["exact"] and exact.get("exact_exe") == "PASS" and exact.get("exe_sha256") == sh else "FAIL"

    physical = reports["physical"]
    buttons = physical.get("buttons") or []
    physical_ok = (
        bound["physical"]
        and physical.get("status") == "PASS"
        and physical.get("exe_sha256") == sh
        and len(buttons) == 4
        and validate_gui(physical, sh)
    )
    gates["gui_smoke"] = "PASS" if physical_ok and (exact.get("gui_smoke") or {}).get("status") == "PASS" else "FAIL"
    gates["same_hash"] = "PASS" if sh and sh == fh == exact.get("exe_sha256") else "FAIL"
    gates["business_content"] = "PASS" if report_pass("business") else "FAIL"

    updater = reports["updater"]
    updater_windows = reports["updater_windows"]
    updater_checks = updater.get("checks") if isinstance(updater.get("checks"), dict) else {}
    rollback_names = [
        "normal_atomic_update",
        "permission_replace_failure_rolls_back",
        "health_failure_rolls_back",
        "rollback_failure_retains_recovery_state",
        "restart_recovery_restores_previous_exe",
    ]
    rollback_ok = report_pass("updater") and all(
        (updater_checks.get(name) or {}).get("status") == "PASS"
        for name in rollback_names
    )
    updater_windows_ok = report_pass("updater_windows")
    gates["updater_process"] = "PASS" if report_pass("updater") and report_pass("integration") and updater_windows_ok else "FAIL"
    gates["updater_exact_exe"] = "PASS" if updater_windows_ok and updater_windows.get("updater_exact_exe") == "PASS" else "FAIL"
    gates["updater_atomic_rollback"] = "PASS" if rollback_ok else "FAIL"
    gates["updater_same_hash"] = "PASS" if updater_windows_ok and updater_windows.get("same_hash") is True else "FAIL"

    if bound["software_release"]:
        gates["updater_real_network"] = state(reports["software_release"].get("status"))
    else:
        gates["updater_real_network"] = "NOT VERIFIED"

    if bound["repository"]:
        gates["repository_independence"] = state(reports["repository"].get("status"))
    else:
        gates["repository_independence"] = "NOT VERIFIED"

    if bound["final_artifact"]:
        gates["final_artifact"] = state(reports["final_artifact"].get("status"))
    else:
        gates["final_artifact"] = "NOT VERIFIED"

    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "schema": "guoxue-mother-gate-input-v2",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "github_sha": current,
        "gates": gates,
        "failures": failures,
        "exe_sha256": sh,
        "final_exe_sha256": fh,
        "current_run_binding": bound,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
