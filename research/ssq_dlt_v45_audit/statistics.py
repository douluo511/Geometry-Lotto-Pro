"""V4.5 research scores and fixed-design statistics, never formal admission.

Pair probabilities are P({a,b} is a subset of the M drawn front numbers),
ordered by itertools.combinations(range(1, N + 1), 2). They are not a
categorical distribution and must sum to C(M,2), not one. The marginal
checks below are necessary; they do not certify global realizability.

The paired test conditions on discordance and assumes independent pairs
with exchangeable signs under the null. The interval is a conservative,
fixed-n Hoeffding interval for independent differences in [-1,1]. Neither
method licenses optional stopping, data-dependent selection or dependence
between periods. The caller must establish these design assumptions.
"""
from __future__ import annotations

from hashlib import sha256
from itertools import combinations
import json
from math import ceil, comb, fsum, isfinite, log, sqrt


class StatisticsBlocked(ValueError):
    """A malformed or incomplete statistical contract fails closed."""


def _numbers(value: object, count: int | None = None, upper: int | None = None) -> tuple:
    if (type(value) not in (list, tuple) or not value
            or (count is not None and len(value) != count)
            or any(type(x) is not int or x < 1 or (upper is not None and x > upper)
                   for x in value) or len(set(value)) != len(value)):
        raise StatisticsBlocked("INVALID_DISTINCT_FRONT_NUMBERS")
    return tuple(value)


def _probability(value: object) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise StatisticsBlocked("INVALID_PROBABILITY")
    return float(value)


def _alpha(value: object) -> float:
    result = _probability(value)
    if result in (0, 1):
        raise StatisticsBlocked("ALPHA_MUST_BE_STRICTLY_BETWEEN_ZERO_AND_ONE")
    return result


def score_d2(candidate_pair: object, draw_front: object) -> int:
    """Return one only when BOTH distinct proposed numbers occur in front."""
    pair = _numbers(candidate_pair, 2)
    drawn = _numbers(draw_front)
    if len(drawn) < 2:
        raise StatisticsBlocked("FRONT_REQUIRES_AT_LEAST_TWO_NUMBERS")
    return int(set(pair).issubset(drawn))


def pair_brier(probabilities: object, draw_front: object, N: int, M: int) -> float:
    """Mean binary Brier over all C(N,2) pairs; lower is better.

    This is not Brier on only the selected pair, nor the product of two
    unverified single-ball probabilities. No vector is rescaled or repaired.
    """
    if type(N) is not int or type(M) is not int or not 2 <= M <= N <= 100:
        raise StatisticsBlocked("INVALID_POPULATION")
    drawn = set(_numbers(draw_front, M, N))
    if type(probabilities) not in (list, tuple) or len(probabilities) != comb(N, 2):
        raise StatisticsBlocked("PAIR_VECTOR_LENGTH_MISMATCH")
    probs = [_probability(x) for x in probabilities]
    tolerance = 1e-9
    if abs(fsum(probs) - comb(M, 2)) > tolerance:
        raise StatisticsBlocked("PAIR_INCLUSION_FIXED_SUM_MISMATCH")
    degrees = [0.0] * N
    squared = []
    for (a, b), probability in zip(combinations(range(1, N + 1), 2), probs):
        degrees[a - 1] += probability
        degrees[b - 1] += probability
        actual = int(a in drawn and b in drawn)
        squared.append((probability - actual) ** 2)
    if any(degree > M - 1 + tolerance for degree in degrees):
        raise StatisticsBlocked("PAIR_MARGINAL_DEGREE_IMPOSSIBLE")
    return fsum(squared) / len(probs)


def paired_summary(hit_pairs: object, *, alpha: float = 0.05) -> dict:
    """One (model_hit, null_hit) per complete, same-game/same-issue pair.

    Caller retains the immutable issue rectangle; this low-level helper
    cannot establish identity, missingness, timestamps or independence.
    Exact tail numerator / 2**discordant is retained even if float underflows.
    """
    alpha = _alpha(alpha)
    if type(hit_pairs) not in (list, tuple) or len(hit_pairs) > 10000:
        raise StatisticsBlocked("INVALID_PAIRED_OBSERVATIONS")
    for pair in hit_pairs:
        if (type(pair) not in (list, tuple) or len(pair) != 2
                or any(type(x) is not int or x not in (0, 1) for x in pair)):
            raise StatisticsBlocked("PAIRED_OUTCOMES_MUST_BE_BINARY_INTEGERS")
    n = len(hit_pairs)
    wins = sum(a == 1 and b == 0 for a, b in hit_pairs)
    losses = sum(a == 0 and b == 1 for a, b in hit_pairs)
    discordant = wins + losses
    numerator = sum(comb(discordant, k) for k in range(wins, discordant + 1))
    probability = numerator / (2 ** discordant)
    delta = (wins - losses) / n if n else None
    radius = sqrt(2 * log(2 / alpha) / n) if n else None
    return {
        "n": n, "wins": wins, "losses": losses, "ties": n - discordant,
        "model_hits": sum(a for a, _ in hit_pairs),
        "null_hits": sum(b for _, b in hit_pairs),
        "paired_delta": delta,
        "confidence_interval": ([max(-1.0, delta - radius), min(1.0, delta + radius)]
                                if n else None),
        "confidence_level": 1 - alpha,
        "interval_method": "CONSERVATIVE_FIXED_N_HOEFFDING_INDEPENDENT_PAIRS",
        "p_one_sided": probability,
        "p_exact_numerator": str(numerator),
        "p_exact_denominator_power_two": discordant,
        "p_float_underflow": probability == 0,
        "test_method": "EXACT_CONDITIONAL_DISCORDANT_BINOMIAL_GREATER",
        "assumptions": ["independent issue pairs", "null exchangeable discordant signs",
                        "fixed sample size; no optional stopping or selected comparisons"],
        "status": "RESEARCH_ONLY" if n else "BLOCKED_NO_PAIRS",
        "formal_a_samples": 0, "decision": "NO_EDGE",
    }


def _family(expected_family: object) -> tuple:
    if (type(expected_family) is not tuple or len(expected_family) != 12
            or any(type(item) is not str or not item for item in expected_family)
            or len(set(expected_family)) != 12):
        raise StatisticsBlocked("EXPLICIT_UNIQUE_FIXED_TWELVE_IDS_REQUIRED")
    return expected_family


def holm(pvalues: object, expected_family: tuple, *, alpha: float = 0.05) -> dict:
    """Holm step-down on exactly the explicitly supplied twelve hypotheses.

    Missing entries, including None, block all decisions. IDs alone never
    establish the semantics or authenticity of the original formal family.
    """
    family = _family(expected_family)
    alpha = _alpha(alpha)
    if type(pvalues) is not dict:
        raise StatisticsBlocked("PVALUES_MUST_BE_A_DICTIONARY")
    missing = sorted(set(family) - set(pvalues))
    extra = sorted(set(pvalues) - set(family), key=str)
    unresolved = sorted(key for key in family if key in pvalues and pvalues[key] is None)
    if missing or extra or unresolved:
        return {"status": "BLOCKED_INCOMPLETE_FIXED_FAMILY", "family_size": 12,
                "missing": missing, "extra": extra, "unresolved": unresolved,
                "adjusted_pvalues": None, "rejected": [],
                "formal_family_semantics": "NOT_ESTABLISHED_BY_IDS",
                "formal_a_samples": 0, "decision": "NO_EDGE"}
    validated = {key: _probability(value) for key, value in pvalues.items()}
    ordered = sorted(family, key=lambda key: (validated[key], key))
    adjusted = {}
    previous = 0.0
    for index, key in enumerate(ordered):
        previous = min(1.0, max(previous, (12 - index) * validated[key]))
        adjusted[key] = previous
    return {"status": "RESEARCH_ONLY", "family_size": 12, "alpha": alpha,
            "adjusted_pvalues": adjusted,
            "rejected": [key for key in ordered if adjusted[key] <= alpha],
            "formal_family_semantics": "NOT_ESTABLISHED_BY_IDS",
            "formal_a_samples": 0, "decision": "NO_EDGE"}


def precision_sample_size(max_half_width: float, *, alpha: float = 0.05) -> int:
    """Conservative fixed n for a [-1,1] paired-difference Hoeffding radius.

    A precision bound is not a power calculation or a claim of expected edge.
    """
    alpha = _alpha(alpha)
    if (type(max_half_width) not in (int, float) or not isfinite(max_half_width)
            or not 0 < max_half_width <= 1):
        raise StatisticsBlocked("INVALID_PRECISION")
    return ceil(2 * log(2 / alpha) / max_half_width ** 2)


def validate_fixed_plan(plan: object, completed_issue_ids: object = ()) -> dict:
    """Validate an explicit research-only fixed-n stopping contract.

    This hashes local content only; it cannot prove pre-registration or
    authenticate the original formal twelve definitions. Invalid/missing/
    out-of-order issues cannot be replaced by favorable observations.
    """
    fields = {"scope", "family_ids", "target_n", "expected_issue_ids", "alpha",
              "minimum_effect", "stop_rule", "replication_required"}
    if type(plan) is not dict or set(plan) != fields:
        raise StatisticsBlocked("EXACT_FIXED_PLAN_FIELDS_REQUIRED")
    family = _family(tuple(plan["family_ids"]) if type(plan["family_ids"]) is list
                     else plan["family_ids"])
    n = plan["target_n"]
    issues = plan["expected_issue_ids"]
    if (plan["scope"] != "RESEARCH_ONLY" or type(n) is not int or not 1 <= n <= 10000
            or type(issues) not in (list, tuple) or len(issues) != n
            or any(type(i) is not str or not i for i in issues)
            or len(set(issues)) != n
            or plan["stop_rule"] != "FIXED_N_NO_EARLY_SUCCESS_NO_EXTENSION"
            or plan["replication_required"] is not True):
        raise StatisticsBlocked("INVALID_FIXED_SAMPLE_OR_STOPPING_CONTRACT")
    alpha = _alpha(plan["alpha"])
    effect = plan["minimum_effect"]
    if type(effect) not in (int, float) or not isfinite(effect) or not 0 < effect <= 1:
        raise StatisticsBlocked("POSITIVE_MINIMUM_EFFECT_REQUIRED")
    if (type(completed_issue_ids) not in (list, tuple)
            or tuple(completed_issue_ids) != tuple(issues[:len(completed_issue_ids)])):
        raise StatisticsBlocked("COMPLETED_ISSUES_MUST_BE_EXACT_PLANNED_PREFIX")
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"status": "RESEARCH_FIXED_N_COMPLETE" if len(completed_issue_ids) == n
            else "COLLECTING_NO_EARLY_DECISION", "target_n": n,
            "completed_n": len(completed_issue_ids), "family_size": len(family),
            "plan_sha256": sha256(canonical).hexdigest(), "alpha": alpha,
            "minimum_effect": float(effect), "stop_rule": plan["stop_rule"],
            "trusted_preregistration": "NOT_VERIFIED",
            "original_formal_twelve": "NOT_VERIFIED", "independent_replication": "REQUIRED",
            "formal_a_samples": 0, "decision": "NO_EDGE"}
