"""Score ONLY a frozen 11-model receipt against publisher-verified draw history.

An evaluated score is not an issuer-certified prize claim. Predraw status is
separately checked against the nominal publisher draw time in Asia/Shanghai.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from research.supercompute.v47_integrated import score_result
from research.supercompute.v47_models import canonical, validate_history

DRAW_TIME = {"ssq": time(21, 15), "dlt": time(21, 25)}
CHINA = ZoneInfo("Asia/Shanghai")


def verify_publisher_history(game, history_path, official_receipt_path):
    receipt = json.loads(Path(official_receipt_path).read_bytes())
    if (receipt.get("schema") != "SSQDLT_V47_LIVE_ISSUER_INGEST_V1"
            or receipt.get("status") != "OVERLAP_VERIFIED"
            or receipt.get("publisher_issues_matched") is not True
            or game not in receipt.get("games", {})):
        raise ValueError("not a matching verified live publisher receipt")
    rows = json.loads(Path(history_path).read_bytes())["draws"]
    validate_history(rows, game)
    digest = hashlib.sha256(canonical(rows)).hexdigest()
    if digest != receipt["games"][game]["history_sha256"]:
        raise ValueError("draws modified after publisher validation")
    return {str(r["issue"]): r for r in rows}, receipt["games"][game]


def score_issued_frozen(game, frozen_path, official_history, official_receipt):
    history, provenance = verify_publisher_history(
        game, official_history, official_receipt)
    raw = Path(frozen_path).read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    doc = json.loads(raw)
    if (doc.get("schema") != "SSQDLT_V47_UNIFIED_FROZEN_V1"
            or doc.get("source", {}).get("game") != game
            or doc.get("source", {}).get("ticket_count") != 11):
        raise ValueError("not a 11-row frozen model report for this game")
    issue = str(doc["source"]["target_issue"])
    if issue not in history:
        return {"status": "DRAW_NOT_YET_IN_PUBLISHER_TABLE",
                "game": game, "issue": issue, "frozen_sha256": file_sha}
    actual = history[issue]
    outcome = score_result(frozen_path, file_sha, actual)
    if outcome["ticket_count"] != 11:
        raise ValueError("not all eleven models were scored")
    stamp = datetime.fromisoformat(doc["created_utc"])
    if stamp.tzinfo is None:
        raise ValueError("untrusted naive freeze timestamp")
    planned = datetime.combine(datetime.fromisoformat(actual["draw_date"]).date(),
                               DRAW_TIME[game], tzinfo=CHINA)
    created_before_nominal_draw = stamp < planned
    return {
        "schema": "SSQDLT_V47_PUBLISHED_DRAW_SCORE_V1",
        "game": game, "issue": issue,
        "status": "PUBLISHED_DRAW_SCORED",
        "publisher_confirmed_overlap": True,
        "signed_issuer_data": False,
        "frozen_sha256": file_sha,
        "draw": actual,
        "publisher_raw_sha256": provenance["raw_sha256"],
        "publisher_source_url": provenance["source_url"],
        "freeze_created_utc": doc["created_utc"],
        "nominal_draw_time_china": planned.isoformat(),
        "frozen_before_nominal_draw": created_before_nominal_draw,
        "trusted_predraw_seal": False,
        "model_scores": outcome["per_model_score"],
        "count": outcome["ticket_count"],
    }


def score_directory(frozen_dir, source_dir, output_dir):
    """Create-only score receipts; late draws remain pending, not invented."""
    root = Path(frozen_dir)
    results = []
    for game in ("ssq", "dlt"):
        h = Path(source_dir) / f"{game}-verified-history.json"
        receipt = Path(source_dir) / "official-ingest-receipt.json"
        if not h.is_file() or not receipt.is_file():
            raise FileNotFoundError("trusted publisher source missing")
        for frozen in sorted(root.glob(f"{game}-*-v47-unified.json")):
            score = score_issued_frozen(game, frozen, h, receipt)
            if score["status"] == "DRAW_NOT_YET_IN_PUBLISHER_TABLE":
                results.append({"status": "PENDING", "game": game,
                                "issue": score["issue"]})
                continue
            dest = Path(output_dir) / f"{game}-{score['issue']}-score.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as file:
                file.write(canonical(score))
            results.append({"status": "SCORED", "game": game,
                            "issue": score["issue"], "file": str(dest),
                            "count": 11,
                            "predraw_by_nominal_time": score["frozen_before_nominal_draw"]})
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frozen-dir", type=Path, required=True)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    print("V47_LIVE_SCORE=" + json.dumps(
        score_directory(args.frozen_dir, args.source_dir, args.output_dir),
        ensure_ascii=False))


if __name__ == "__main__":
    main()
