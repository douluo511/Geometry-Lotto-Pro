"""Mathematical reference distributions; no candidates, dataset or network access.

These are new, explicit research implementations, not recovered definitions of
the historical named models or the formal eight slots. A probability vector is
constructed from an actual distribution over exactly M distinct front balls.
For product weights, P(S)=prod(w[i] for i in S)/e_M(w). Pair inclusion is
w[i]*w[j]*e_(M-2)(w excluding i,j)/e_M(w). Pairwise-D2 instead mixes a uniform
M-subset with previously observed M-subsets using 20 uniform pseudo-observations.
All full-pair probabilities therefore sum to C(M,2), not one.

No model establishes source authority or pre-draw availability. Date and issue
checks are prefix guards only. The caller must supply independent as-of proof.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from itertools import combinations
import json
from math import comb, isfinite
import re

RULES = {"SSQ": (33, 6), "DLT": (35, 5)}
VERSION = "reference-v45-audit-1.0.0"
FIXED_SEED = 20261020
MODEL_PARAMETERS = {
    "Hot60": {"window": 60, "prior_draws": 10},
    "EWMA": {"half_life_draws": 20, "prior_draws": 10},
    "ShrinkMix": {"window": 60, "prior_draws": 10, "uniform_weight": 0.5},
    "Pairwise-D2": {"window": 60, "uniform_prior_draws": 20},
    "Random NULL": {"seed": FIXED_SEED},
}
MODELS = tuple(MODEL_PARAMETERS)


class ModelInputError(ValueError):
    """Malformed or leaking input is never silently truncated."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _elementary(weights: list[float], degree: int) -> float:
    coefficients = [1.0] + [0.0] * degree
    for weight in weights:
        for k in range(degree, 0, -1):
            coefficients[k] += weight * coefficients[k - 1]
    return coefficients[degree]


def weighted_subset_probabilities(weights: list[float], drawn: int) -> tuple[list[float], list[float]]:
    """Exact finite sum identities, evaluated with positive-only float DP.

    A common rescaling of weights cancels. We recompute each leave-two-out
    elementary polynomial rather than subtracting nearly equal coefficients.
    This helper permits small populations for exhaustive independent tests.
    """
    if (type(weights) is not list or len(weights) < 2 or type(drawn) is not int
            or not 2 <= drawn <= len(weights)
            or any(type(w) not in (float, int) or not isfinite(w) or w <= 0
                   for w in weights)):
        raise ModelInputError("INVALID_SUBSET_DISTRIBUTION")
    scale = max(weights)
    scaled = [float(w / scale) for w in weights]
    partition = _elementary(scaled, drawn)
    if not isfinite(partition) or partition <= 0:
        raise ModelInputError("UNREPRESENTABLE_SUBSET_DISTRIBUTION")
    probabilities = []
    singles = [0.0] * len(scaled)
    for i, j in combinations(range(len(scaled)), 2):
        remainder = [w for k, w in enumerate(scaled) if k != i and k != j]
        p = scaled[i] * scaled[j] * _elementary(remainder, drawn - 2) / partition
        if not isfinite(p) or not -1e-12 <= p <= 1 + 1e-12:
            raise ModelInputError("NUMERIC_PROBABILITY_FAILURE")
        p = min(1.0, max(0.0, p))
        probabilities.append(p)
        singles[i] += p / (drawn - 1)
        singles[j] += p / (drawn - 1)
    if abs(sum(probabilities) - comb(drawn, 2)) > 1e-8:
        raise ModelInputError("NUMERIC_PROBABILITY_MASS_FAILURE")
    return singles, probabilities


def _validate_prefix(game: str, issue: str, history: list[dict],
                     target_deadline: str | None) -> list[dict]:
    if type(game) is not str or game not in RULES:
        raise ModelInputError("UNKNOWN_GAME")
    issue_length = 7 if game == "SSQ" else 5
    pattern = re.compile(r"[0-9]{" + str(issue_length) + r"}\Z")
    if type(issue) is not str or not pattern.fullmatch(issue):
        raise ModelInputError("INVALID_TARGET_ISSUE")
    deadline_date = None
    if target_deadline is not None:
        if type(target_deadline) is not str:
            raise ModelInputError("INVALID_TARGET_DEADLINE")
        try:
            deadline = datetime.fromisoformat(target_deadline.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ModelInputError("INVALID_TARGET_DEADLINE") from exc
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ModelInputError("TIMEZONE_REQUIRED")
        deadline_date = deadline.date()
    if type(history) is not list:
        raise ModelInputError("INVALID_HISTORY")
    upper, drawn = RULES[game]
    clean = []
    seen = set()
    for row in history:
        if type(row) is not dict or row.get("game") != game:
            raise ModelInputError("CROSS_GAME_HISTORY")
        row_issue = row.get("issue")
        if (type(row_issue) is not str or not pattern.fullmatch(row_issue)
                or row_issue >= issue or row_issue in seen):
            raise ModelInputError("FUTURE_OR_DUPLICATE_ISSUE")
        seen.add(row_issue)
        raw_date = row.get("date")
        try:
            row_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError) as exc:
            raise ModelInputError("INVALID_HISTORY_DATE") from exc
        if row_date.isoformat() != raw_date:
            raise ModelInputError("INVALID_HISTORY_DATE")
        # A day-only history field cannot prove availability earlier that day.
        if deadline_date is not None and row_date >= deadline_date:
            raise ModelInputError("HISTORY_NOT_BEFORE_TARGET_DATE")
        front = row.get("front")
        if (type(front) is not list or len(front) != drawn
                or any(type(n) is not int or not 1 <= n <= upper for n in front)
                or len(set(front)) != drawn):
            raise ModelInputError("INVALID_FRONT_NUMBERS")
        clean.append({"game": game, "issue": row_issue,
                      "date": raw_date, "front": sorted(front)})
    clean.sort(key=lambda row: row["issue"])
    if any(a["date"] > b["date"] for a, b in zip(clean, clean[1:])):
        raise ModelInputError("NONMONOTONIC_HISTORY_DATES")
    return clean


def reference_distribution(game: str, issue: str, history: list[dict], model: str,
            parameters: dict | None = None, *, target_deadline: str | None = None) -> dict:
    """Calculate a mathematical reference from a supplied prior prefix.

    No future rows are filtered away: their presence raises ModelInputError.
    Parameters are recorded, immutable defaults, not an optimization interface.
    No candidate selection is implemented and no operational registry is used.
    The uniform NULL reference has no stochastic candidate generator; its fixed
    seed is a contract identifier, not a claim that any candidates were drawn.
    """
    if type(model) is not str or model not in MODEL_PARAMETERS:
        raise ModelInputError("UNKNOWN_RESEARCH_MODEL")
    fixed = MODEL_PARAMETERS[model]
    if parameters is not None and (type(parameters) is not dict
                                    or _canonical(parameters) != _canonical(fixed)):
        raise ModelInputError("PARAMETER_CHANGE_REQUIRES_NEW_PREREGISTRATION")
    prefix = _validate_prefix(game, issue, history, target_deadline)
    upper, drawn = RULES[game]
    pairs = list(combinations(range(1, upper + 1), 2))
    uniform_pair = comb(drawn, 2) / comb(upper, 2)
    uniform_single = drawn / upper
    used = prefix[-fixed["window"]:] if "window" in fixed else prefix
    construction = "UNIFORM_FIXED_SIZE_SUBSET"
    if model == "Random NULL":
        singles = [uniform_single] * upper
        probabilities = [uniform_pair] * len(pairs)
    elif model == "Pairwise-D2":
        alpha = fixed["uniform_prior_draws"]
        denominator = alpha + len(used)
        single_counts = [0] * upper
        pair_counts = {pair: 0 for pair in pairs}
        for row in used:
            for n in row["front"]:
                single_counts[n - 1] += 1
            for pair in combinations(row["front"], 2):
                pair_counts[pair] += 1
        singles = [(alpha * uniform_single + c) / denominator for c in single_counts]
        probabilities = [(alpha * uniform_pair + pair_counts[pair]) / denominator
                         for pair in pairs]
        construction = "DIRICHLET_UNIFORM_PLUS_EMPIRICAL_FIXED_SIZE_SUBSETS"
    else:
        counts = [0.0] * upper
        total_weight = 0.0
        for age, row in enumerate(reversed(used)):
            weight = 2 ** (-age / fixed["half_life_draws"]) if model == "EWMA" else 1.0
            total_weight += weight
            for n in row["front"]:
                counts[n - 1] += weight
        prior = fixed["prior_draws"]
        rates = [(prior * uniform_single + c) / (prior + total_weight) for c in counts]
        odds = [r / (1 - r) for r in rates]
        singles, probabilities = weighted_subset_probabilities(odds, drawn)
        construction = "PRODUCT_WEIGHT_FIXED_SIZE_SUBSET_FROM_SINGLE_BALL_ODDS"
        if model == "ShrinkMix":
            uniform_weight = fixed["uniform_weight"]
            singles = [uniform_weight * uniform_single + (1 - uniform_weight) * p
                       for p in singles]
            probabilities = [uniform_weight * uniform_pair + (1 - uniform_weight) * p
                             for p in probabilities]
            construction = "UNIFORM_AND_PRODUCT_WEIGHT_FIXED_SIZE_MIXTURE"
    return {
        "game": game, "issue": issue, "model_id": "reference-v45-audit/" + model,
        "model": model, "version": VERSION, "parameters": dict(fixed),
        "seed": FIXED_SEED, "training_rows": len(prefix), "effective_rows": len(used),
        "prefix_sha256": sha256(_canonical(prefix)).hexdigest(),
        "target_deadline": target_deadline,
        "deadline_scope": "DATE_AND_ISSUE_PREFIX_ONLY" if target_deadline else "ISSUE_ORDER_ONLY",
        "single_probabilities": singles,
        "pair_probabilities": probabilities,
        "pair_order": "LEXICOGRAPHIC_1_BASED_ITERTools_COMBINATIONS",
        "probability_construction": construction,
        "probability_mass_expected": comb(drawn, 2),
        "candidate_generation": "NOT_IMPLEMENTED_REFERENCE_ONLY",
        "scope": "MATHEMATICAL_REFERENCE_ONLY", "asof_verified": False,
        "active_new_primary_challengers": 0,
        "formal_A_samples": 0, "R2": "BLOCKED", "decision": "NO_EDGE",
    }
