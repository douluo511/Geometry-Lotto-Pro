"""Subprocess-only adapter to actual SSQ / DLT `glp.engine` feature code.

Run with a GAME-SPECIFIC PYTHONPATH, not mixed in one interpreter; both apps
define the same `glp` package. Input is validated synthetic historical
fixtures only. Output is not an official forecast or physics observation.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def extract_geometry(snapshot: dict, game: str) -> dict:
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
    return {
        "source_engine": game,
        "status": "RESEARCH_FEATURES_NOT_PHYSICS",
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
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("SYNTHETIC_FIXTURE_TOO_LARGE")
        snapshot = json.loads(raw)
        print(json.dumps(extract_geometry(snapshot, args.game), sort_keys=True))
    except (ValueError, TypeError, KeyError, ImportError) as exc:
        print("GEOMETRY_ADAPTER_BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
