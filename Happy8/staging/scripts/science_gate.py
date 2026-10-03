from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.domain import Draw
from happy8.science import validate_history


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if source.get("status") != "PASS":
        raise SystemExit("official network evidence is not PASS")
    draws_raw = source.get("draws")
    if not isinstance(draws_raw, list) or not draws_raw:
        raise SystemExit("official network evidence does not contain canonical draws")
    draws = [
        Draw.from_values(row["issue"], row["draw_date"], row["numbers"])
        for row in draws_raw
    ]
    report = validate_history(draws, canonical_hash=str(source.get("canonical_hash") or ""))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Method/software acceptance may pass while edge_state honestly remains NO_EDGE.
    # The release workflow separately remains NOT FINAL until prospective, Windows,
    # same-hash, repository-independence and final release gates are satisfied.
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
    protocol_ok = (
        set(protocol) == required_protocol
        and all(value == "PASS" for value in protocol.values())
    )
    ok = (
        report.get("status") == "PASS"
        and report.get("software_verdict") == "PASS"
        and protocol_ok
        and report.get("canonical_hash") == source.get("canonical_hash")
        and report.get("gates", {}).get("data_integrity") == "PASS"
        and report.get("gates", {}).get("sample_size") == "PASS"
        and report.get("gates", {}).get("oos_size") == "PASS"
        and (report.get("edge_state") == "VALIDATED_EDGE" or (
            report.get("edge_state") == "NO_EDGE"
            and report.get("dan_state") == "NULL_DAN"
            and not report.get("formal_dan")
            and report.get("production_model") == "uniform_baseline"
        ))
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
