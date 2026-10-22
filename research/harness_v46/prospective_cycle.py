"""V4.7 forecast-before-draw / score-after-draw CLI, SHADOW research only.

Never recompute or edit an earlier frozen prediction to score it. A qualified
future D2 advantage requires separately authenticated official data, a trusted
pre-draw seal and preregistered prospective repeated observations.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .core import MODELS, RULES, GateError
from .convergence import check_complete_batch, score_readonly
from .schedule import scheduled_once


def frozen_forecast_report(database, run_id):
    """Verified immutable six-arm cards for both games, read-only."""
    if not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("DUAL_GAME_V47_RUN_ID_REQUIRED")
    path = Path(database).resolve()
    conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        games = {}
        for game in ("SSQ", "DLT"):
            batch_sha = check_complete_batch(conn, run_id, game)
            rows = conn.execute(
                "SELECT model,payload,prediction_sha256,frozen_at,evidence_class "
                "FROM predictions WHERE run_id=? AND lottery=?",
                (run_id, game),
            ).fetchall()
            by_model = {model: (payload, sha, stamp, klass)
                        for model, payload, sha, stamp, klass in rows}
            if set(by_model) != set(MODELS):
                raise GateError("INCOMPLETE_FROZEN_MODEL_SET")
            models = []
            target = None
            for model in MODELS:
                payload, sha, stamp, klass = by_model[model]
                if klass != "SHADOW":
                    raise GateError("UNQUALIFIED_FROZEN_EVIDENCE_CLASS")
                prediction = json.loads(payload)
                issue = prediction["target_issue"]
                if target is None:
                    target = issue
                elif target != issue:
                    raise GateError("FROZEN_TARGET_ISSUE_CONFLICT")
                models.append({
                    "model": model,
                    "candidates_1_to_5": prediction["candidates_1_to_5"],
                    "primary_d2": prediction["primary_d2"],
                    "ticket": prediction["ticket"],
                    "prediction_sha256": sha,
                    "model_version": prediction["version"],
                    "parameters_sha256": prediction["parameters_sha256"],
                    "model_source_sha256": prediction["model_source_sha256"],
                    "frozen_at_local_untrusted": stamp,
                    "evidence_class": "SHADOW",
                })
            games[game] = {
                "target_issue": target,
                "prediction_batch_sha256": batch_sha,
                "models": models,
            }
    finally:
        conn.close()
    return {
        "schema": "V47-PROSPECTIVE-SHADOW-FORECAST-1",
        "run_id": run_id, "games": games,
        "forecast_source": "PINNED_IMMUTABLE_LEDGER_ONLY",
        "independently_trusted_predraw_seal": False,
        "official_source_authenticity": "NOT_VERIFIED",
        "external_tsa": "NOT_VERIFIED",
        "formal_A": 0, "decision": "NO_EDGE",
    }


def forecast_on_demand(snapshots, database, *, now=None):
    """Manual before-cutoff run uses SAME immutable dual-game freeze logic."""
    if not isinstance(snapshots, dict) or set(snapshots) != set(RULES):
        raise GateError("BOTH_GAME_SNAPSHOTS_REQUIRED")
    receipt = scheduled_once(
        snapshots, database, now=now, require_delivery_window=False
    )
    if receipt.get("status") != "SHADOW_ONLY":
        raise GateError("SHADOW_FORECAST_NOT_FROZEN")
    result = frozen_forecast_report(database, receipt["run_id"])
    result["freeze_receipt"] = receipt
    return result


def evaluate_after_draw(database, run_id, result_bundle):
    """Read-only per-draw D2 comparison; no update/backfill/auto learning."""
    frozen = frozen_forecast_report(database, run_id)
    if not isinstance(result_bundle, dict) or set(result_bundle) != set(RULES):
        raise GateError("EXACTLY_TWO_GAME_RESULTS_REQUIRED")
    scored = {}
    for game in ("SSQ", "DLT"):
        result = result_bundle[game]
        if not isinstance(result, dict) or result.get("lottery") != game:
            raise GateError("DRAW_RESULT_GAME_IDENTITY_MISMATCH")
        if str(result.get("issue")) != frozen["games"][game]["target_issue"]:
            raise GateError("RESULT_ISSUE_DIFFERS_FROM_FROZEN_ISSUE")
        review = score_readonly(database, run_id, result)
        if review["prediction_batch_sha256"] != frozen["games"][game]["prediction_batch_sha256"]:
            raise GateError("FROZEN_BATCH_CHANGED_BETWEEN_SHOW_AND_SCORE")
        scored[game] = review
    return {
        "schema": "V47-PROSPECTIVE-SHADOW-SCORE-1",
        "run_id": run_id,
        "frozen_forecast_reference": {
            game: {"target_issue": frozen["games"][game]["target_issue"],
                   "prediction_batch_sha256": frozen["games"][game]["prediction_batch_sha256"]}
            for game in ("SSQ", "DLT")
        },
        "games": scored,
        "outcome_source": "CALLER_UNVERIFIED",
        "paired_control": "SAME_DRAW_RANDOM_NULL",
        "eligibility_for_prospective_edge": "BLOCKED_UNAUTHENTICATED_EVIDENCE",
        "improvement_policy": "NEXT_VERSION_ONLY_NEVER_REWRITE_FROZEN_HISTORY",
        "formal_A": 0, "decision": "NO_EDGE",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4.7 dual-game SHADOW prospective research cycle")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("forecast", help="Create a local pre-cutoff SHADOW freeze with actual six-model picks")
    f.add_argument("--snapshot-bundle", required=True)
    f.add_argument("--database", required=True)
    v = sub.add_parser("show", help="Read actual frozen selections, never recompute numbers")
    v.add_argument("--database", required=True)
    v.add_argument("--run-id", required=True)
    s = sub.add_parser("score", help="Compare frozen selections to caller-supplied results, read-only")
    s.add_argument("--database", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--result-bundle", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "forecast":
            snapshot = json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
            result = forecast_on_demand(snapshot, args.database)
        elif args.command == "show":
            result = frozen_forecast_report(args.database, args.run_id)
        else:
            observed = json.loads(Path(args.result_bundle).read_text(encoding="utf-8"))
            result = evaluate_after_draw(args.database, args.run_id, observed)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (GateError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
