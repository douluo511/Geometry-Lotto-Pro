from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HARD_GATES = [
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui","self_test","contract_test",
    "fault_injection","real_network","windows_build","exact_exe","gui_smoke","same_hash","business_content",
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
    a = p.parse_args()
    gates_src = json.loads(Path(a.gate_input).read_text(encoding="utf-8-sig")).get("gates", {})
    gates = {k: gates_src.get(k, "UNKNOWN") for k in HARD_GATES}
    acceptance = json.loads(Path(a.acceptance).read_text(encoding="utf-8-sig"))
    exe = Path(a.exe)
    actual_hash = sha256(exe) if exe.exists() else None
    if acceptance.get("final_release_gate") != "PASS" or int(acceptance.get("hard_fail_count", 999)) != 0:
        gates["exact_exe"] = "FAIL"
    if not actual_hash or actual_hash != acceptance.get("sha256"):
        gates["same_hash"] = "FAIL"
    failures = {k: v for k, v in gates.items() if v != "PASS"}
    report = {
        "final_gate": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "gates": gates,
        "exe_sha256": actual_hash,
        "failures": failures,
    }
    Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 2

if __name__ == "__main__":
    raise SystemExit(main())
