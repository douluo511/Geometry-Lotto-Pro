"""Fixed, synthetic-development-only D2 candidates; no formal admission.

Conditional Bernoulli means P(S) is proportional to product(w[i] for i in S)
on sets of exactly k distinct numbers.  The marginal-to-odds mapping below is
a surrogate: conditioning changes its supplied Bernoulli marginals.  It is
not a fitted marginal maximum-entropy model.  Replication z values are ranking
scores, not calibrated z tests, since their estimated baseline shares data.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import math
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

from research.ssq_dlt_v45 import models as oldmodels


MODEL_IDS = ("R46-CBPAIR-SHRINK", "R46-REPLICATED-PAIR")
PARAMETERS = MappingProxyType({
    "base_window": 240,
    "marginal_pseudo_draws": 200,
    "recent_window": 60,
    "pair_prior_pseudo_draws": 200,
    "replication_block_window": 60,
    "replication_variance_floor_addend": 1.0,
    "tie_score_decimals": 12,
    "weight_mapping": "odds_of_uniform_shrunk_marginal_surrogate",
})


def registry() -> dict:
    """Fresh metadata; caller mutations cannot change fixed parameters."""
    return {
        "schema": "ssq-dlt-d2-next-registry-1",
        "scope": "RESEARCH_ONLY",
        "formal_A": 0,
        "parameters": copy.deepcopy(dict(PARAMETERS)),
        "models": {
            MODEL_IDS[0]: {
                "version": "1.0.0",
                "algorithm": "Pair60/CB240 coherent fixed-k mixture",
                "score_formula": "(h_recent60(pair)+200*q_CB240(pair))/(60+200)",
                "tie_rule": "round(score,12), recent60 pair count, base240 marginal sum, ascending pair",
                "tie_rounding": "Python round(float,12); no score rounding before probability output",
            },
            MODEL_IDS[1]: {
                "version": "1.0.0",
                "algorithm": "Maximum of minimum two-block residual ranking scores; top-two-odds fallback if max<=0",
                "score_formula": "min((h_recent60-60*q)/sqrt(60*q*(1-q)+1),(h_previous60-60*q)/sqrt(60*q*(1-q)+1))",
                "block_policy": "Most recent 60 and preceding nonoverlapping 60 within base240",
                "fallback": "If unrounded maximum min-block score <= 0: two largest surrogate odds, ascending-number ties",
                "tie_rule": "round(min_z,12), round(CBPAIR_score,12), ascending pair",
                "tie_rounding": "Python round(float,12); raw maximum is used for fallback",
            },
        },
        "shared_prior": {
            "input_marginal_formula": "p_i=(base240_count_i+200*k/n)/(240+200)",
            "weight_formula": "w_i=p_i/(1-p_i)",
            "distribution": "P(S)=product(w_i for i in S)/e_k(w), |S|=k",
            "joint_formula": "q_ij=w_i*w_j*e_(k-2)(w_without_i_j)/e_k(w)",
            "calibration": "Surrogate odds, not a marginal maximum-likelihood or maximum-entropy fit",
        },
        "marginal_calibration": "surrogate odds; resulting conditional marginals need not equal shrunk inputs",
        "residual_calibration": "descriptive score, not a normal test or independent replication",
        "brier_unit": "One draw; dependent pair indicators are never independent sample units",
    }


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _inputs(weights: list[float], k: int) -> tuple[list[float], int]:
    if (type(weights) is not list or len(weights) < 2
            or type(k) is not int or not 0 <= k <= len(weights)):
        raise ValueError("POSITIVE_WEIGHTS_AND_LEGAL_K_REQUIRED")
    if any(isinstance(w, bool) or not isinstance(w, (float, int))
           or not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError("FINITE_POSITIVE_WEIGHTS_REQUIRED")
    return [float(w) for w in weights], k


def _elementary(weights: list[float], degree: int) -> list[float]:
    """Positive dynamic program for elementary symmetric coefficients."""
    e = [1.0] + [0.0] * degree
    for seen, weight in enumerate(weights, 1):
        for d in range(min(degree, seen), 0, -1):
            e[d] += weight * e[d - 1]
    return e


def _delete(e: list[float], weight: float, degree: int) -> list[float]:
    result = [1.0]
    for d in range(1, degree + 1):
        result.append(e[d] - weight * result[d - 1])
    return result


def _logadd(a: float, b: float) -> float:
    if a == -math.inf:
        return b
    if b == -math.inf:
        return a
    hi, lo = max(a, b), min(a, b)
    return hi + math.log1p(math.exp(lo - hi))


def _log_elementary(logweights: list[float], degree: int) -> list[float]:
    e = [0.0] + [-math.inf] * degree
    for seen, logweight in enumerate(logweights, 1):
        for d in range(min(degree, seen), 0, -1):
            e[d] = _logadd(e[d], logweight + e[d - 1])
    return e


def _valid_pair_probabilities(result: dict, n: int, k: int) -> bool:
    if any(not math.isfinite(q) or not 0.0 <= q <= 1.0 for q in result.values()):
        return False
    return math.isclose(math.fsum(result.values()), math.comb(k, 2), rel_tol=2e-10, abs_tol=2e-10)


def conditional_pair_probabilities(weights: list[float], k: int) -> dict[tuple[int, int], float]:
    """Exact fixed-k product-weight joint inclusions, using one-based numbers.

    Fast coefficient deletion is O(n^2 k).  Cancellation or underflow triggers
    a positive excluded-pair DP, then log-space DP for extreme public inputs.
    These numerical fallbacks do not change the registered model.
    """
    weights, k = _inputs(weights, k)
    n = len(weights)
    pairs = list(itertools.combinations(range(n), 2))
    if k < 2:
        return {(i + 1, j + 1): 0.0 for i, j in pairs}
    if k == n:
        return {(i + 1, j + 1): 1.0 for i, j in pairs}
    # Overall scale cancels from every conditional probability.
    largest = max(weights)
    scaled = [w / largest for w in weights]
    e = _elementary(scaled, k)
    result = {}
    # Ratios of subnormal coefficients can be badly wrong while pair mass
    # still sums correctly.  Reserve exponent headroom for the numerators,
    # and never use a scaled DP that has lost positive support to underflow.
    ordinary_dp_safe = (all(weight > 0.0 for weight in scaled)
                        and e[k] >= math.sqrt(sys.float_info.min)
                        and math.isfinite(e[k]))
    if ordinary_dp_safe:
        deleted = [_delete(e, weight, k - 2) for weight in scaled]
        for i, j in pairs:
            excluded = _delete(deleted[i], scaled[j], k - 2)
            result[i + 1, j + 1] = scaled[i] * scaled[j] * excluded[k - 2] / e[k]
        if _valid_pair_probabilities(result, n, k):
            return result
        # Positive operations avoid subtraction cancellation in deletion.
        for i, j in pairs:
            other = [weight for a, weight in enumerate(scaled) if a != i and a != j]
            coefficient = _elementary(other, k - 2)[k - 2]
            result[i + 1, j + 1] = scaled[i] * scaled[j] * coefficient / e[k]
        if _valid_pair_probabilities(result, n, k):
            return result
    logs = [math.log(w) for w in weights]
    logz = _log_elementary(logs, k)[k]
    for i, j in pairs:
        other = [v for a, v in enumerate(logs) if a != i and a != j]
        logq = logs[i] + logs[j] + _log_elementary(other, k - 2)[k - 2] - logz
        result[i + 1, j + 1] = math.exp(min(0.0, logq))
    if not _valid_pair_probabilities(result, n, k):
        raise ArithmeticError("CONDITIONAL_PAIR_NUMERICAL_FAILURE")
    return result


def sample_conditional(weights: list[float], k: int, rng) -> list[int]:
    """Sample exactly k numbers from product weights using a suffix DP.

    Log-space suffix coefficients preserve very unequal positive weights.
    ``rng`` supplies random(), and the result is sorted and one-based.
    """
    weights, k = _inputs(weights, k)
    n = len(weights)
    logs = [math.log(w) for w in weights]
    suffix = [[0.0] + [-math.inf] * k for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for need in range(1, min(k, n - i) + 1):
            suffix[i][need] = _logadd(suffix[i + 1][need], logs[i] + suffix[i + 1][need - 1])
    selected = []
    need = k
    for i in range(n):
        if need == 0:
            break
        if n - i == need:
            selected.extend(range(i + 1, n + 1))
            break
        probability = math.exp(min(0.0, logs[i] + suffix[i + 1][need - 1] - suffix[i][need]))
        if rng.random() < probability:
            selected.append(i + 1)
            need -= 1
    return selected


def predict_candidates(game: str, history: list[dict]) -> dict:
    """Return one fixed D2 per candidate from a validated supplied prefix.

    The caller must enforce target/as-of source admission.  This function has
    no target issue and cannot certify a prefix as pre-draw evidence.
    """
    oldmodels.validate_history(game, "UNASSIGNED", history)
    if len(history) < PARAMETERS["base_window"]:
        raise oldmodels.ModelBlocked("AT_LEAST_240_HISTORY_DRAWS_REQUIRED")
    n, k, _, _ = oldmodels.RULES[game]
    base = history[-PARAMETERS["base_window"]:]
    recent = base[-PARAMETERS["recent_window"]:]
    previous = base[-2 * PARAMETERS["replication_block_window"]:-PARAMETERS["replication_block_window"]]
    counts = Counter(number for row in base for number in row["front"])
    marginal_pseudo = PARAMETERS["marginal_pseudo_draws"]
    shrunk = [(counts[i] + marginal_pseudo * k / n) / (len(base) + marginal_pseudo)
              for i in range(1, n + 1)]
    weights = [p / (1.0 - p) for p in shrunk]
    q = conditional_pair_probabilities(weights, k)
    conditional_marginals = [math.fsum(value for pair, value in q.items() if i in pair) / (k - 1)
                             for i in range(1, n + 1)]
    h_recent = Counter(pair for row in recent for pair in itertools.combinations(sorted(row["front"]), 2))
    h_previous = Counter(pair for row in previous for pair in itertools.combinations(sorted(row["front"]), 2))
    tau = PARAMETERS["pair_prior_pseudo_draws"]
    scores = {pair: (h_recent[pair] + tau * probability) / (len(recent) + tau)
              for pair, probability in q.items()}
    decimals = PARAMETERS["tie_score_decimals"]
    first = min(q, key=lambda pair: (-round(scores[pair], decimals), -h_recent[pair],
                                     -sum(counts[i] for i in pair), pair))
    block = PARAMETERS["replication_block_window"]
    z = {pair: min((h_recent[pair] - block * probability)
                  / math.sqrt(block * probability * (1.0 - probability)
                              + PARAMETERS["replication_variance_floor_addend"]),
                  (h_previous[pair] - block * probability)
                  / math.sqrt(block * probability * (1.0 - probability)
                              + PARAMETERS["replication_variance_floor_addend"]))
         for pair, probability in q.items()}
    fallback = max(z.values()) <= 0.0
    top = sorted(range(1, n + 1), key=lambda i: (-weights[i - 1], i))
    second = tuple(sorted(top[:2])) if fallback else min(
        q, key=lambda pair: (-round(z[pair], decimals), -round(scores[pair], decimals), pair))
    shared = {
        "history_size": len(history),
        "base_window": len(base),
        "recent_window": len(recent),
        "previous_window": len(previous),
        "prior_pair_mass": math.fsum(q.values()),
        "expected_pair_mass": math.comb(k, 2),
        "max_abs_conditional_vs_input_marginal": max(abs(a - b) for a, b in zip(conditional_marginals, shrunk)),
        "marginal_mapping": PARAMETERS["weight_mapping"],
    }
    return {
        MODEL_IDS[0]: {"d2": list(first), "pair_probabilities": dict(scores), "diagnostics": {
            **shared, "score": scores[first], "prior_joint_probability": q[first],
            "recent_pair_count": h_recent[first],
            "base_marginal_sum": sum(counts[i] for i in first),
            "score_is_probability": True,
        }},
        MODEL_IDS[1]: {"d2": list(second), "diagnostics": {
            **shared, "score": z[second], "max_min_block_score": max(z.values()),
            "prior_joint_probability": q[second], "mixture_score": scores[second],
            "recent_pair_count": h_recent[second], "previous_pair_count": h_previous[second],
            "fallback_top_two_odds": fallback, "score_is_probability": False,
        }},
    }
