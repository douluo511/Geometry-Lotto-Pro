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
    p.add_argument("--output", required=True)
    a = p.parse_args()

    github_sha = os.environ.get("GITHUB_SHA")
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

    gates["self_test"] = "PASS" if str((exact.get("self_test") or {}).get("status", "")).upper() == "PASS" else "FAIL"
    gates["unit_test"] = "PASS" if passed(unit) else "FAIL"
    gates["contract_test"] = "PASS" if passed(contract) else "FAIL"
    gates["integration_test"] = "PASS" if passed(integration) else "FAIL"
    gates["fault_injection"] = "PASS" if passed(fault) else "FAIL"

    distinct_sources = set(real.get("distinct_source_ids") or [])
    gates["real_network"] = "PASS" if (
        passed(real)
        and str(real.get("network_gate", "")).upper() == "PASS"
        and int(real.get("source_count", 0)) >= 2
        and len(distinct_sources) >= 2
    ) else "FAIL"

    gates["business_validation"] = "PASS" if str(business_validation.get("business_validation", "")).upper() == "PASS" else "FAIL"
    gates["counterexample_validation"] = "PASS" if str(business_validation.get("counterexample_validation", "")).upper() == "PASS" else "FAIL"
    gates["reversal_validation"] = "PASS" if str(business_validation.get("reversal_validation", "")).upper() == "PASS" else "FAIL"

    source_exe = Path(a.exe)
    final_exe = Path(a.final_exe)
    source_hash = sha256(source_exe)
    final_hash = sha256(final_exe)
    exact_hash = exact.get("exe_sha256")
    current_sha_ok = not exact.get("github_sha") or exact.get("github_sha") == github_sha

    gates["windows_build"] = "PASS" if str(exact.get("windows_build", "")).upper() == "PASS" and current_sha_ok else "FAIL"
    gates["exact_exe"] = "PASS" if str(exact.get("exact_exe", "")).upper() == "PASS" and source_hash == exact_hash else "FAIL"
    gates["gui_smoke"] = "PASS" if (
        str((exact.get("gui_smoke") or {}).get("status", "")).upper() == "PASS"
        and passed(physical)
        and len(physical.get("buttons") or []) == 4
        and all(str(x.get("status", "")).upper() == "PASS" and x.get("visual_changed") is True for x in (physical.get("buttons") or []))
    ) else "FAIL"
    gates["same_hash"] = "PASS" if source_hash and source_hash == final_hash == exact_hash else "FAIL"
    gates["business_content"] = "PASS" if passed(business) else "FAIL"

    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "schema": "psychology-mother-gate-input-v2",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "github_sha": github_sha,
        "gates": gates,
        "failures": failures,
        "exe_sha256": source_hash,
        "final_exe_sha256": final_hash,
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
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
