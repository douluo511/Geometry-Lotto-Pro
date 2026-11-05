"""Local SHADOW CLI. No autonomous data-source or external TSA claims."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .core import MODELS, GateError, canon, forecast, freeze_shadow, init_ledger, score, validate_study_snapshot


def run_forecast(args):
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    validate_study_snapshot(snapshot)
    if str(args.run_id).startswith("V47G-"):
        raise GateError("V47_RUN_ID_REQUIRES_INDEPENDENT_GAME_FREEZE_USE_CLOSED_LOOP")
    if str(args.run_id).startswith("V47-"):
        raise GateError(
            "V47_RUN_ID_REQUIRES_DUAL_GAME_MANIFEST_USE_SCHEDULE"
        )
    # This single-lottery CLI is a legacy SHADOW path; canonical V4.7 RUN_IDs
    # must be derived from the dual-game manifest in schedule.py.
    models = MODELS if args.model == "all" else (args.model,)
    forecasts = [forecast(snapshot, m) for m in models]  # compute before any write
    db = sqlite3.connect(args.database)
    try:
        init_ledger(db)
        actual_local_time = datetime.now(timezone.utc).isoformat()
        receipts = []
        # All-or-nothing across the six model rows for this lottery and run.
        with db:
            for candidate in forecasts:
                sha = freeze_shadow(db, args.run_id, snapshot, candidate, actual_local_time)
                receipts.append({
                "model": candidate["model"],
                "lottery": candidate["lottery"],
                "prediction_sha256": sha,
                "candidates_1_to_5": candidate["candidates_1_to_5"],
                "primary_d2": candidate["primary_d2"],
                "ticket": candidate["ticket"],
                "evidence_class": "SHADOW",
                "external_tsa": "NOT_RUN",
                "parameters_sha256": candidate["parameters_sha256"],
                })
        print(json.dumps({
            "run_id": args.run_id,
            "created_at_local_untrusted": actual_local_time,
            "snapshot_sha256": forecasts[0]["snapshot_sha256"],
            "receipts": receipts,
            "formal_a_eligible": False,
            "warning": "Local timestamps and claimed official data do not establish external proof",
        }, ensure_ascii=False, indent=2))
    finally:
        db.close()


def run_score(args):
    if str(args.run_id).startswith(("V47-", "V47G-")):
        raise GateError("V47_RUN_ID_REQUIRES_CANONICAL_REPLAY_USE_PROSPECTIVE_CYCLE_OR_CLOSED_LOOP")
    result = json.loads(Path(args.official_result).read_text(encoding="utf-8"))
    db = sqlite3.connect("file:" + str(Path(args.database).resolve()) + "?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT payload,prediction_sha256 FROM predictions "
            "WHERE run_id=? AND lottery=? ORDER BY model",
            (args.run_id, result["lottery"]),
        ).fetchall()
    finally:
        db.close()
    if not rows:
        raise GateError("no frozen predictions")
    scores = []
    for payload, sha in rows:
        if hashlib.sha256(payload.encode()).hexdigest() != sha:
            raise GateError("stored prediction hash mismatch")
        prediction = json.loads(payload)
        scores.append({
            "model": prediction["model"],
            "prediction_sha256": sha,
            "score": score(prediction, result),
            "evidence_class": "SHADOW",
        })
    print(json.dumps({
        "run_id": args.run_id,
        "lottery": result["lottery"],
        "issue": str(result["issue"]),
        "scores": scores,
        "warning": "Result source and record authenticity not independently verified; NO_EDGE",
    }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="V4.7 dual lottery SHADOW runner")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("forecast")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--database", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--model", choices=("all",) + MODELS, default="all")
    q = sub.add_parser("score")
    q.add_argument("--database", required=True)
    q.add_argument("--run-id", required=True)
    q.add_argument("--official-result", required=True)
    args = parser.parse_args()
    try:
        if args.command == "forecast":
            run_forecast(args)
        else:
            run_score(args)
    except (GateError, sqlite3.Error, OSError, KeyError, ValueError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
