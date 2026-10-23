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

from .core import MODELS, RULES, GateError, digest, validate_run_manifest_record
from .convergence import check_complete_batch, score_readonly
from .schedule import scheduled_once
from .statistics import evaluate_shadow_d2


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
    scoring_inputs = {}
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
        # Persist the exact *canonical caller-supplied* outcome values in the
        # returned audit receipt. This is reproducibility, not source verification.
        scoring_inputs[game] = {
            "lottery": game,
            "issue": str(result["issue"]),
            "front": list(result["front"]),
            "back": list(result["back"]),
        }
    report = {
        "schema": "V47-PROSPECTIVE-SHADOW-SCORE-1",
        "run_id": run_id,
        "frozen_forecast_reference": {
            game: {"target_issue": frozen["games"][game]["target_issue"],
                   "prediction_batch_sha256": frozen["games"][game]["prediction_batch_sha256"]}
            for game in ("SSQ", "DLT")
        },
        "games": scored,
        "outcome_source": "CALLER_UNVERIFIED",
        "scoring_inputs": {
            "result_bundle": scoring_inputs,
            "result_bundle_sha256": digest(scoring_inputs),
            "authenticated_official_source": False,
            "timestamp_trust": "NONE",
        },
        "paired_control": "SAME_DRAW_RANDOM_NULL",
        "eligibility_for_prospective_edge": "BLOCKED_UNAUTHENTICATED_EVIDENCE",
        "improvement_policy": "NEXT_VERSION_ONLY_NEVER_REWRITE_FROZEN_HISTORY",
        "formal_A": 0, "decision": "NO_EDGE",
    }
    # Binds BOTH game results, score values, frozen batch hashes, and explicit
    # SHADOW limitations. This SHA is self-reported, not a trusted time seal.
    report["score_receipt_sha256"] = digest(report)
    return report



def summarize_prospective_receipts(database, receipts):
    """Replay only ledger-backed score receipts; NEVER certify results or sampling.

    All submitted score reports are compared byte-for-byte at the semantic
    JSON-object level to a fresh read-only replay from the frozen original
    predictions and the receipt's *caller-supplied* outcome bundle. This blocks
    tampered score vectors and missing arms, not fabricated source data, missing
    past draws, selective reporting or post-hoc sampling.
    """
    if not isinstance(receipts, list) or not receipts:
        raise GateError("EMPTY_STUDY_RECEIPTS")
    indexed = {}
    for claimed in receipts:
        if not isinstance(claimed, dict) or claimed.get("schema") != "V47-PROSPECTIVE-SHADOW-SCORE-1":
            raise GateError("INVALID_SCORE_RECEIPT")
        run_id = claimed.get("run_id")
        if not isinstance(run_id, str) or not run_id.startswith("V47-"):
            raise GateError("INVALID_STUDY_RUN_ID")
        if run_id in indexed:
            raise GateError("DUPLICATE_STUDY_RUN")
        claimed_hash = claimed.get("score_receipt_sha256")
        if (not isinstance(claimed_hash, str) or
                claimed_hash != digest({k: v for k, v in claimed.items()
                                        if k != "score_receipt_sha256"})):
            raise GateError("INVALID_SCORE_RECEIPT_HASH")
        bundle = claimed.get("scoring_inputs", {}).get("result_bundle")
        if not isinstance(bundle, dict) or set(bundle) != set(RULES):
            raise GateError("INCOMPLETE_STUDY_RESULTS")
        # Recompute from the frozen six-arm prediction ledger. Do NOT trust
        # embedded model scores, hashes, NULL bits, or claimed source labels.
        actual = evaluate_after_draw(database, run_id, bundle)
        if claimed != actual:
            raise GateError("SCORE_RECEIPT_REPLAY_MISMATCH")
        indexed[run_id] = actual

    # All recorded V4.7 freezes in this *local ledger* must be represented.
    # Otherwise a caller can submit only favorable draw receipts and obtain
    # a misleading statistical summary. This proves neither a complete
    # official calendar nor protection against privileged DB replacement.
    path = Path(database).resolve()
    conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        ledger_run_ids = {row[0] for row in conn.execute(
            "SELECT run_id FROM run_manifests"
        )}
    finally:
        conn.close()
    missing = ledger_run_ids - set(indexed)
    if missing:
        raise GateError("STUDY_COVERAGE_MISSING_FROZEN_RUNS:" + str(len(missing)))
    if set(indexed) != ledger_run_ids:
        raise GateError("STUDY_ROSTER_COVERAGE_MISMATCH")

    rows = []
    issue_seen = set()
    for run_id in sorted(indexed):
        verified = indexed[run_id]
        for game in ("SSQ", "DLT"):
            issue = verified["frozen_forecast_reference"][game]["target_issue"]
            key = (game, issue)
            if key in issue_seen:
                raise GateError("DUPLICATE_STUDY_GAME_ISSUE")
            issue_seen.add(key)
            scores = verified["games"][game]["scores"]
            if set(scores) != set(MODELS):
                raise GateError("INCOMPLETE_STUDY_MODEL_SCORES")
            rows.append({
                "lottery": game,
                "issue": issue,
                "scores": {m: scores[m]["D2"] for m in MODELS},
            })
    rows.sort(key=lambda r: (r["lottery"], int(r["issue"])))
    # Fixed enumerated arithmetic family (the historical registration of the
    # hypotheses is still NOT verified).
    family = [
        {"hypothesis_id": f"V47-{game}-{model}", "lottery": game, "model": model}
        for game in ("SSQ", "DLT") for model in MODELS
    ]
    analysis = evaluate_shadow_d2(rows, family, expected_family_size=12)
    identities = [{"run_id": rid, "score_receipt_sha256":
                   indexed[rid]["score_receipt_sha256"]} for rid in sorted(indexed)]
    return {
        "schema": "V47-SHADOW-REPLAYED-PROSPECTIVE-STUDY-1",
        "run_ids": sorted(indexed),
        "score_receipts_sha256": digest(identities),
        "study_rows_sha256": digest(rows),
        "draws_by_game": {game: sum(row["lottery"] == game for row in rows)
                          for game in ("SSQ", "DLT")},
        "forecast_outcome_integrity": "REPLAYED_FROZEN_LEDGER",
        "coverage": "CALLER_SUBMITTED_RECEIPTS_ONLY",
        "local_ledger_roster": {
            "run_count": len(ledger_run_ids),
            "run_ids_sha256": digest(sorted(ledger_run_ids)),
            "status": "ALL_LOCAL_FROZEN_RUNS_PRESENT_NOT_OFFICIAL_SCHEDULE",
        },
        "official_results_authenticated": False,
        "preregistration_verified": False,
        "independent_predraw_timestamp_verified": False,
        "source_authenticity": "NOT_VERIFIED",
        "statistical_analysis": analysis,
        "formal_A": 0,
        "decision": "NO_EDGE",
        "limitations": [
            "Every run registered in this local database must have a receipt, but an external schedule, other databases and privileged replacement remain unverified.",
            "Caller-provided results are replayed for consistency, not independently authenticated as official.",
            "Local SQLite and self-reported hashes do not provide independent predraw custody or RFC3161 proof.",
            "No evidence supports prospective predictive advantage or formal promotion.",
        ],
    }


def build_predraw_commitment(database, run_id):
    """Export deterministic TWO-GAME SHA256 imprint; no TSA request or verification.

    Caller may submit message_imprint_sha256 to an external RFC3161 TSA later.
    Neither this output nor a self-reported timestamp can grant formal A.
    """
    frozen = frozen_forecast_report(database, run_id)
    path = Path(database).resolve()
    conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        manifest = validate_run_manifest_record(conn, run_id)
        manifest_record = conn.execute(
            "SELECT manifest_sha256,evidence_class FROM run_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if manifest is None or manifest_record is None or manifest_record[1] != "SHADOW":
            raise GateError("PREDRAW_COMMITMENT_REQUIRES_SHADOW_MANIFEST")
        manifest_sha = manifest_record[0]
    finally:
        conn.close()
    preimage = {
        "schema": "V47-DUAL-PREDRAW-PREIMAGE-1",
        "run_id": run_id,
        "manifest_sha256": manifest_sha,
        "harness_source_sha256": manifest["harness_source_sha256"],
        "games": {},
    }
    for game in ("SSQ", "DLT"):
        context = manifest["games"][game]
        frozen_game = frozen["games"][game]
        if (context["issue"] != frozen_game["target_issue"]
                or set(x["model"] for x in frozen_game["models"]) != set(MODELS)):
            raise GateError("PREDRAW_COMMITMENT_MODEL_OR_TARGET_CONFLICT")
        models = {m["model"]: m for m in frozen_game["models"]}
        preimage["games"][game] = {
            "target_issue": frozen_game["target_issue"],
            "snapshot_sha256": context["snapshot_sha256"],
            "as_of": context["as_of"],
            "sales_cutoff": context["sales_cutoff"],
            "target_draw_at": context["target_draw_at"],
            "prediction_batch_sha256": frozen_game["prediction_batch_sha256"],
            "prediction_hashes": {
                model: models[model]["prediction_sha256"] for model in MODELS
            },
            "local_freeze_times_untrusted": {
                model: models[model]["frozen_at_local_untrusted"] for model in MODELS
            },
        }
    return {
        "schema": "V47-DUAL-PREDRAW-COMMITMENT-1",
        "preimage": preimage,
        "message_imprint_hash_algorithm": "sha256",
        "message_imprint_sha256": digest(preimage),
        "external_tsa": "NOT_REQUESTED",
        "independent_timestamp_verified": False,
        "official_source_authenticated": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
    }


def verify_predraw_commitment(database, claimed):
    """Read-only deterministic replay, NOT signature/certificate/time verification."""
    if not isinstance(claimed, dict) or claimed.get("schema") != "V47-DUAL-PREDRAW-COMMITMENT-1":
        raise GateError("INVALID_PREDRAW_COMMITMENT_SCHEMA")
    preimage = claimed.get("preimage")
    if not isinstance(preimage, dict) or claimed.get("message_imprint_sha256") != digest(preimage):
        raise GateError("PREDRAW_COMMITMENT_DIGEST_MISMATCH")
    run_id = preimage.get("run_id")
    if not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("INVALID_PREDRAW_COMMITMENT_RUN_ID")
    expected = build_predraw_commitment(database, run_id)
    if claimed != expected:
        raise GateError("PREDRAW_COMMITMENT_LEDGER_MISMATCH")
    return True


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
    st = sub.add_parser("study", help="Recheck frozen per-draw score receipts and summarize SHADOW D2 evidence")
    st.add_argument("--database", required=True)
    st.add_argument("--receipts-file", required=True)
    co = sub.add_parser("commitment", help="Export deterministic dual-game SHA256 imprint; no TSA issued")
    co.add_argument("--database", required=True)
    co.add_argument("--run-id", required=True)
    ve = sub.add_parser("verify-commitment", help="Replay a local commitment, not an independent timestamp")
    ve.add_argument("--database", required=True)
    ve.add_argument("--commitment-file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "forecast":
            snapshot = json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
            result = forecast_on_demand(snapshot, args.database)
        elif args.command == "show":
            result = frozen_forecast_report(args.database, args.run_id)
        elif args.command == "score":
            observed = json.loads(Path(args.result_bundle).read_text(encoding="utf-8"))
            result = evaluate_after_draw(args.database, args.run_id, observed)
        elif args.command == "study":
            receipts = json.loads(Path(args.receipts_file).read_text(encoding="utf-8"))
            result = summarize_prospective_receipts(args.database, receipts)
        elif args.command == "commitment":
            result = build_predraw_commitment(args.database, args.run_id)
        else:
            commitment = json.loads(Path(args.commitment_file).read_text(encoding="utf-8"))
            result = {"replay_matches_local_ledger": verify_predraw_commitment(args.database, commitment),
                      "independent_timestamp_verified": False, "formal_A": 0, "decision": "NO_EDGE"}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (GateError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
