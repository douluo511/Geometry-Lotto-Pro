"""Unregistered V4.7 statistical + geometry fusion shadow model.

Research hypothesis ONLY. Connects the five PREEXISTING V4.7 statistical
rankers and two geometry rankings from each ORIGINAL game-specific engine.
Optional full-space outputs are heuristic comparison/rerank features.

No measured lottery-machine parameters exist: physical diagnostics have
weight exactly ZERO. No posterior win probabilities or certified calibration.
Never modify core.MODELS, the preregistered Random NULL, formal slots, real
source admission, or any user's persistent prediction ledger.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from math import comb

from . import core

FUSION_ID = "experimental_stat_geometry_v1"
VERSION = "V47-EXPERIMENTAL-FUSION-1"
STAT_MODELS = ("hot60", "ewma", "shrinkmix", "pairwise_d2", "challenger")
GEOMETRY_MODELS = ("geometry_state", "geometry_transition")
FRONT_STAT_WEIGHT = 0.70
FRONT_GEOMETRY_WEIGHT = 0.30
COMBINATION_BONUS = 0.05  # hypothesis, not validated probability
PHYSICAL_WEIGHT = 0.0


def _synthetic_guard(snapshot):
    if (not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("provenance"), dict)
            or snapshot["provenance"].get("status")
            != "SYNTHETIC_FIXTURE_NOT_OFFICIAL"):
        raise ValueError("SYNTHETIC_ONLY_NO_OFFICIAL_AUTHENTICATION")
    core.validate_study_snapshot(snapshot)
    if set(STAT_MODELS) != set(core.MODELS) - {"random_null"}:
        raise ValueError("REGISTERED_V47_MODELS_CHANGED")


def _geometry_projection(snapshot, geometry):
    game = snapshot["lottery"]
    if (not isinstance(geometry, dict)
            or geometry.get("source_engine") != game
            or geometry.get("status") != "RESEARCH_FEATURES_NOT_PHYSICS"
            or geometry.get("formal_A") != 0
            or geometry.get("edge") != "NO_EDGE"
            or geometry.get("real_machine_geometry_observed") is not False
            or geometry.get("validated_official_draws") is not False
            or geometry.get("physical_forecast_supported") is not False):
        raise ValueError("UNVERIFIED_GEOMETRY_PROVENANCE")
    rankings = geometry.get("geometry_rankings")
    if not isinstance(rankings, dict) or set(rankings) != {"front", "back"}:
        raise ValueError("MISSING_COMPLETE_GEOMETRY_RANKINGS")
    rules = core.RULES[game]
    copied = {}
    for area in ("front", "back"):
        size = rules["pool" if area == "front" else "back_pool"]
        values = rankings[area]
        if not isinstance(values, dict) or set(values) != set(GEOMETRY_MODELS):
            raise ValueError("GEOMETRY_COMPONENTS_MISSING")
        copied[area] = {}
        for comp in GEOMETRY_MODELS:
            order = values[comp]
            if (not isinstance(order, list) or len(order) != size
                    or any(type(n) is not int or not 1 <= n <= size for n in order)
                    or len(set(order)) != size):
                raise ValueError("GEOMETRY_RANKING_NOT_COMPLETE_PERMUTATION")
            copied[area][comp] = list(order)

    complete = geometry.get("complete_space")
    if not isinstance(complete, dict):
        raise ValueError("INVALID_FULLSPACE_REPORT")
    if complete and set(complete) != {"front", "back"}:
        raise ValueError("INCOMPLETE_FULLSPACE_REPORT")
    best = {}
    for area, record in complete.items():
        pool = rules["pool" if area == "front" else "back_pool"]
        picks = rules["front" if area == "front" else "back"]
        if (not isinstance(record, dict)
                or record.get("status") != "SOURCE_ENGINE_EXECUTED_RESEARCH_ONLY"
                or record.get("theoretical_legal_combinations") != comb(pool, picks)):
            raise ValueError("UNVERIFIED_FULLSPACE_RESEARCH_RESULT")
        numbers = record.get("best_synthetic_scored_combination")
        if (not isinstance(numbers, list) or len(numbers) != picks
                or any(type(x) is not int or not 1 <= x <= pool for x in numbers)
                or sorted(set(numbers)) != numbers):
            raise ValueError("INVALID_FULLSPACE_BEST_COMBINATION")
        actual = record.get("engine_reported_count")
        if game == "SSQ" and actual != comb(pool, picks):
            raise ValueError("SSQ_FULLSPACE_COUNT_MISMATCH")
        if game == "DLT" and actual is not None:
            raise ValueError("DLT_UNSUPPORTED_ENUMERATION_COUNT_CLAIM")
        best[area] = list(numbers)
    return {
        "source_engine": game,
        "geometry_rankings": copied,
        "comparison_fullspace_best": best,
    }


def _borda(order, pool):
    return {ball: (pool - 1 - idx) / (pool - 1) for idx, ball in enumerate(order)}


def build_research_candidate(
    snapshot: dict, geometry: dict, *, physical_weight: float = 0.0
) -> dict:
    """Produce an independently versioned, SHADOW-ONLY fusion candidate."""
    _synthetic_guard(snapshot)
    if type(physical_weight) not in (float, int) or physical_weight != PHYSICAL_WEIGHT:
        raise ValueError("UNCALIBRATED_PHYSICS_HAS_ZERO_ALLOWED_WEIGHT")
    game = snapshot["lottery"]
    projected = _geometry_projection(snapshot, geometry)
    rules = core.RULES[game]
    pool = rules["pool"]
    stat_orders = {model: core._model_ranking(snapshot, model) for model in STAT_MODELS}
    if any(sorted(order) != list(range(1, pool + 1)) for order in stat_orders.values()):
        raise ValueError("REGISTERED_MODEL_RANKING_INCOMPLETE")
    stat_points = {model: _borda(order, pool) for model, order in stat_orders.items()}
    geo_front = {
        model: _borda(projected["geometry_rankings"]["front"][model], pool)
        for model in GEOMETRY_MODELS
    }
    fullspace_front = projected["comparison_fullspace_best"].get("front", [])
    stat_score = {
        n: sum(stat_points[model][n] for model in STAT_MODELS) / len(STAT_MODELS)
        for n in range(1, pool + 1)
    }
    front_score = {
        n: FRONT_STAT_WEIGHT * stat_score[n] +
           FRONT_GEOMETRY_WEIGHT * sum(geo_front[m][n] for m in GEOMETRY_MODELS)
           / len(GEOMETRY_MODELS) +
           (COMBINATION_BONUS if n in fullspace_front else 0)
        for n in range(1, pool + 1)
    }
    ranked_front = core._rank(front_score)

    back_pool = rules["back_pool"]
    geo_back = {
        model: _borda(projected["geometry_rankings"]["back"][model], back_pool)
        for model in GEOMETRY_MODELS
    }
    fullspace_back = projected["comparison_fullspace_best"].get("back", [])
    back_score = {
        n: sum(geo_back[m][n] for m in GEOMETRY_MODELS) / len(GEOMETRY_MODELS)
           + (COMBINATION_BONUS if n in fullspace_back else 0)
        for n in range(1, back_pool + 1)
    }
    ranked_back = core._rank(back_score)
    front = sorted(ranked_front[:rules["front"]])
    back = sorted(ranked_back[:rules["back"]])
    return {
        "version": VERSION,
        "model": FUSION_ID,
        "lottery": game,
        "target_issue": str(snapshot["target_issue"]),
        "snapshot_sha256": core.digest(snapshot),
        "geometry_projection_sha256": core.digest(projected),
        "registered_core_source_sha256": core.model_source_sha256(),
        "model_families": ["registered_five_statistical", "two_real_geometry_components"],
        "contributing_models": list(STAT_MODELS),
        "geometry_components": list(GEOMETRY_MODELS),
        "front_statistical_weight": FRONT_STAT_WEIGHT,
        "front_geometry_weight": FRONT_GEOMETRY_WEIGHT,
        "physical_signal_weight": PHYSICAL_WEIGHT,
        "full_space_search_used": bool(projected["comparison_fullspace_best"]),
        "full_space_provenance": (
            "EXISTING_GAME_ENGINE_SYNTHETIC_ONLY"
            if projected["comparison_fullspace_best"] else "NOT_RUN"
        ),
        "comparison_fullspace_best": projected["comparison_fullspace_best"],
        "ranked_front": ranked_front,
        "ranked_back": ranked_back,
        "candidates_1_to_5": ranked_front[:5],
        "primary_d2": ranked_front[:2],
        "ticket": {"front": front, "back": back},
        "prospective_calibration": "NOT_RUN",
        "status": "UNREGISTERED_SYNTHETIC_RESEARCH_ONLY",
        "evidence_class": "SHADOW",
        "physical_forecast_supported": False,
        "formal_a_eligible": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
    }


def audit_research_candidate(snapshot, geometry, candidate):
    if (not isinstance(candidate, dict)
            or candidate != build_research_candidate(snapshot, geometry)):
        raise core.GateError("EXPERIMENTAL_MODEL_RECOMPUTATION_MISMATCH")
    return True


def _in_memory_only(conn):
    if not isinstance(conn, sqlite3.Connection):
        raise ValueError("SQLITE_CONNECTION_REQUIRED")
    database_files = conn.execute("PRAGMA database_list").fetchall()
    if (len(database_files) != 1 or database_files[0][1] != "main"
            or database_files[0][2] != ""):
        raise core.GateError("EXPERIMENTAL_LEDGER_MUST_BE_IN_MEMORY_ONLY")


def _init_synthetic_receipts(conn):
    _in_memory_only(conn)
    conn.execute("PRAGMA recursive_triggers = ON")
    # sqlite3.executescript() commits implicitly; individual CREATE statements
    # preserve the caller-owned freeze transaction even on failures.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_experimental_forecasts (
            run_id TEXT NOT NULL,
            lottery TEXT NOT NULL,
            target_issue TEXT NOT NULL,
            snapshot_sha256 TEXT NOT NULL,
            geometry_projection_sha256 TEXT NOT NULL,
            candidate_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL,
            trust_class TEXT NOT NULL CHECK(
                trust_class='SYNTHETIC_LOCAL_NO_EXTERNAL_SEAL'),
            PRIMARY KEY(run_id,lottery)
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS block_synthetic_fusion_update
        BEFORE UPDATE ON synthetic_experimental_forecasts
        BEGIN SELECT RAISE(ABORT, 'immutable synthetic fusion record'); END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS block_synthetic_fusion_delete
        BEFORE DELETE ON synthetic_experimental_forecasts
        BEGIN SELECT RAISE(ABORT, 'immutable synthetic fusion record'); END
    """)


def freeze_research_candidate(conn, run_id, snapshot, geometry, candidate):
    """Create an immutable SHA256 receipt only in an in-memory SQLite DB."""
    if not isinstance(run_id, str) or not run_id.startswith("SYNTHETIC-"):
        raise core.GateError("EXPERIMENTAL_RUN_ID_MUST_BE_SYNTHETIC")
    audit_research_candidate(snapshot, geometry, candidate)
    _init_synthetic_receipts(conn)
    payload = core.canon(candidate)
    candidate_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    row = (run_id, snapshot["lottery"], str(snapshot["target_issue"]),
           core.digest(snapshot), candidate["geometry_projection_sha256"],
           candidate_sha, payload, "SYNTHETIC_LOCAL_NO_EXTERNAL_SEAL")
    existing = conn.execute(
        "SELECT run_id,lottery,target_issue,snapshot_sha256,geometry_projection_sha256,"
        "candidate_sha256,payload,trust_class FROM synthetic_experimental_forecasts "
        "WHERE run_id=? AND lottery=?",
        (run_id, snapshot["lottery"]),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO synthetic_experimental_forecasts VALUES(?,?,?,?,?,?,?,?)",
            row,
        )
    elif existing != row:
        raise core.GateError("CONFLICTING_EXPERIMENTAL_CANDIDATE_RETRY")
    return candidate_sha


def score_frozen_research_candidate(
    conn, run_id, snapshot, geometry, synthetic_outcome
):
    """Read, rehash, recompute and score the exact frozen experimental bytes."""
    _in_memory_only(conn)
    _synthetic_guard(snapshot)
    if not isinstance(synthetic_outcome, dict):
        raise core.GateError("SYNTHETIC_OUTCOME_REQUIRED")
    if (synthetic_outcome.get("lottery") != snapshot["lottery"]
            or str(synthetic_outcome.get("issue")) != str(snapshot["target_issue"])):
        raise core.GateError("SYNTHETIC_OUTCOME_TARGET_MISMATCH")
    row = conn.execute(
        "SELECT target_issue,snapshot_sha256,geometry_projection_sha256,"
        "candidate_sha256,payload,trust_class FROM synthetic_experimental_forecasts "
        "WHERE run_id=? AND lottery=?",
        (run_id, snapshot["lottery"]),
    ).fetchone()
    if row is None:
        raise core.GateError("EXPERIMENTAL_CANDIDATE_NOT_FROZEN")
    target, snapsha, geosha, savedsha, payload, trust = row
    expected = build_research_candidate(snapshot, geometry)
    if (target != str(snapshot["target_issue"]) or snapsha != core.digest(snapshot)
            or geosha != expected["geometry_projection_sha256"]
            or trust != "SYNTHETIC_LOCAL_NO_EXTERNAL_SEAL"
            or hashlib.sha256(payload.encode("utf-8")).hexdigest() != savedsha):
        raise core.GateError("EXPERIMENTAL_FROZEN_RECEIPT_MISMATCH")
    candidate = json.loads(payload)
    audit_research_candidate(snapshot, geometry, candidate)
    scoring = core.score(candidate, synthetic_outcome)
    return {
        "status": "SYNTHETIC_FROZEN_RESEARCH_SCORE_ONLY",
        "frozen_sha256": savedsha,
        "score": scoring,
        "official_draw_admitted": False,
        "real_predictive_edge_claimed": False,
    }
