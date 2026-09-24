from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tested-exe", required=True)
    p.add_argument("--final-exe", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--evidence", nargs="+", required=True)
    args = p.parse_args()

    tested = Path(args.tested_exe)
    final = Path(args.final_exe)
    failures = []
    evidence_rows = []

    for raw in args.evidence:
        path = Path(raw)
        if not path.exists():
            failures.append(f"missing evidence: {path}")
            evidence_rows.append({"file": str(path), "status": "MISSING"})
            continue
        try:
            data = read_json(path)
            status = data.get("status") or data.get("overall") or data.get("final_gate")
            evidence_rows.append({"file": str(path), "status": status})
            if status != "PASS":
                failures.append(f"{path}: status={status}")
        except Exception as e:
            failures.append(f"{path}: unreadable ({e})")
            evidence_rows.append({"file": str(path), "status": "INVALID"})

    if not tested.exists():
        failures.append("tested EXE missing")
    if not final.exists():
        failures.append("final EXE missing")

    tested_hash = sha256_file(tested) if tested.exists() else None
    final_hash = sha256_file(final) if final.exists() else None
    same_hash = bool(tested_hash and final_hash and tested_hash == final_hash)
    if not same_hash:
        failures.append("same-hash gate failed")

    same_size = tested.exists() and final.exists() and tested.stat().st_size == final.stat().st_size
    if not same_size:
        failures.append("exact-size gate failed")

    final_gate = "PASS" if not failures else "FAIL"
    report = {
        "type": "final_release_gate",
        "final_gate": final_gate,
        "status": final_gate,
        "tested_exe": str(tested),
        "final_exe": str(final),
        "tested_sha256": tested_hash,
        "final_sha256": final_hash,
        "same_hash": same_hash,
        "same_size": same_size,
        "evidence": evidence_rows,
        "failures": failures,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if final_gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
