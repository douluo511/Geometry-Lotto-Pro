from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "SSQ"


def _read(name: str) -> dict[str, Any]:
    path = EVIDENCE / name
    if not path.exists():
        return {"status": "MISSING", "_path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            return {"status": "INVALID", "_path": str(path)}
        value["_path"] = str(path)
        return value
    except Exception as exc:
        return {"status": "INVALID", "error": f"{type(exc).__name__}: {exc}", "_path": str(path)}


def _pass(report: dict[str, Any]) -> bool:
    return str(report.get("status", "")).upper() == "PASS"


def _check_pass(acceptance: dict[str, Any], name: str) -> bool:
    row = (acceptance.get("checks") or {}).get(name) or {}
    return (
        str(row.get("status", "")).upper() == "PASS"
        and int(row.get("exit_code", 0)) == 0
        and row.get("exe_hash_matches") is True
    )


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    arch = _read("ARCHITECTURE_GATE.json")
    business = _read("BUSINESS_GATE.json")
    unit_gate = _read("UNIT_GATE.json")
    net_contract = _read("NETCLIENT_CONTRACT_GATE.json")
    source_self = _read("source-self.json")
    source_live = _read("source-live-update.json")
    fault_names = ["integrity-tamper", "offline-failclosed", "corrupt-repair"]
    source_faults = {name: _read(f"source-{name}.json") for name in fault_names}
    acceptance = _read("WINDOWS_EXACT_EXE_ACCEPTANCE.json")
    gui_click = _read("physical_gui_click.json")

    gates = {
        key: ("PASS" if value == "PASS" else "FAIL")
        for key, value in (arch.get("gates") or {}).items()
    }
    for required in [
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient", "storage",
        "engine", "evidence", "service", "ui",
    ]:
        gates.setdefault(required, "FAIL")

    gates["self_test"] = "PASS" if _pass(source_self) and _check_pass(acceptance, "self") else "FAIL"
    gates["unit_test"] = "PASS" if _pass(unit_gate) else "FAIL"
    gates["contract_test"] = "PASS" if _pass(net_contract) else "FAIL"
    gates["integration_test"] = "PASS" if all(
        _check_pass(acceptance, name) for name in ("update", "predict", "audit", "gui")
    ) else "FAIL"
    gates["fault_injection"] = "PASS" if (
        all(_pass(source_faults[name]) for name in fault_names)
        and all(_check_pass(acceptance, name) for name in fault_names)
    ) else "FAIL"

    live_result = source_live.get("result") if isinstance(source_live.get("result"), dict) else {}
    gates["real_network"] = "PASS" if (
        _pass(source_live)
        and str(live_result.get("crosscheck_status", "")).upper() == "PASS"
        and _check_pass(acceptance, "update")
    ) else "FAIL"

    exe = Path(a.exe)
    actual_hash = _sha256(exe)
    acceptance_hash = str(acceptance.get("sha256") or "")
    all_acceptance_checks_hash_bound = bool(acceptance.get("checks")) and all(
        row.get("exe_hash_matches") is True
        for row in (acceptance.get("checks") or {}).values()
        if isinstance(row, dict)
    )
    windows_ok = (
        str(acceptance.get("runner_os", "")).lower() == "windows"
        and str(acceptance.get("windows_exact_exe_acceptance", "")).upper() == "PASS"
        and int(acceptance.get("hard_fail_count", 999)) == 0
    )
    science_ok = _check_pass(acceptance, "science")
    random_worlds_ok = all(
        _check_pass(acceptance, name)
        for name in ("random-world-101", "random-world-202", "random-world-303")
    )
    gates["business_validation"] = "PASS" if (
        _pass(business) and science_ok and _check_pass(acceptance, "audit")
    ) else "FAIL"
    gates["counterexample_validation"] = "PASS" if random_worlds_ok else "FAIL"
    gates["reversal_validation"] = "PASS" if (
        random_worlds_ok
        and _pass(source_faults["offline-failclosed"])
        and _pass(source_faults["integrity-tamper"])
        and _check_pass(acceptance, "audit")
    ) else "FAIL"

    gates["windows_build"] = "PASS" if windows_ok else "FAIL"
    gates["exact_exe"] = "PASS" if windows_ok and actual_hash and actual_hash == acceptance_hash else "FAIL"
    gates["gui_smoke"] = "PASS" if (
        _pass(gui_click)
        and _check_pass(acceptance, "gui")
        and _check_pass(acceptance, "default-gui-launch")
    ) else "FAIL"
    gates["same_hash"] = "PASS" if (
        actual_hash is not None
        and actual_hash == acceptance_hash
        and all_acceptance_checks_hash_bound
    ) else "FAIL"
    gates["business_content"] = "PASS" if _pass(business) else "FAIL"

    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "schema": "ssq-mother-gate-input-v2",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "gates": gates,
        "failures": failures,
        "exe_sha256": actual_hash,
        "acceptance_sha256": acceptance_hash or None,
        "evidence_status": {
            "architecture": arch.get("status", "MISSING"),
            "business": business.get("status", "MISSING"),
            "unit": unit_gate.get("status", "MISSING"),
            "netclient_contract": net_contract.get("status", "MISSING"),
            "source_self": source_self.get("status", "MISSING"),
            "source_live": source_live.get("status", "MISSING"),
            "source_faults": {k: v.get("status", "MISSING") for k, v in source_faults.items()},
            "windows_acceptance": acceptance.get("windows_exact_exe_acceptance", acceptance.get("status", "MISSING")),
            "physical_gui_click": gui_click.get("status", "MISSING"),
        },
        "rule": "Only current-run explicit PASS evidence can produce PASS; missing/unknown/warning/pending/skipped/unavailable all fail closed.",
    }
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
