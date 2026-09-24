from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_MARKERS = [
    "unit_tests.pass",
    "contract_tests.pass",
    "fault_injection.pass",
    "python_self_test.pass",
    "real_network.pass",
    "windows_build.pass",
    "exact_exe_self_test.pass",
    "gui_smoke.pass",
    "same_hash.pass",
    "final_exe_self_test.pass",
    "final_gui_smoke.pass",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def evaluate(evidence_dir: Path, candidate_exe: Path, final_exe: Path) -> dict:
    marker_state = {name: (evidence_dir / name).exists() for name in REQUIRED_MARKERS}
    candidate_exists = candidate_exe.exists()
    final_exists = final_exe.exists()
    candidate_hash = sha256(candidate_exe) if candidate_exists else None
    final_hash = sha256(final_exe) if final_exists else None
    same_hash = bool(candidate_hash and final_hash and candidate_hash == final_hash)

    checks = {
        **marker_state,
        "candidate_exe_exists": candidate_exists,
        "final_exe_exists": final_exists,
        "candidate_final_same_hash": same_hash,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "final_gate": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "candidate_sha256": candidate_hash,
        "final_sha256": final_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--candidate-exe", required=True)
    parser.add_argument("--final-exe", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = evaluate(
        Path(args.evidence_dir),
        Path(args.candidate_exe),
        Path(args.final_exe),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["final_gate"] == "PASS" else 10


if __name__ == "__main__":
    raise SystemExit(main())
