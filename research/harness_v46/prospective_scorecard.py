"""Read-only SHADOW feedback bridge: frozen predictions -> supplied result -> D2 card.

This code cannot authenticate an official result, trusted clock, publication
time or external pre-draw seal. It never modifies a forecasting model, ledger,
formal study or future target. Local time fields are consistency guards only.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import convergence as cv
from . import frozen_replay
from .core import MODELS, RULES, GateError, canon, digest, dt, load_registered_snapshot
from .statistics import FAIR_D2

SCHEMA = "V47-SHADOW-D2-FEEDBACK-1"


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _readonly_connection(db_path):
    p = Path(db_path).resolve()
    if not p.is_file():
        raise GateError("SHADOW_LEDGER_NOT_FOUND")
    conn = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def replay_shadow_feedback(db_path, run_id, outcome, *, observed_at=None):
    """Make one deterministic diagnostic receipt from a persisted six-model batch.

    Result data are CALLER_UNVERIFIED, regardless of any caller-supplied label.
    A local pre-cutoff frozen_at is NOT proof of a trusted pre-draw timestamp.
    """
    if not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("V47_REGISTERED_RUN_REQUIRED")
    conn = _readonly_connection(db_path)
    try:
        original = frozen_replay.resolve_scorecard(conn, run_id)
    finally:
        conn.close()
    if original is not None:
        return original.replay_shadow_feedback(
            db_path, run_id, outcome, observed_at=observed_at)
    if not isinstance(outcome, dict) or set(outcome) != {
        "lottery", "issue", "front", "back", "drawn_at"
    }:
        raise GateError("STRICT_UNVERIFIED_OUTCOME_SCHEMA_REQUIRED")
    game, issue = outcome["lottery"], outcome["issue"]
    if (game not in RULES or not isinstance(issue, str)
            or not issue.isascii() or not issue.isdigit()):
        raise GateError("INVALID_UNVERIFIED_OUTCOME_IDENTITY")
    try:
        claimed_draw_time = dt(outcome["drawn_at"])
    except (TypeError, ValueError) as exc:
        raise GateError("INVALID_UNVERIFIED_OUTCOME_TIME") from exc

    # A claimed future draw time is not permission to score before the actual
    # locally observed target window. This clock is still UNTRUSTED evidence.
    observed = datetime.now(timezone.utc) if observed_at is None else observed_at
    if (not isinstance(observed, datetime) or observed.tzinfo is None
            or observed.utcoffset() is None):
        raise GateError("SCORING_OBSERVATION_CLOCK_MUST_BE_AWARE")
    conn = _readonly_connection(db_path)
    try:
        batch_sha256 = cv.check_complete_batch(conn, run_id, game)
        snapshot = frozen_replay.load_snapshot(conn, run_id, game)
        if observed < dt(snapshot["target_draw_at"]):
            raise GateError("SCORE_BEFORE_LOCKED_TARGET_DRAW_TIME")
        if claimed_draw_time > observed:
            raise GateError("OUTCOME_CLAIMED_DRAW_TIME_IN_FUTURE")
        if str(snapshot["target_issue"]) != issue:
            raise GateError("OUTCOME_TARGET_ISSUE_MISMATCH")
        if claimed_draw_time < dt(snapshot["target_draw_at"]):
            raise GateError("OUTCOME_CLAIMED_BEFORE_TARGET_DRAW")
        rows = conn.execute(
            "SELECT model,payload,frozen_at,evidence_class FROM predictions "
            "WHERE run_id=? AND lottery=? ORDER BY model", (run_id, game)
        ).fetchall()
        if len(rows) != len(MODELS) or {x[0] for x in rows} != set(MODELS):
            raise GateError("INCOMPLETE_FROZEN_D2_VECTOR")
        frozen = {}
        for model, raw_payload, frozen_at, evidence_class in rows:
            if evidence_class != "SHADOW":
                raise GateError("NONSHADOW_FROZEN_PREDICTION")
            try:
                stamped = dt(frozen_at)
            except (TypeError, ValueError) as exc:
                raise GateError("INVALID_LOCAL_FREEZE_TIME") from exc
            if not (dt(snapshot["as_of"]) <= stamped < dt(snapshot["sales_cutoff"])
                    and stamped < claimed_draw_time):
                raise GateError("FREEZE_OUTSIDE_LOCKED_PREDRAW_WINDOW")
            prediction = json.loads(raw_payload)
            frozen[model] = {
                "primary_d2": prediction["primary_d2"],
                "d1_to_d5": prediction["candidates_1_to_5"],
                "prediction_sha256": digest(prediction),
                "locally_frozen_at_untrusted": frozen_at,
            }
    finally:
        conn.close()

    # cv.score_readonly independently reopens the ledger and replays each
    # registered model against its original stored snapshot.
    scored = cv.score_readonly(db_path, run_id, outcome)
    values = scored["scores"]
    if set(values) != set(MODELS):
        raise GateError("INCOMPLETE_SCORING_VECTOR")
    all_models = {}
    for model in MODELS:
        row = values[model]
        if any(type(row.get("D" + str(k))) is not int
               or row["D" + str(k)] not in (0, 1) for k in range(1, 6)):
            raise GateError("INVALID_DIAGNOSTIC_D1_D5")
        all_models[model] = {**frozen[model], **row}
    report = {
        "schema": SCHEMA,
        "run_id": run_id,
        "lottery": game,
        "target_issue": issue,
        "prediction_batch_sha256": batch_sha256,
        "outcome_claimed_drawn_at_untrusted": outcome["drawn_at"],
        "outcome_sha256": digest(outcome),
        "outcome_authenticity": "CALLER_UNVERIFIED",
        "predraw_external_seal": "NOT_VERIFIED",
        "scorer_source_sha256": _source_sha256(),
        "models": all_models,
        "fair_d2_baseline": FAIR_D2[game],
        "evidence_class": "SHADOW_DIAGNOSTIC_ONLY",
        "formal_A": 0,
        "decision": "NO_EDGE",
    }
    report["receipt_sha256"] = digest(report)
    return report


def summarize_shadow_feedback(cards):
    """Descriptive cumulative D2 rates only; not preregistered significance."""
    if not isinstance(cards, list) or not cards:
        raise GateError("NONEMPTY_SHADOW_FEEDBACK_REQUIRED")
    seen, scorer_hash = set(), None
    bucket = {game: [] for game in RULES}
    for card in cards:
        if not isinstance(card, dict) or card.get("schema") != SCHEMA:
            raise GateError("INVALID_SHADOW_FEEDBACK_SCHEMA")
        receipt = {k: v for k, v in card.items() if k != "receipt_sha256"}
        if digest(receipt) != card.get("receipt_sha256"):
            raise GateError("SHADOW_FEEDBACK_RECEIPT_CHANGED")
        if (card.get("evidence_class") != "SHADOW_DIAGNOSTIC_ONLY"
                or card.get("formal_A") != 0 or type(card.get("formal_A")) is not int
                or card.get("decision") != "NO_EDGE"
                or card.get("outcome_authenticity") != "CALLER_UNVERIFIED"
                or card.get("predraw_external_seal") != "NOT_VERIFIED"):
            raise GateError("UNVERIFIED_SCORECARD_CANNOT_PROMOTE_AUTHORITY")
        game, issue = card.get("lottery"), card.get("target_issue")
        if (game not in RULES or not isinstance(issue, str)
                or not issue.isascii() or not issue.isdigit()):
            raise GateError("INVALID_FEEDBACK_TARGET")
        # Preserve the frozen spelling in receipts, but count one numeric target
        # once even if another ledger used a leading-zero issue alias.
        key = game, str(int(issue))
        if key in seen:
            raise GateError("DUPLICATE_TARGET_IN_FEEDBACK")
        seen.add(key)
        if scorer_hash is None:
            scorer_hash = card.get("scorer_source_sha256")
        if (scorer_hash != card.get("scorer_source_sha256")
                or not isinstance(scorer_hash, str) or len(scorer_hash) != 64):
            raise GateError("MIXED_SCORER_SOURCE_IDENTITIES")
        if card.get("fair_d2_baseline") != FAIR_D2[game]:
            raise GateError("FAIR_BASELINE_MISMATCH")
        values = card.get("models")
        if not isinstance(values, dict) or set(values) != set(MODELS):
            raise GateError("INCOMPLETE_STUDY_FEEDBACK_VECTOR")
        for model, val in values.items():
            if (not isinstance(val, dict)
                    or type(val.get("D2")) is not int
                    or val["D2"] not in (0, 1)
                    or not isinstance(val.get("primary_d2"), list)
                    or len(val["primary_d2"]) != 2
                    or val.get("primary_d2") != val.get("d1_to_d5", [])[:2]):
                raise GateError("INVALID_FROZEN_D2_FEEDBACK")
        bucket[game].append(card)

    results = {}
    for game, entries in bucket.items():
        n = len(entries)
        if not n:
            continue
        null_hits = sum(c["models"]["random_null"]["D2"] for c in entries)
        models = {}
        for model in MODELS:
            hits = sum(c["models"][model]["D2"] for c in entries)
            wins = sum(c["models"][model]["D2"] == 1
                       and c["models"]["random_null"]["D2"] == 0 for c in entries)
            losses = sum(c["models"][model]["D2"] == 0
                         and c["models"]["random_null"]["D2"] == 1 for c in entries)
            models[model] = {
                "draws": n,
                "d2_hits": hits,
                "d2_hit_rate": hits / n,
                "fair_baseline": FAIR_D2[game],
                "observed_minus_fair": hits / n - FAIR_D2[game],
                "paired_wins_vs_null": wins,
                "paired_losses_vs_null": losses,
                "observed_minus_same_draw_null": (hits - null_hits) / n,
            }
        results[game] = models
    return {
        "status": "SHADOW_UNVERIFIED_CUMULATIVE_DIAGNOSTIC",
        "scorer_source_sha256": scorer_hash,
        "unique_lottery_issue_count": len(seen),
        "games": results,
        "outcome_authenticity": "CALLER_UNVERIFIED",
        "preregistration_verified": False,
        "predraw_external_seal": "NOT_VERIFIED",
        "formal_A": 0,
        "decision": "NO_EDGE",
    }
