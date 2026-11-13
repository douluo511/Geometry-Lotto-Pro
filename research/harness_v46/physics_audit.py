"""Read-only V4.7 formula audit and elementary rigid-sphere collision diagnostic.

This module is deliberately NOT a lottery prediction model, random draw model,
complete lottery-machine simulator, source verifier, or formal-A promoter.
It never changes frozen models, seeds, predictions, or ledgers.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations
from math import comb, isfinite, sqrt

from . import core

AUDIT_VERSION = "V47-M1M2M3-PHYSICS-RESEARCH-DIAGNOSTIC-v1"


class AuditBlocked(ValueError):
    """Invalid evidence or a failed independent model-contract check."""


def d2_probability(pool: int, picks: int) -> Fraction:
    """Exact fair-without-replacement chance for one fixed pair in the draw.

    Count all allowed k-subsets containing the 2 fixed numbers, then divide
    by all allowed k-subsets. The result is not fitted from historical data.
    """
    if (type(pool) is not int or type(picks) is not int
            or pool < 2 or not 2 <= picks <= pool):
        raise ValueError("INVALID_D2_RULES")
    return Fraction(comb(pool - 2, picks - 2), comb(pool, picks))


def _independent_pairwise_d2(draws: list[dict], pool: int, picks: int) -> list[int]:
    """Integer-only oracle independent of core._pair_scores floating arithmetic.

    For n=120, tau=200, multiply the existing candidate score by
    n*k*(n+tau): (ca+cb)*k*(n+tau) + cab*n*k - ca*cb*(k-1).
    The positive scale preserves ranking and the lexicographic tie-break.
    This audits the REGISTERED algorithm; it does not replace its formula.
    """
    tail = draws[-120:]
    if len(tail) != 120:
        raise AuditBlocked("PAIRWISE_WARMUP_REQUIRED")
    n, tau, k = len(tail), 200, picks
    counts = Counter(num for row in tail for num in row["front"])
    pair_counts = Counter(pair for row in tail
                          for pair in combinations(row["front"], 2))
    best_pair, best_score = None, None
    for a, b in combinations(range(1, pool + 1), 2):
        score = ((counts[a] + counts[b]) * k * (n + tau)
                 + pair_counts[(a, b)] * n * k
                 - counts[a] * counts[b] * (k - 1))
        if best_score is None or score > best_score:
            best_pair, best_score = (a, b), score
    return list(best_pair)


def audit_model_contracts(snapshot: dict) -> dict:
    """M1 structured checks, M2 independent attack, M3 fair-rate calibration.

    Strictly accepts synthetic snapshots. A success is a code-contract audit,
    not evidence of a forward predictive edge. No candidate is promoted.
    """
    if (not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("provenance"), dict)
            or snapshot["provenance"].get("status") != "SYNTHETIC_FIXTURE_NOT_OFFICIAL"):
        raise AuditBlocked("SYNTHETIC_ONLY_NO_OFFICIAL_AUTHENTICATION")
    core.validate_study_snapshot(snapshot)
    game = snapshot["lottery"]
    rules = core.RULES[game]
    fair = d2_probability(rules["pool"], rules["front"])
    if abs(float(fair) - rules["d2"]) > 1e-15:
        raise AuditBlocked("FAIR_D2_FORMULA_DISAGREEMENT")

    predictions = {}
    for model in core.MODELS:
        forecast = core.forecast(snapshot, model)
        if forecast != core.forecast(snapshot, model):
            raise AuditBlocked("MODEL_NONDETERMINISTIC:" + model)
        core.validate_forecast(forecast, snapshot)
        if (forecast["model"] != model or forecast["evidence_class"] != "SHADOW"
                or forecast["formal_a_eligible"] is not False
                or not set(forecast["primary_d2"]).issubset(forecast["ticket"]["front"])):
            raise AuditBlocked("MODEL_CONTRACT_VIOLATION:" + model)
        predictions[model] = forecast

    pair = _independent_pairwise_d2(
        snapshot["draws"], rules["pool"], rules["front"])
    if predictions["pairwise_d2"]["primary_d2"] != pair:
        raise AuditBlocked("PAIRWISE_INDEPENDENT_DISAGREEMENT")

    # Same target, different past draw numbers. The preregistered fixed NULL
    # is independent of historical selection but binds game and target issue.
    changed = deepcopy(snapshot)
    changed["draws"][0]["front"], changed["draws"][1]["front"] = (
        changed["draws"][1]["front"], changed["draws"][0]["front"])
    changed_null = core.forecast(changed, "random_null")
    if (changed_null["primary_d2"] != predictions["random_null"]["primary_d2"]
            or changed_null["ticket"] != predictions["random_null"]["ticket"]):
        raise AuditBlocked("RANDOM_NULL_HISTORY_LEAKAGE")

    return {
        "audit_version": AUDIT_VERSION,
        "status": "SYNTHETIC_SHADOW_AUDIT_ONLY",
        "lottery": game,
        "model_ids": list(core.MODELS),
        "verified_deterministic_models": len(predictions),
        "fair_d2": float(fair),
        "fair_d2_fraction": f"{fair.numerator}/{fair.denominator}",
        "independent_pairwise_check": "PASS",
        "null_history_invariance": "PASS",
        "probability_calibration": "NOT_RUN_NO_AUTHENTICATED_PROSPECTIVE_DRAWS",
        "physical_forecast_supported": False,
        "physics_limitation": "NO_MEASURED_MACHINE_OR_BALL_INITIAL_CONDITIONS",
        "formal_A": 0,
        "edge": "NO_EDGE",
    }


def _number(value: object) -> bool:
    return (type(value) in (int, float) and isfinite(value))


def _vector(value: object) -> tuple[float, float, float]:
    if (not isinstance(value, (tuple, list)) or len(value) != 3
            or not all(_number(x) for x in value)):
        raise ValueError("INVALID_3D_VECTOR")
    return tuple(float(x) for x in value)


@dataclass(frozen=True)
class Ball:
    """An ideal rigid sphere: mass kg, radius m, position m, velocity m/s."""

    mass: float
    radius: float
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]

    def __post_init__(self):
        if (not _number(self.mass) or self.mass <= 0
                or not _number(self.radius) or self.radius <= 0):
            raise ValueError("INVALID_BALL_MASS_OR_RADIUS")
        object.__setattr__(self, "mass", float(self.mass))
        object.__setattr__(self, "radius", float(self.radius))
        object.__setattr__(self, "position", _vector(self.position))
        object.__setattr__(self, "velocity", _vector(self.velocity))


def linear_momentum(ball: Ball) -> tuple[float, float, float]:
    return tuple(ball.mass * v for v in ball.velocity)


def kinetic_energy(ball: Ball) -> float:
    return 0.5 * ball.mass * sum(v * v for v in ball.velocity)


def collide(a: Ball, b: Ball, restitution: float = 1.0) -> tuple[Ball, Ball]:
    """One frictionless 3D contact impulse, without advancing time or positions.

    This diagnostic resolves an approaching sphere-sphere contact. It excludes
    air motion, spinner geometry, spin, wall forces, contact duration, repeated
    collisions and measured initial conditions. It is not a drawing simulator.
    """
    if not isinstance(a, Ball) or not isinstance(b, Ball):
        raise ValueError("BALL_OBJECTS_REQUIRED")
    if not _number(restitution) or not 0 <= restitution <= 1:
        raise ValueError("INVALID_RESTITUTION")
    delta = tuple(y - x for x, y in zip(a.position, b.position))
    distance = sqrt(sum(x * x for x in delta))
    if distance == 0:
        raise ValueError("AMBIGUOUS_CONTACT_NORMAL")
    if distance > a.radius + b.radius + 1e-12:
        return a, b
    normal = tuple(x / distance for x in delta)
    relative = sum((vb - va) * n for va, vb, n
                   in zip(a.velocity, b.velocity, normal))
    if relative >= 0:
        return a, b
    impulse = -(1.0 + restitution) * relative / (1.0 / a.mass + 1.0 / b.mass)
    va = tuple(v - impulse * n / a.mass for v, n in zip(a.velocity, normal))
    vb = tuple(v + impulse * n / b.mass for v, n in zip(b.velocity, normal))
    return replace(a, velocity=va), replace(b, velocity=vb)


if __name__ == "__main__":
    import json
    print(json.dumps({
        "audit_version": AUDIT_VERSION,
        "SSQ_fair_D2": str(d2_probability(33, 6)),
        "DLT_fair_D2": str(d2_probability(35, 5)),
        "rigid_sphere_kernel": "SYNTHETIC_CONTACT_ONLY",
        "full_lottery_machine_simulator": False,
        "physical_forecast_supported": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
    }, sort_keys=True))
