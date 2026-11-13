"""Subprocess-only adapter to actual SSQ / DLT `glp.engine` feature code.

Run with a GAME-SPECIFIC PYTHONPATH, not mixed in one interpreter; both apps
define the same `glp` package. Input is validated synthetic historical
fixtures only. Output is not an official forecast or physics observation.
"""
from __future__ import annotations

import argparse
import json
import sys
from math import comb

from . import core


def extract_geometry(snapshot: dict, game: str, *, complete_space: bool = False) -> dict:
    if (game not in ("SSQ", "DLT") or not isinstance(snapshot, dict)
            or snapshot.get("lottery") != game
            or not isinstance(snapshot.get("provenance"), dict)
            or snapshot["provenance"].get("status") != "SYNTHETIC_FIXTURE_NOT_OFFICIAL"):
        raise ValueError("SYNTHETIC_GAME_BOUNDARY_REQUIRED")
    core.validate_study_snapshot(snapshot)

    # Each game must run in its own Python process and package path to avoid
    # importing the wrong game's glp.engine or glp.domain modules.
    from glp.domain import Draw
    from glp import engine

    if len(snapshot["draws"]) > 1000:
        raise ValueError("GEOMETRY_FIXTURE_TOO_LARGE")
    draws = [Draw.from_dict(row) for row in snapshot["draws"]]
    features = {}
    geometry_first_pairs = {}
    for area in ("front", "back"):
        data = engine.feature_vectors(draws, area)
        rankings = engine.individual_model_rankings(draws, area)
        required = {"geometry_state", "geometry_transition"}
        if not required <= set(data) or not required <= set(rankings):
            raise ValueError("GEOMETRY_SOURCE_ENGINE_CONTRACT_MISSING")
        if any(not values for values in data.values()):
            raise ValueError("GEOMETRY_FEATURE_EMPTY")
        features[area] = sorted(data.keys())
        geometry_first_pairs[area] = {
            label: list(rankings[label][:2]) for label in sorted(required)
        }
    # Full legal-combination enumeration is intentionally opt-in because it
    # is computationally costly and not supported by evidence of prediction.
    complete = {}
    if complete_space:
        for area in ("front", "back"):
            pick = core.RULES[game]["front" if area == "front" else "back"]
            pool = core.RULES[game]["pool" if area == "front" else "back_pool"]
            total = comb(pool, pick)
            result = engine.score_complete_space(draws, area)
            if game == "SSQ":
                if result["count"] != total or not result["top"]:
                    raise ValueError("SSQ_COMBINATION_SEARCH_INCOMPLETE")
                best = list(result["top"][0][0])
                observed_count = result["count"]
            else:
                best = list(result.numbers)
                # The DLT app scores full combinations but returns only the
                # best combo; its iterator does not expose an actual counter.
                observed_count = None
            if (len(best) != pick or len(set(best)) != pick
                    or any(type(n) is not int or n < 1 or n > pool for n in best)):
                raise ValueError("INVALID_COMPLETE_COMBINATION_RESULT")
            complete[area] = {
                "status": "SOURCE_ENGINE_EXECUTED_RESEARCH_ONLY",
                "theoretical_legal_combinations": total,
                "engine_reported_count": observed_count,
                "best_synthetic_scored_combination": best,
            }

    return {
        "source_engine": game,
        "status": "RESEARCH_FEATURES_NOT_PHYSICS",
        "complete_space": complete,
        "features": features,
        "illustrative_top_two_from_geometry_scores": geometry_first_pairs,
        "real_machine_geometry_observed": False,
        "validated_official_draws": False,
        "physical_forecast_supported": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=("SSQ", "DLT"), required=True)
    parser.add_argument("--complete-space", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("SYNTHETIC_FIXTURE_TOO_LARGE")
        snapshot = json.loads(raw)
        print(json.dumps(extract_geometry(snapshot, args.game, complete_space=args.complete_space), sort_keys=True))
    except (ValueError, TypeError, KeyError, ImportError) as exc:
        print("GEOMETRY_ADAPTER_BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
