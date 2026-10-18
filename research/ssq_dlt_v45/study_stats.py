"""Research D2 statistics and prospective sample-size scenarios, stdlib only.

No statistic in this module establishes admission or a predictive edge.  Wilson,
Clopper--Pearson and conditional McNemar calculations assume independent,
identically distributed paired observations.  Adaptive training can change the
joint distribution over time; an as-of replay alone does not verify that model.
The fair-null e-process instead assumes fair independent draws and forecasts
measurable before each draw. Historical source availability is not proved here.
"""
from __future__ import annotations

from fractions import Fraction
from math import (ceil, comb, cosh, exp, fsum, isfinite, lgamma, log, log1p,
                  sqrt)
from statistics import NormalDist
from typing import Mapping, Sequence


GAMES = {"SSQ": (33, 6), "DLT": (35, 5)}
E_LAMBDAS = (0.05, 0.1, 0.2, 0.4, 0.8)
REFERENCES = [
    {"title": "NIST: Binomial proportion confidence intervals",
     "url": "https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm"},
    {"title": "NIST: Exact binomial (Clopper-Pearson) limits",
     "url": "https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/propconf.htm"},
    {"title": "statsmodels: Exact McNemar uses the binomial distribution",
     "url": "https://www.statsmodels.org/dev/generated/statsmodels.stats.contingency_tables.mcnemar.html"},
    {"title": "R stats: Holm familywise adjustment",
     "url": "https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html"},
]


def _count(value: int, name: str = "count") -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _probability(value: float, name: str, *, open_interval: bool = False) -> None:
    if (type(value) not in (int, float) or not isfinite(value)
            or not (0 < value < 1 if open_interval else 0 <= value <= 1)):
        raise ValueError(f"{name} must be a finite probability")


def _counts(successes: int, n: int) -> None:
    _count(successes, "successes")
    _count(n, "n")
    if successes > n:
        raise ValueError("successes cannot exceed n")


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> list[float]:
    """Two-sided Wilson score interval; n=0 returns [0,1], not an estimate."""
    _counts(successes, n)
    _probability(confidence, "confidence", open_interval=True)
    if n == 0:
        return [0.0, 1.0]
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion, z2 = successes / n, z * z
    denominator = 1 + z2 / n
    center = (proportion + z2 / (2 * n)) / denominator
    half = z * sqrt(proportion * (1 - proportion) / n + z2 / (4 * n * n)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def _binomial_small_tail(k: int, n: int, p: float, *, upper: bool) -> float:
    """Sum away from the mode, starting at the largest term of that tail.

    The caller chooses a tail whose endpoint is on its side of the mean.  The
    recurrence cannot overflow; the starting mass uses log-gamma for thousands
    of observations.  Extreme probabilities can underflow to float zero.
    """
    mass = exp(lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
               + k * log(p) + (n - k) * log1p(-p))
    weights, weight = [1.0], 1.0
    if upper:
        for j in range(k, n):
            weight *= (n - j) / (j + 1) * p / (1 - p)
            weights.append(weight)
            if weight < 1e-17:
                break
    else:
        for j in range(k, 0, -1):
            weight *= j / (n - j + 1) * (1 - p) / p
            weights.append(weight)
            if weight < 1e-17:
                break
    return min(1.0, max(0.0, mass * fsum(weights)))


def binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P[Binomial(n,p)>=k], with stable tail summation and endpoint handling."""
    _count(n, "n")
    if type(k) is not int:
        raise ValueError("k must be integer")
    _probability(p, "p")
    if k <= 0:
        return 1.0
    if k > n or p == 0:
        return 0.0
    if p == 1:
        return 1.0
    if k > n * p:
        return _binomial_small_tail(k, n, p, upper=True)
    return max(0.0, 1.0 - _binomial_small_tail(k - 1, n, p, upper=False))


def paired_exact_one_sided(wins: int, losses: int) -> float:
    """Conditional McNemar P[Binomial(wins+losses,.5)>=wins].

    H1 is model better than NULL. Validity requires iid paired observations
    under equal marginal success probabilities, not merely sorted draw dates.
    """
    _count(wins, "wins")
    _count(losses, "losses")
    return binomial_upper_tail(wins, wins + losses, 0.5)


def _cp_bounds(successes: int, n: int, tail_alpha: float) -> list[float]:
    """One lower and one upper Clopper--Pearson bound, each tail_alpha."""
    if n == 0:
        return [0.0, 1.0]
    if successes == 0:
        lower = 0.0
    else:
        left, right = 0.0, 1.0
        for _ in range(64):
            middle = (left + right) / 2
            if binomial_upper_tail(successes, n, middle) < tail_alpha:
                left = middle
            else:
                right = middle
        lower = (left + right) / 2
    if successes == n:
        upper = 1.0
    else:
        # P[X<=x] = P[Binomial(n,1-p)>=n-x]; avoids cancellation.
        left, right = 0.0, 1.0
        for _ in range(64):
            middle = (left + right) / 2
            if binomial_upper_tail(n - successes, n, 1 - middle) > tail_alpha:
                left = middle
            else:
                right = middle
        upper = (left + right) / 2
    return [lower, upper]


def paired_difference_interval(wins: int, losses: int, n: int,
                               confidence: float = 0.95) -> list[float]:
    """Conservative two-sided CI for p10-p01, including sparse/all-zero data.

    There are four one-sided Clopper--Pearson bounds, each alpha/4. By a
    Bonferroni union bound their rectangle and its difference have coverage
    at least confidence under an iid multinomial paired-observation model.
    These are per-comparison CIs, not simultaneous CIs for the model family.
    """
    _counts(wins, n)
    _counts(losses, n)
    if wins + losses > n:
        raise ValueError("discordant counts cannot exceed n")
    _probability(confidence, "confidence", open_interval=True)
    if n == 0:
        return [-1.0, 1.0]
    lower_win, upper_win = _cp_bounds(wins, n, (1 - confidence) / 4)
    lower_loss, upper_loss = _cp_bounds(losses, n, (1 - confidence) / 4)
    return [max(-1.0, lower_win - upper_loss), min(1.0, upper_win - lower_loss)]


def _binary(values: Sequence[int], name: str) -> list[int]:
    if (not isinstance(values, (list, tuple))
            or any(type(value) is not int or value not in (0, 1) for value in values)):
        raise ValueError(f"{name} must contain integer 0/1 outcomes")
    return list(values)


def paired_summary(model_hits: Sequence[int], null_hits: Sequence[int],
                   confidence: float = 0.95) -> dict:
    """Describe same-period D2 full hits. Does not prove as-of source integrity."""
    model = _binary(model_hits, "model_hits")
    null = _binary(null_hits, "null_hits")
    if len(model) != len(null):
        raise ValueError("paired series must have equal length")
    n = len(model)
    wins = sum(x == 1 and y == 0 for x, y in zip(model, null))
    losses = sum(x == 0 and y == 1 for x, y in zip(model, null))
    return {
        "n": n, "model_hits": sum(model), "null_hits": sum(null),
        "wins": wins, "losses": losses,
        "both_hit": sum(x == 1 and y == 1 for x, y in zip(model, null)),
        "both_miss": sum(x == 0 and y == 0 for x, y in zip(model, null)),
        "model_rate": sum(model) / n if n else None,
        "null_rate": sum(null) / n if n else None,
        "model_rate_ci": wilson_interval(sum(model), n, confidence),
        "null_rate_ci": wilson_interval(sum(null), n, confidence),
        "paired_delta": (wins - losses) / n if n else None,
        "paired_delta_ci": paired_difference_interval(wins, losses, n, confidence),
        "confidence": confidence,
        "ci_method": "CP_DISCORDANT_MARGINALS_FOUR_ONE_SIDED_BONFERRONI",
        "ci_scope": "PER_COMPARISON_NOT_FAMILY_SIMULTANEOUS",
        "p_one_sided": paired_exact_one_sided(wins, losses),
        "assumption": "IID_PAIRED_OBSERVATIONS_NOT_VERIFIED_BY_REPLAY",
        "formal_A": 0, "decision": "NO_EDGE",
    }


def holm_adjust(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjustment; caller must supply the entire frozen family."""
    if not isinstance(pvalues, Mapping) or not pvalues:
        raise ValueError("complete nonempty Holm family required")
    for key, pvalue in pvalues.items():
        if type(key) is not str or not key:
            raise ValueError("nonempty string hypothesis keys required")
        _probability(pvalue, "pvalue")
    ordered = sorted(pvalues, key=lambda key: (pvalues[key], key))
    adjusted, maximum = {}, 0.0
    for rank, key in enumerate(ordered):
        maximum = max(maximum, (len(ordered) - rank) * pvalues[key])
        adjusted[key] = min(1.0, maximum)
    return adjusted


def _fraction(value: Fraction) -> dict:
    return {"numerator": value.numerator, "denominator": value.denominator,
            "value": float(value)}


def uniform_pair_probabilities(game: str, overlap: int) -> dict:
    """Exact uniform k-of-N probabilities for fixed pairs sharing 0,1,2 items.

    Both pairs hit iff all 4-overlap union members occur in the draw, with
    probability C(N-(4-overlap), k-(4-overlap))/C(N,k). No Monte Carlo used.
    """
    if type(game) is not str or game not in GAMES:
        raise ValueError("unknown game")
    if type(overlap) is not int or overlap not in (0, 1, 2):
        raise ValueError("overlap must be 0, 1, or 2")
    upper, count = GAMES[game]
    union = 4 - overlap
    denominator = comb(upper, count)
    hit = Fraction(comb(count, 2), comb(upper, 2))
    both = Fraction(comb(upper - union, count - union), denominator)
    one = hit - both
    return {"game": game, "overlap": overlap, "union_size": union,
            "marginal_hit": _fraction(hit), "both_hit": _fraction(both),
            "model_only": _fraction(one), "null_only": _fraction(one),
            "disagreement": _fraction(2 * one),
            "neither_hit": _fraction(1 - 2 * hit + both),
            "formula": "P(both)=C(N-union,k-union)/C(N,k); q=2*(p-P(both))"}


def paired_sample_size(p_null: float, delta: float, disagreement: float, *,
                       alpha: float = 0.005, power: float = 0.8) -> dict:
    """Unconditional normal paired-difference planning approximation.

    n = ceil((z_(1-alpha)*sqrt(q)+z_power*sqrt(q-delta^2))^2/delta^2).
    q=P(model-only)+P(null-only), fixed under the alternative. Random
    discordance counts, discreteness, continuity corrections, temporal drift
    and model-selection uncertainty are not captured. This is not guaranteed
    exact-McNemar power, and must not be treated as an observed improvement.
    """
    _probability(p_null, "p_null")
    _probability(delta, "delta", open_interval=True)
    _probability(disagreement, "disagreement")
    _probability(alpha, "alpha", open_interval=True)
    _probability(power, "power", open_interval=True)
    if alpha >= 0.5 or power <= 0.5:
        raise ValueError("planning requires alpha<.5 and power>.5")
    p_model = p_null + delta
    if p_model > 1:
        raise ValueError("alternative probability exceeds one")
    # Frechet constraints for a 2x2 table with the requested marginals.
    q_max = min(p_model + p_null, 2 - p_model - p_null)
    if disagreement < delta - 1e-14 or disagreement > q_max + 1e-14:
        raise ValueError("infeasible paired discordance for these marginals")
    za, zb = NormalDist().inv_cdf(1 - alpha), NormalDist().inv_cdf(power)
    raw = (za * sqrt(disagreement)
           + zb * sqrt(max(0.0, disagreement - delta * delta))) ** 2 / (delta * delta)
    n = ceil(raw)
    return {"p_null": p_null, "p_model": p_model, "absolute_delta": delta,
            "disagreement": disagreement, "alpha_one_sided": alpha,
            "target_power": power, "n_approx": n,
            "expected_model_hits": n * p_model, "expected_null_hits": n * p_null,
            "expected_discordant": n * disagreement,
            "method": "NORMAL_PAIRED_DIFFERENCE_APPROXIMATION_NO_CONTINUITY_CORRECTION",
            "guaranteed_power": False}


def power_report(family_size: int = 10, alpha: float = 0.05,
                 power: float = 0.8, primary_delta: float = 0.01) -> dict:
    """Frozen planning scenarios; primary target is an absolute one percentage point."""
    _count(family_size, "family_size")
    if family_size == 0:
        raise ValueError("family size must be positive")
    _probability(alpha, "alpha", open_interval=True)
    _probability(power, "power", open_interval=True)
    _probability(primary_delta, "primary_delta", open_interval=True)
    deltas = sorted({0.005, 0.01, 0.02, float(primary_delta)})
    games = {}
    for game in GAMES:
        p0 = uniform_pair_probabilities(game, 0)["marginal_hit"]["value"]
        scenarios = []
        for delta in deltas:
            p1 = p0 + delta
            if p1 > 1:
                raise ValueError("planning alternative exceeds one")
            for name, joint in (("INDEPENDENT_SUCCESS_INDICATORS", p0 * p1),
                                ("MAXIMUM_DISCORDANCE_FRECHET", max(0.0, p0 + p1 - 1))):
                item = paired_sample_size(p0, delta, p0 + p1 - 2 * joint,
                                          alpha=alpha / family_size, power=power)
                item.update({"scenario": name, "joint_success": joint,
                             "primary_specification": delta == primary_delta,
                             "approx_years_at_156_draws_per_year": item["n_approx"] / 156})
                scenarios.append(item)
        games[game] = {"p0": p0, "sample_size_scenarios": scenarios,
                       "uniform_draw_overlap_scenarios": [uniform_pair_probabilities(game, o)
                                                          for o in (0, 1, 2)]}
    return {"schema": "ssq-dlt-v45-d2-power-1", "family_size": family_size,
            "family_alpha": alpha, "bonferroni_planning_alpha": alpha / family_size,
            "target_power": power, "primary_absolute_delta": primary_delta,
            "games": games,
            "assumptions": ["IID paired observations and stable alternative success rates",
                            "Fixed discordance scenario, no exact-power guarantee",
                            "Bonferroni planning is conservative relative to Holm critical values",
                            "156 draws/year is a scale illustration, not a verified future schedule",
                            "Fresh prospective periods with trusted pre-draw sealing still required"],
            "references": REFERENCES, "formal_A": 0, "decision": "NO_EDGE"}


def fair_null_eprocess(game: str, predictions_model: Sequence[Sequence[int]],
                       predictions_null: Sequence[Sequence[int]],
                       model_hits: Sequence[int], null_hits: Sequence[int]) -> dict:
    """Fixed equal-weight positive-lambda mixture for a fair-draw secondary check.

    Given pre-draw pairs, D_t=hit_model-hit_null and
    E[exp(lambda D_t)|past]=1+q_t*(cosh(lambda)-1), where q_t is determined by
    pair overlap. Each normalized product, and their fixed mixture, is a
    nonnegative martingale under conditionally uniform independent draws.
    Markov and Ville bounds give fixed-final and anytime-valid p bounds.
    This does not establish forecast predictability or historical availability.
    Do not select a winner by trying extra lambdas after seeing outcomes.
    """
    if type(game) is not str or game not in GAMES:
        raise ValueError("unknown game")
    model, null = _binary(model_hits, "model_hits"), _binary(null_hits, "null_hits")
    if not (len(model) == len(null) == len(predictions_model) == len(predictions_null)):
        raise ValueError("complete paired predictions and outcomes required")
    upper = GAMES[game][0]
    log_products = [0.0] * len(E_LAMBDAS)
    log_max, log_mixture = 0.0, 0.0
    overlap_counts = {str(overlap): 0 for overlap in (0, 1, 2)}
    for pair_model, pair_null, hit_model, hit_null in zip(predictions_model,
                                                        predictions_null, model, null):
        for pair in (pair_model, pair_null):
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(type(number) is not int or not 1 <= number <= upper for number in pair)
                    or len(set(pair)) != 2):
                raise ValueError("legal two-number forecasts required")
        overlap = len(set(pair_model) & set(pair_null))
        if overlap == 2 and hit_model != hit_null:
            raise ValueError("identical pairs cannot have discordant full-hit scores")
        overlap_counts[str(overlap)] += 1
        q = uniform_pair_probabilities(game, overlap)["disagreement"]["value"]
        difference = hit_model - hit_null
        for index, lam in enumerate(E_LAMBDAS):
            log_products[index] += lam * difference - log1p(q * (cosh(lam) - 1))
        maximum = max(log_products)
        log_mixture = maximum + log(fsum(exp(value - maximum) for value in log_products)) - log(len(E_LAMBDAS))
        log_max = max(log_max, log_mixture)
    overflow = log_mixture > 709.0
    return {"schema": "ssq-dlt-v45-fair-null-eprocess-1", "game": game, "n": len(model),
            "lambdas": list(E_LAMBDAS), "mixture_weights": [1 / len(E_LAMBDAS)] * len(E_LAMBDAS),
            "overlap_counts": overlap_counts, "final_log_e_value": log_mixture,
            "final_e_value": None if overflow else exp(log_mixture),
            "e_value_overflow_use_log": overflow,
            "fixed_final_p_markov": exp(-max(0.0, log_mixture)),
            "running_max_log_e_value": log_max,
            "anytime_p_markov": exp(-log_max),
            "scope": "SECONDARY_FAIR_UNIFORM_NULL_SENSITIVITY_NOT_MODEL_SELECTION",
            "assumptions": ["Conditionally uniform independent draws",
                            "Both forecasts predictable before each draw",
                            "Correct full-hit scoring, complete period sequence",
                            "Fixed lambdas and equal mixture weights before outcomes"],
            "availability_verified": False, "formal_A": 0, "decision": "NO_EDGE"}
