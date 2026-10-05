from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import random
import sys

# Direct script execution sets sys.path[0] to Happy8/staging/scripts. Bind this
# contract to the exact sibling package without changing any science threshold.
STAGING_ROOT = Path(__file__).resolve().parents[1]
if str(STAGING_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGING_ROOT))

from happy8.domain import Draw
from happy8.science import validate_history


METHOD_GATES = (
    "candidate_pool_independent_validation",
    "multi_window_multi_seed",
    "reality_check_max_model_null",
    "holm_multiple_testing",
    "leave_one_period_out",
    "leakage_future_mutation",
    "false_gain_elimination",
)


def main() -> int:
    rng = random.Random(20261005)
    start = date(2024, 1, 1)
    draws = []
    for index in range(600):
        numbers = sorted(rng.sample(range(1, 81), 20))
        draws.append(
            Draw.from_values(
                str(2020001 + index),
                (start + timedelta(days=index)).isoformat(),
                numbers,
            )
        )

    canonical_payload = [draw.to_dict() for draw in draws]
    canonical_hash = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    report = validate_history(draws, canonical_hash=canonical_hash)
    gates = report.get("gates", {})
    failures = []
    for name in METHOD_GATES:
        if gates.get(name) != "PASS":
            failures.append(f"{name}={gates.get(name)!r}")
    pool = report.get("candidate_pool", {})
    if pool.get("candidate_count") != 5:
        failures.append(f"candidate_count={pool.get('candidate_count')!r}")
    if pool.get("reality_check", {}).get("status") != "PASS":
        failures.append("reality_check_not_executed")
    if report.get("multi_window_seed_robustness", {}).get("case_count") != 9:
        failures.append("window_seed_denominator_changed")
    if report.get("leakage_challenge", {}).get("status") != "PASS":
        failures.append("future_mutation_leakage_challenge_failed")
    if report.get("edge_state") != "NO_EDGE":
        failures.append(f"random_fixture_edge_state={report.get('edge_state')!r}")
    if report.get("dan_state") != "NULL_DAN" or report.get("formal_dan"):
        failures.append("random_fixture_emitted_formal_dan")
    if gates.get("prospective") != "PENDING":
        failures.append("prospective_gate_was_promoted")

    evidence = {
        "schema": "happy8-science-method-contract-v1",
        "status": "PASS" if not failures else "FAIL",
        "fixture": "deterministic_uniform_random_20_of_80",
        "fixture_seed": 20261005,
        "draw_count": len(draws),
        "canonical_hash": canonical_hash,
        "method_gates": {name: gates.get(name) for name in METHOD_GATES},
        "candidate_count": pool.get("candidate_count"),
        "reality_check": pool.get("reality_check"),
        "window_seed_case_count": report.get("multi_window_seed_robustness", {}).get("case_count"),
        "leakage_status": report.get("leakage_challenge", {}).get("status"),
        "edge_state": report.get("edge_state"),
        "dan_state": report.get("dan_state"),
        "formal_dan": report.get("formal_dan"),
        "failures": failures,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
