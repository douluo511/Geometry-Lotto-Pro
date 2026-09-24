from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HARD_GATES = [
    "self_test",
    "contract_test",
    "fault_injection",
    "real_network",
    "windows_build",
    "exact_exe",
    "gui_smoke",
    "same_hash",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate(report: dict) -> dict:
    statuses = report.get("gates", {})
    final = "PASS" if all(statuses.get(k) == "PASS" for k in HARD_GATES) else "FAIL"
    return {"final_gate": final, "gates": {k: statuses.get(k, "UNKNOWN") for k in HARD_GATES}}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = evaluate(data)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["final_gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
