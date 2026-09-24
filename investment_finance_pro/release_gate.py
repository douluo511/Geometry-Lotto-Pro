from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HARD_GATES = [
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui","self_test","contract_test",
    "fault_injection","real_network","windows_build","exact_exe","gui_smoke","same_hash",
]

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()

def evaluate(payload: dict, tested: Path, final: Path) -> dict:
    source = payload.get("gates", {})
    gates = {name: source.get(name, "UNKNOWN") for name in HARD_GATES}
    tested_hash = sha256_file(tested) if tested.exists() else None
    final_hash = sha256_file(final) if final.exists() else None
    if not tested_hash or not final_hash:
        gates["exact_exe"] = "FAIL"
    if not tested_hash or tested_hash != final_hash:
        gates["same_hash"] = "FAIL"
    failures = {k: v for k, v in gates.items() if v != "PASS"}
    return {
        "final_gate": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "gates": gates,
        "tested_sha256": tested_hash,
        "final_sha256": final_hash,
        "failures": failures,
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--tested-exe", required=True)
    p.add_argument("--final-exe", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    result = evaluate(
        json.loads(Path(args.input).read_text(encoding="utf-8-sig")),
        Path(args.tested_exe),
        Path(args.final_exe),
    )
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["final_gate"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
