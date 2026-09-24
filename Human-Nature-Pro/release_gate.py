from __future__ import annotations
import argparse
import json
from pathlib import Path

HARD_GATES = [
    "purpose_model",
    "five_why",
    "risk_boundary",
    "domain_model",
    "architecture",
    "function_contract",
    "interface_contract",
    "data_source",
    "netclient",
    "storage",
    "engine",
    "evidence",
    "service",
    "ui",
    "self_test",
    "contract_test",
    "fault_injection",
    "real_network",
    "windows_build",
    "exact_exe",
    "gui_smoke",
    "same_hash",
]

def evaluate(payload: dict) -> dict:
    source = payload.get("gates", {})
    gates = {name: source.get(name, "UNKNOWN") for name in HARD_GATES}
    failures = {k: v for k, v in gates.items() if v != "PASS"}
    return {
        "final_gate": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "gates": gates,
        "failures": failures,
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = evaluate(json.loads(Path(args.input).read_text(encoding="utf-8-sig")))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["final_gate"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
