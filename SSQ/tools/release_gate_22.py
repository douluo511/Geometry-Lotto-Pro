from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HARD_GATES = [
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui","self_test","unit_test","contract_test","integration_test",
    "fault_injection","real_network","business_validation","counterexample_validation","reversal_validation",
    "windows_build","exact_exe","gui_smoke","same_hash","business_content",
    "updater_process","updater_exact_exe","updater_atomic_rollback","updater_real_network","updater_same_hash",
    "repository_independence",
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gate-input", required=True)
    p.add_argument("--acceptance", required=True)
    p.add_argument("--exe", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--repository-independent", choices=["PASS", "FAIL"], required=True)
    a = p.parse_args()
    gate_input = json.loads(Path(a.gate_input).read_text(encoding="utf-8-sig"))
    # Never trust a caller-supplied list of PASS strings. Re-derive the result
    # from current-run artifacts and reject a stale or hand-authored manifest.
    from derive_gate_status import derive
    expected = derive(Path(a.acceptance).parent, Path(a.exe), a.repository_independent)
    manifest_matches = (
        gate_input.get("schema") == expected["schema"]
        and gate_input.get("gates") == expected["gates"]
        and gate_input.get("proofs") == expected["proofs"]
        and gate_input.get("commit_sha") == expected["commit_sha"]
    )
    gates = {k: expected["gates"].get(k, "UNKNOWN") for k in HARD_GATES}
    acceptance = json.loads(Path(a.acceptance).read_text(encoding="utf-8-sig"))
    exe = Path(a.exe)
    actual_hash = sha256(exe) if exe.exists() else None
    if (acceptance.get("windows_exact_exe_acceptance") != "PASS"
            or acceptance.get("final_release_gate") != "PENDING"
            or int(acceptance.get("hard_fail_count", 999)) != 0):
        gates["exact_exe"] = "FAIL"
    if not actual_hash or actual_hash != acceptance.get("sha256"):
        gates["same_hash"] = "FAIL"
    failures = {k: v for k, v in gates.items() if v != "PASS"}
    if not manifest_matches:
        failures["gate_input_integrity"] = "FAIL"
    report = {
        "final_gate": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "gates": gates,
        "exe_sha256": actual_hash,
        "failures": failures,
        "gate_input_integrity": "PASS" if manifest_matches else "FAIL",
    }
    Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 2

if __name__ == "__main__":
    raise SystemExit(main())
