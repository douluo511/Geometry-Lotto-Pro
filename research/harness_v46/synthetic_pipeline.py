"""In-memory SHADOW prediction/freeze/score/walk-forward demonstration.

Only INVENTED synthetic draws, generated future outcomes after the forecast
batch is frozen. Strictly NO certified predraw seal, official data, real
forecast eligibility, persistent ledger, formal A, or live source effects.

The model source and permanent workflow stay unchanged. This subprocess/CI
research smoke is not the official V4.7 closed_loop controller.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import random
import sqlite3

from . import core


def score_frozen_synthetic(conn, run_id: str, snapshot: dict, synthetic_outcome: dict) -> dict:
    """Score ONLY the exact immutable prediction payload read from SQLite.

    A comparison to a freshly recomputed prediction is insufficient to prove
    which bytes were frozen. Read the stored bytes, hash and validate them.
    Score is read-only and does NOT add any true official-result evidence.
    """
    if (not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("provenance"), dict)
            or snapshot["provenance"].get("status") != "SYNTHETIC_FIXTURE_NOT_OFFICIAL"):
        raise ValueError("SYNTHETIC_ONLY_NO_OFFICIAL_AUTHENTICATION")
    core.validate_study_snapshot(snapshot)
    if (not isinstance(synthetic_outcome, dict)
            or synthetic_outcome.get("lottery") != snapshot["lottery"]
            or str(synthetic_outcome.get("issue")) != str(snapshot["target_issue"])):
        raise core.GateError("wrong synthetic target issue or lottery")
    context = conn.execute(
        "SELECT target_issue,snapshot_sha256,as_of,sales_cutoff "
        "FROM run_context WHERE run_id=? AND lottery=?",
        (run_id, snapshot["lottery"]),
    ).fetchone()
    expected_context = (
        str(snapshot["target_issue"]), core.digest(snapshot),
        snapshot["as_of"], snapshot["sales_cutoff"],
    )
    if tuple(context or ()) != expected_context:
        raise core.GateError("SYNTHETIC_FROZEN_CONTEXT_MISMATCH")

    rows = conn.execute(
        "SELECT model,payload,prediction_sha256,evidence_class "
        "FROM predictions WHERE run_id=? AND lottery=? ORDER BY model",
        (run_id, snapshot["lottery"]),
    ).fetchall()
    if not rows:
        raise core.GateError("SYNTHETIC_FROZEN_PREDICTIONS_MISSING")
    scores: dict[str, dict] = {}
    for model, payload, saved_sha, evidence_class in rows:
        if (model not in core.MODELS or model in scores
                or evidence_class != "SHADOW"
                or hashlib.sha256(payload.encode("utf-8")).hexdigest() != saved_sha):
            raise core.GateError("SYNTHETIC_FROZEN_PAYLOAD_TAMPERED")
        predicted = json.loads(payload)
        core.validate_forecast(predicted, snapshot)
        if predicted["model"] != model or predicted["formal_a_eligible"] is not False:
            raise core.GateError("SYNTHETIC_FROZEN_MODEL_IDENTITY_MISMATCH")
        scores[model] = core.score(predicted, synthetic_outcome)
    return {model: scores[model] for model in core.MODELS if model in scores}


def _invent_outcome(snapshot: dict, seed: int, period: int) -> dict:
    rules = core.RULES[snapshot["lottery"]]
    # This generator does not consume the registered Random NULL seed or its
    # random engine; it is intentionally independent of core.forecast().
    rng = random.Random(f"SYNTHETIC-OUTCOME-v1|{snapshot['lottery']}|{seed}|{period}")
    return {
        "lottery": snapshot["lottery"], "issue": snapshot["target_issue"],
        "front": sorted(rng.sample(range(1, rules["pool"] + 1), rules["front"])),
        "back": sorted(rng.sample(range(1, rules["back_pool"] + 1), rules["back"])),
    }


def _advance_synthetic_snapshot(snapshot: dict, outcome: dict) -> dict:
    next_snapshot = deepcopy(snapshot)
    original_draw_at = core.dt(snapshot["target_draw_at"])
    published = original_draw_at + timedelta(hours=1)
    next_snapshot["draws"].append({
        "issue": str(snapshot["target_issue"]),
        "front": list(outcome["front"]),
        "back": list(outcome["back"]),
        "drawn_at": original_draw_at.isoformat(),
        "published_at": published.isoformat(),
        "draw_date": original_draw_at.date().isoformat(),
    })
    next_snapshot["target_issue"] = str(int(snapshot["target_issue"]) + 1)
    next_snapshot["as_of"] = (original_draw_at + timedelta(hours=2)).isoformat()
    next_snapshot["sales_cutoff"] = (original_draw_at + timedelta(days=2)).isoformat()
    next_snapshot["target_draw_at"] = (original_draw_at + timedelta(days=3)).isoformat()
    core.validate_study_snapshot(next_snapshot)
    return next_snapshot


def run_synthetic_walk_forward(
    game: str, *, seed: int, periods: int = 2, allow_real_outcomes: bool = False
) -> dict:
    """Demonstrate in-memory freeze/read-back/score across invented future draws.

    A walk-forward synthetic test cannot establish real predictive validity.
    `periods` is limited to prevent accidental unbounded CI simulations.
    """
    from .research_stack import synthetic_fixture, _int
    if allow_real_outcomes:
        raise ValueError("SYNTHETIC_ONLY_NO_OFFICIAL_AUTHENTICATION")
    if game not in core.RULES:
        raise ValueError("UNKNOWN_LOTTERY")
    _int(seed, 0, 2**32 - 1, "SEED")
    _int(periods, 1, 5, "PERIODS")
    snapshot = synthetic_fixture(game, seed=seed)
    db = sqlite3.connect(":memory:")
    try:
        core.init_ledger(db)
        reports = []
        for period in range(periods):
            run_id = f"SYNTHETIC-LOCAL-{game}-{seed}-{period}"
            core.validate_study_snapshot(snapshot)
            frozen_at = snapshot["as_of"]  # invented clock, NOT a trusted seal
            with db:
                for model in core.MODELS:
                    predicted = core.forecast(snapshot, model)
                    core.freeze_shadow(db, run_id, snapshot, predicted, frozen_at)
            frozen_count = db.execute(
                "SELECT COUNT(*) FROM predictions WHERE run_id=? AND lottery=?",
                (run_id, game),
            ).fetchone()[0]
            if frozen_count != len(core.MODELS):
                raise core.GateError("INCOMPLETE_SYNTHETIC_FROZEN_ROSTER")

            # Only now generate the simulated future lottery outcome. Replaying
            # independent synthetic outcomes is NOT an official draw.
            outcome = _invent_outcome(snapshot, seed, period)
            scored = score_frozen_synthetic(db, run_id, snapshot, outcome)
            if len(scored) != len(core.MODELS):
                raise core.GateError("INCOMPLETE_SYNTHETIC_SCORE_ROSTER")
            rows = db.execute(
                "SELECT model,payload,prediction_sha256 FROM predictions "
                "WHERE run_id=? AND lottery=?",
                (run_id, game),
            ).fetchall()
            by_model = {}
            for model, payload, sha in rows:
                prediction = json.loads(payload)
                by_model[model] = {
                    "frozen_sha256": sha,
                    "ranking_first_two": prediction["primary_d2"],
                    "synthetic_outcome_front": list(outcome["front"]),
                    **scored[model],
                }
            reports.append({
                "period_index": period + 1,
                "target_issue": snapshot["target_issue"],
                "snapshot_sha256": core.digest(snapshot),
                "models": {m: by_model[m] for m in core.MODELS},
                "frozen_count": frozen_count,
                "score_count": len(scored),
                "frozen_at": frozen_at,
                "evidence_class": "SYNTHETIC_SHADOW_ONLY",
            })
            if period + 1 < periods:
                snapshot = _advance_synthetic_snapshot(snapshot, outcome)

        total = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        frozen_events = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='LOCAL_SHADOW_FREEZE'"
        ).fetchone()[0]
        if total != periods * len(core.MODELS) or frozen_events != total:
            raise core.GateError("INCOMPLETE_SYNTHETIC_FREEZE_AUDIT")
        return {
            "status": "SYNTHETIC_LOCAL_ONLY", "game": game, "periods": periods,
            "source": "INVENTED_DRAW_HISTORY", "db_location": "MEMORY_ONLY",
            "models": list(core.MODELS),
            "random_null_model": "random_null",
            "frozen_predictions": total,
            "freeze_audit_events": frozen_events,
            "scores_computed": total,
            "walk_forward": reports,
            "synthetic_d2_success_counts": {
                model: sum(item["models"][model]["D2"] for item in reports)
                for model in core.MODELS
            },
            "trusted_predraw_seal": False,
            "official_draws_admitted": False,
            "real_predictive_edge_claimed": False,
            "formal_A": 0, "edge": "NO_EDGE",
        }
    finally:
        db.close()
