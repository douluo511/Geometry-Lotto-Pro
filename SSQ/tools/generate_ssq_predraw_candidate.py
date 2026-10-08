"""Produce a genuine NEXT-issue SSQ forecast Freeze CANDIDATE from live official data.

This generator NEVER writes to GitHub, never calls a fake provider, and never
claims qualified future draw outcomes. Consumers must separately commit exactly
one JSON to the dedicated evidence branch while the draw-date cutoff is future.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "SSQ"))

from glp.engine import make_prediction  # noqa: E402
from glp.sources import build_canonical  # noqa: E402
from glp.util import sha256_json  # noqa: E402

_CN = timezone(timedelta(hours=8))


def generate(*, source_commit: str, today_china: date | None = None,
             canonical_builder=build_canonical) -> dict:
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("SSQ candidate must bind exact GitHub source commit")
    now_day = datetime.now(_CN).date() if today_china is None else today_china
    if not isinstance(now_day, date):
        raise ValueError("invalid China-local calculation date")
    dataset, evidence = canonical_builder()
    if (
        not dataset.draws
        or dataset.crosscheck_status != "PASS"
        or not isinstance(evidence, dict)
        or evidence.get("crosscheck_status") != "PASS"
        or evidence.get("raw_response_status") not in (
            "PENDING_PERSISTENCE", "PERSISTED_AND_VERIFIED"
        )
    ):
        raise ValueError("SSQ official multi-source canonical quorum is not PASS")
    draws = dataset.draws
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("SSQ official draws contain duplicate issue")
    if draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("SSQ official draws not chronologically ordered")
    if not all(d.validate() is None for d in draws):
        raise ValueError("SSQ official draws contain invalid data")
    if sha256_json([d.to_dict() for d in draws]) != dataset.canonical_hash:
        raise ValueError("SSQ canonical SHA-256 does not bind official draw history")
    latest_day = date.fromisoformat(draws[-1].draw_date)
    if latest_day > now_day or (now_day - latest_day).days > 7:
        raise ValueError("SSQ latest official draw is missing, stale or in future")

    prediction, _trace = make_prediction(
        draws, dataset.canonical_hash,
        evidence={"edge_state": "NO_EDGE", "dan_state": "NULL_DAN"}, formal=False,
    )
    target = date.fromisoformat(prediction.target_date)
    if target <= now_day or (target - now_day).days > 7:
        raise ValueError(
            "SSQ target is already on/past China draw date, or too distant: "
            f"china_today={now_day.isoformat()}, "
            f"latest_official_issue={draws[-1].issue}, "
            f"latest_official_date={draws[-1].draw_date}, "
            f"next_target_issue={prediction.to_dict().get('target_issue')}, "
            f"next_target_date={prediction.target_date}; "
            "cannot freeze a same-day or already-drawn candidate without verified cutoff"
        )
    expected = prediction.to_dict()
    if (
        expected["edge_state"] != "NO_EDGE"
        or expected["dan_state"] != "NULL_DAN"
        or expected["canonical_hash"] != dataset.canonical_hash
        or not re.fullmatch(r"20[0-9]{5}", expected["target_issue"])
    ):
        raise ValueError("SSQ candidate attempted unsupported production promotion")
    return {
        "schema": "ssq-prospective-freeze-v1",
        "model_source_commit": source_commit,
        "prediction": expected,
        "source_evidence": {
            "schema": "ssq-live-official-source-candidate-v1",
            "source_mode": evidence.get("verification"),
            "crosscheck_status": dataset.crosscheck_status,
            "crosscheck_count": dataset.crosscheck_count,
            "latest_issue": draws[-1].issue,
            "latest_draw_date": draws[-1].draw_date,
            "canonical_hash": dataset.canonical_hash,
            "draw_count": len(draws),
            "source_receipts_hash": sha256_json(evidence.get("source_receipts", [])),
        },
        "scientific_decision": {
            "qualified_replays": 0,
            "min_prospective_required": 120,
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
            "promotion_authorized": False,
            "production_rho": 0.0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    artifact = generate(source_commit=args.source_commit)
    issue = artifact["prediction"]["target_issue"]
    output = args.output_dir / f"{issue}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("SSQ candidate output exists; overwriting is forbidden")
    data = (json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output.write_bytes(data)
    if not 0 < len(data) <= 50000:
        output.unlink(missing_ok=True)
        raise ValueError("SSQ Freeze candidate exceeds approved blob size")
    print("SSQ_FREEZE_CANDIDATE=" + json.dumps({
        "target_issue": issue,
        "target_date": artifact["prediction"]["target_date"],
        "freeze_hash": artifact["prediction"]["freeze_hash"],
        "source_commit": args.source_commit,
        "official_latest_issue": artifact["source_evidence"]["latest_issue"],
        "official_canonical_hash": artifact["source_evidence"]["canonical_hash"],
        "qualified_replays": 0,
        "promotion_authorized": False,
        "output_file": str(output),
    }, ensure_ascii=False, sort_keys=True))
    print("SSQ_FREEZE_JSON=" + json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
