"""Single-entrypoint, synthetic-only V4.7 research stack.

Integrates existing registered V4.7 selectors and M1/M2 audit, both actual
source-app geometry feature engines in isolated subprocesses, a deterministic
fair-draw Monte Carlo null benchmark and an UNCALIBRATED 2-ball chamber.
Never mutates frozen forecasts, registers an extra model, purchases tickets,
claims empirical calibration, or produces official predictions.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path

from . import core
from .physics_audit import Ball, audit_model_contracts, d2_probability
from .physics_sim import Chamber, simulate_chamber
from .synthetic_pipeline import run_synthetic_walk_forward

ROOT = Path(__file__).resolve().parents[2]
GAME_APP = {"SSQ": ROOT / "SSQ" / "SSQ", "DLT": ROOT / "DLT" / "src"}


def _int(value: object, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("INVALID_" + label)
    return value


def synthetic_fixture(game: str, *, seed: int) -> dict:
    if game not in core.RULES:
        raise ValueError("UNKNOWN_LOTTERY")
    _int(seed, 0, 2**32 - 1, "SEED")
    r = core.RULES[game]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    # 120 draws required by each registered model; no real-world draw records.
    for idx in range(120):
        rng = random.Random(seed * 1009 + idx * 101 + (0 if game == "SSQ" else 1))
        stamp = start + timedelta(days=idx)
        rows.append({
            "issue": (f"2026{idx + 1:03d}" if game == "SSQ"
                      else f"26{idx + 1:03d}"),
            "front": sorted(rng.sample(range(1, r["pool"] + 1), r["front"])),
            "back": sorted(rng.sample(range(1, r["back_pool"] + 1), r["back"])),
            "drawn_at": stamp.isoformat(),
            "published_at": (stamp + timedelta(hours=1)).isoformat(),
            "draw_date": stamp.date().isoformat(),
        })
    snapshot = {
        "lottery": game,
        "as_of": "2026-10-20T00:00:00+00:00",
        "sales_cutoff": "2026-10-23T12:00:00+08:00",
        "target_draw_at": "2026-10-23T21:00:00+08:00",
        "target_issue": "2026999" if game == "SSQ" else "26999",
        "draws": rows,
        "provenance": {"status": "SYNTHETIC_FIXTURE_NOT_OFFICIAL"},
    }
    core.validate_study_snapshot(snapshot)
    return snapshot


def simulate_fair_d2(*, pool: int, picks: int, trials: int, seed: int) -> dict:
    """Sample legal without-replacement draws; calibrate only the FAIR NULL."""
    _int(trials, 1, 100000, "TRIALS")
    _int(seed, 0, 2**32 - 1, "SEED")
    fair = d2_probability(pool, picks)
    p = float(fair)
    rng = random.Random(seed)
    population = range(1, pool + 1)
    hits = 0
    for _ in range(trials):
        draw = rng.sample(population, picks)
        hits += int(1 in draw and 2 in draw)
    observed = hits / trials
    brier = (hits * (1 - p) ** 2 + (trials - hits) * p * p) / trials
    return {
        "status": "SYNTHETIC_NULL_CALIBRATION_ONLY",
        "sampling": "uniform_without_replacement",
        "trials": trials,
        "fixed_pair": [1, 2],
        "fair_rate": p,
        "observed_hits": hits,
        "observed_rate": observed,
        "theoretical_standard_error": sqrt(p * (1 - p) / trials),
        "brier_empirical": brier,
        "authentic_forecasts_or_outcomes": False,
        "proof_of_predictive_advantage": False,
    }


def _geometry_subprocess(snapshot: dict, game: str, *, complete_space: bool = False) -> dict:
    """Use actual glp.engine per game without global sys.path cross-talk."""
    path = GAME_APP[game]
    if not path.is_dir():
        raise ValueError("MISSING_GAME_APP:" + game)
    env = os.environ.copy()
    env["GLP_DISABLE_BACKGROUND"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(path), str(ROOT)))
    args = [sys.executable, "-m", "research.harness_v46.geometry_adapter", "--game", game]
    if complete_space:
        args.append("--complete-space")
    try:
        child = subprocess.run(
            args,
            cwd=str(ROOT),
            env=env,
            input=json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("GEOMETRY_SUBPROCESS_TIMEOUT:" + game) from exc
    if child.returncode != 0:
        raise ValueError("GEOMETRY_SUBPROCESS_BLOCKED:" + game + ":" + child.stderr[-350:])
    if len(child.stdout) > 65536:
        raise ValueError("GEOMETRY_RESPONSE_TOO_LARGE")
    report = json.loads(child.stdout)
    if (report.get("source_engine") != game
            or report.get("status") != "RESEARCH_FEATURES_NOT_PHYSICS"
            or report.get("formal_A") != 0
            or report.get("physical_forecast_supported") is not False):
        raise ValueError("GEOMETRY_RESULT_CONTRACT_BREACH:" + game)
    return report


def run_synthetic_stack(*, seed: int = 2026, trials: int = 3000, steps: int = 12, full_combinations: bool = False) -> dict:
    """Reproducible integration smoke, deliberately NOT a model promotion."""
    _int(seed, 0, 2**32 - 1, "SEED")
    _int(trials, 1, 100000, "TRIALS")
    _int(steps, 1, 10000, "STEPS")
    if type(full_combinations) is not bool:
        raise ValueError("FULL_COMBINATIONS_MUST_BE_BOOLEAN")
    games = {}
    for game in ("SSQ", "DLT"):
        snapshot = synthetic_fixture(game, seed=seed)
        audit = audit_model_contracts(snapshot)
        if audit["model_ids"] != list(core.MODELS) or audit["edge"] != "NO_EDGE":
            raise ValueError("REGISTERED_MODELS_CHANGED:" + game)
        r = core.RULES[game]
        geometry = _geometry_subprocess(snapshot, game, complete_space=full_combinations)
        walk_forward = run_synthetic_walk_forward(game, seed=seed, periods=2)
        random_reference = simulate_fair_d2(
            pool=r["pool"], picks=r["front"], trials=trials,
            seed=(seed + (0 if game == "SSQ" else 104729)) % (2**32),
        )
        games[game] = {
            "m1_math": {
                "fair_d2": audit["fair_d2"],
                "fair_d2_fraction": audit["fair_d2_fraction"],
                "model_ids": audit["model_ids"],
                "verified_deterministic_models": audit["verified_deterministic_models"],
            },
            "m2_adversarial": {
                "independent_pairwise_check": audit["independent_pairwise_check"],
                "null_history_invariance": audit["null_history_invariance"],
            },
            "m3_probability": random_reference,
            "geometry": geometry,
            "walk_forward": walk_forward,
            "provenance": "SYNTHETIC_FIXTURE_NOT_OFFICIAL",
        }
    chamber = Chamber(
        lengths=(3.0, 3.0, 3.0),
        gravity=(0.0, 0.0, -9.81),
        air_velocity=(0.0, 0.0, 0.2),
        drag_rate=0.1,
        shake_acceleration=2.0,
        shake_frequency_hz=2.0,
        restitution=0.75,
    )
    left = Ball(1.0, 0.12, (0.65, 1.0, 1.5), (0.85, 0.0, 0.0))
    right = Ball(1.0, 0.12, (1.75, 1.0, 1.5), (-0.85, 0.0, 0.0))
    physical = simulate_chamber(chamber, [left, right], steps=steps, dt=0.025)
    return {
        "schema": "V47-UNIFIED-SYNTHETIC-RESEARCH-v1",
        "status": "SYNTHETIC_RESEARCH_ONLY",
        "games": games,
        "physics": physical,
        "official_source_authenticated": False,
        "independent_predraw_time_seal": False,
        "prospective_calibration_valid": False,
        "physical_forecast_supported": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
        "limitations": [
            "No official draw or target authenticated by this research command.",
            "M3 simulations check a theoretical fair null, not actual prediction calibration.",
            "Local freeze and walk-forward score use invented outcomes and in-memory SQLite only; never formal A.",
            "Toy physical box is uncalibrated and lacks full machinery, airflow CFD, ball spin and drawing mechanism.",
            "No owner Windows host, reboot recovery, pre-draw freeze or live model integration is certified.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true",
                        help="required opt-in: use invented history only")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--full-combinations", action="store_true",
                        help="score entire SSQ and DLT legal combination space, research only")
    args = parser.parse_args(argv)
    if not args.synthetic:
        print("BLOCKED: --synthetic required; no live forecasting", file=sys.stderr)
        return 2
    try:
        report = run_synthetic_stack(
            seed=args.seed, trials=args.trials, steps=args.steps,
            full_combinations=args.full_combinations)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("UNIFIED_SYNTHETIC_STACK_BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
