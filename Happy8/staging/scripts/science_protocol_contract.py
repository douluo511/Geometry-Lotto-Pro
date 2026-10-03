from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.domain import Draw
from happy8.science import validate_history


def build_synthetic_history(count: int = 500) -> list[Draw]:
    rng = random.Random(20261003)
    start = date(2020, 1, 1)
    draws: list[Draw] = []
    for index in range(count):
        issue = f"{2020001 + index:07d}"
        draw_date = (start + timedelta(days=index)).isoformat()
        numbers = sorted(rng.sample(range(1, 81), 20))
        draws.append(Draw.from_values(issue, draw_date, numbers))
    return draws


def canonical_hash(draws: list[Draw]) -> str:
    raw = json.dumps(
        [draw.to_dict() for draw in draws],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    draws = build_synthetic_history()
    report = validate_history(draws, canonical_hash=canonical_hash(draws))

    required_protocol = {
        "candidate_pool_independent_validation",
        "multi_window_perturbation",
        "multi_seed_perturbation",
        "reality_check_executed",
        "holm_correction_executed",
        "leave_one_period_out_executed",
        "leakage_challenge",
        "canonical_hash_bound",
    }
    protocol = report.get("protocol_gates", {})
    if set(protocol) != required_protocol:
        raise SystemExit(f"protocol gate denominator drifted: {sorted(protocol)}")
    failed = {key: value for key, value in protocol.items() if value != "PASS"}
    if failed:
        raise SystemExit(f"scientific protocol contract failed: {failed}")

    pool = report.get("candidate_pool")
    if not isinstance(pool, list) or len(pool) != 7:
        raise SystemExit("candidate pool must contain exactly seven frozen candidates")
    if any(int(row.get("oos_n", -1)) != 260 for row in pool):
        raise SystemExit("candidate pool OOS alignment drifted")

    lopo = report.get("leave_one_period_out")
    if not isinstance(lopo, list) or len(lopo) != 6:
        raise SystemExit("leave-one-period-out denominator must contain six periods")
    if any(int(row.get("holdout_n", 0)) <= 0 for row in lopo):
        raise SystemExit("leave-one-period-out emitted an empty period")

    reality = report.get("reality_check", {})
    reality_p = float(reality.get("p_value", -1))
    if not 0.0 <= reality_p <= 1.0:
        raise SystemExit("Reality Check p-value outside [0,1]")

    adjusted = report.get("multiple_testing", {}).get("adjusted_p", {})
    if set(adjusted) != {row["model"] for row in pool}:
        raise SystemExit("Holm family does not match candidate pool")
    if any(not 0.0 <= float(value) <= 1.0 for value in adjusted.values()):
        raise SystemExit("Holm adjusted p-value outside [0,1]")

    if report.get("leakage_challenge", {}).get("status") != "PASS":
        raise SystemExit("future-mutation leakage challenge did not pass")
    if report.get("edge_state") != "NO_EDGE":
        raise SystemExit("short synthetic history must not be promoted to VALIDATED_EDGE")
    if report.get("dan_state") != "NULL_DAN" or report.get("formal_dan"):
        raise SystemExit("NO_EDGE synthetic history emitted formal dan")
    if report.get("production_model") != "uniform_baseline":
        raise SystemExit("non-qualified synthetic history escaped to a production candidate")

    summary = {
        "schema": "happy8-scientific-protocol-contract-v1",
        "status": "PASS",
        "synthetic_only": True,
        "draw_count": len(draws),
        "oos_n": report["oos"]["n"],
        "protocol_gates": protocol,
        "edge_state": report["edge_state"],
        "dan_state": report["dan_state"],
        "candidate_models": [row["model"] for row in pool],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
