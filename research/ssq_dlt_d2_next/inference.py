"""Frozen research inference and synthetic operating characteristics, no data IO.

Historical metrics remain descriptive.  In particular a conditional uniform
draw law makes predictable legal pair hits Bernoulli(p0), even with adaptive
training, but does not establish the IID paired model needed by the separate
McNemar component.  Simulated binary tables establish neither premise in life.
"""
from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
from math import ceil, exp, fsum, lgamma, log, log1p
from random import Random
from typing import Mapping, Sequence

from research.ssq_dlt_v45 import study_stats as stats


CANDIDATES = ("R46-CBPAIR-SHRINK", "R46-REPLICATED-PAIR")
BENCHMARKS = ("R45-HOT60", "R45-EWMA", "R45-SHRINKMIX",
              "R45-PAIRWISE-D2", "R45-PAIR-RESIDUAL")
GAMES = ("SSQ", "DLT")
NULL_MODEL = "R45-RANDOM-NULL"
FAMILY_ALPHA = 0.05
PLANNING_DELTA = 0.01
TARGET_POWER = 0.8
COMPONENT_PLANNING_POWER = 0.9
SIMULATION_SEED = 2026101903
SIMULATION_REPLICATIONS = 2000
JOINT_SCENARIOS = ("INDEPENDENT_INDICATORS", "MAXIMUM_DISCORDANCE", "NESTED_HITS")
NULL_CONFIGURATIONS = ((0, 0, 0, 0), (1, 0, 0, 0),
                       (1, 1, 0, 0), (1, 1, 1, 1))


def hypothesis_key(game: str, model: str) -> str:
    if game not in GAMES or model not in BENCHMARKS + CANDIDATES:
        raise ValueError("registered game and non-NULL model required")
    return f"{game}|{model}"


def fair_p0(game: str) -> float:
    if game not in GAMES:
        raise ValueError("unknown game")
    upper, count = stats.GAMES[game]
    return count * (count - 1) / (upper * (upper - 1))


def common_metrics(game: str, model_hits: Sequence[int],
                   null_hits: Sequence[int]) -> dict:
    """Same metrics for every historical producer; never grants admission."""
    p0 = fair_p0(game)
    paired = stats.paired_summary(model_hits, null_hits)
    n, hits = paired["n"], paired["model_hits"]
    analytic = stats.binomial_upper_tail(hits, n, p0)
    # A conjunction of two superiority claims uses max(p1,p2), not min or Fisher.
    # Its validity requires valid component tests under their respective nulls.
    iut = max(analytic, paired["p_one_sided"])
    cp = stats._cp_bounds(hits, n, 0.025)
    return {
        **paired, "game": game, "hits": hits, "rate": paired["model_rate"],
        "fair_d2_p0": p0, "p_fair_one_sided": analytic, "p_iut": iut,
        "rate_ci95": paired["model_rate_ci"], "rate_ci95_exact": cp,
        "delta_vs_fair": hits / n - p0 if n else None,
        "delta_vs_fair_ci95_exact": [cp[0] - p0, cp[1] - p0],
        "paired": paired,
        "analytic_assumption": "CONDITIONAL_HIT_PROBABILITY_P0_EACH_PERIOD_PREDICTABLE_PAIR_FIXED_N",
        "paired_assumption": "IID_PAIRED_BINARY_OBSERVATIONS_UNVERIFIED",
        "confirmation_gate": "BLOCKED_PAIRED_IID_AND_PROSPECTIVE_INTEGRITY_UNVERIFIED",
        "scope": "HISTORICAL_DEV_EXPLORATORY_ONLY",
        "independent_prospective_samples": 0,
        "formal_A": 0, "decision": "NO_EDGE",
    }


def descriptive_family(metrics: Mapping[str, dict]) -> dict:
    """All 7 non-NULL producers x 2 games, never a historical selection rule."""
    expected = {hypothesis_key(game, model)
                for game in GAMES for model in BENCHMARKS + CANDIDATES}
    if not isinstance(metrics, Mapping) or set(metrics) != expected:
        raise ValueError("the complete frozen 14-hypothesis historical family is required")
    adjusted = {}
    for field in ("p_fair_one_sided", "p_one_sided", "p_iut"):
        adjusted[field] = stats.holm_adjust({key: value[field]
                                             for key, value in metrics.items()})
    return {
        "family_size": 14, "hypotheses": sorted(expected),
        "alpha": FAMILY_ALPHA, "p_holm_iut": adjusted["p_iut"],
        "p_holm_fair": adjusted["p_fair_one_sided"],
        "p_holm_paired": adjusted["p_one_sided"],
        "scope": "HISTORICAL_DEV_EXPLORATORY_NOT_SELECTION_OR_CONFIRMATION",
        "independent_prospective_samples": 0,
        "formal_A": 0, "decision": "NO_EDGE",
    }


def _critical_hits(n: int, p0: float, alpha: float) -> int:
    left, right = 0, n + 1
    while left < right:
        middle = (left + right) // 2
        if stats.binomial_upper_tail(middle, n, p0) <= alpha:
            right = middle
        else:
            left = middle + 1
    return left


@lru_cache(maxsize=None)
def exact_binomial_plan(p0: float, p1: float, alpha: float,
                        power: float = TARGET_POWER, maximum_n: int = 50000) -> dict:
    """First integer n attaining requested power, by exact-tail linear scan.

    Discrete power need not be monotone in n.  This searches every preceding
    n, rather than using an unjustified binary search over sample sizes.
    """
    if not (0 < p0 < p1 < 1 and 0 < alpha < 0.5 and 0.5 < power < 1):
        raise ValueError("valid ordered probabilities, one-sided alpha and power required")
    if type(maximum_n) is not int or maximum_n < 1:
        raise ValueError("positive integer maximum_n required")
    critical = 1
    for n in range(1, maximum_n + 1):
        while stats.binomial_upper_tail(critical, n, p0) > alpha:
            critical += 1
        achieved = stats.binomial_upper_tail(critical, n, p1)
        if achieved >= power:
            return {"n": n, "critical_hits": critical, "power": achieved,
                    "actual_size": stats.binomial_upper_tail(critical, n, p0),
                    "alpha": alpha, "target_power": power,
                    "method": "EXACT_BINOMIAL_FIRST_ATTAINING_INTEGER_N"}
    raise ValueError("no attaining sample size within maximum_n")


def _joint(p0: float, p1: float, scenario: str) -> float:
    if scenario == "INDEPENDENT_INDICATORS":
        return p0 * p1
    if scenario == "MAXIMUM_DISCORDANCE":
        return max(0.0, p0 + p1 - 1)
    if scenario == "NESTED_HITS":
        return min(p0, p1)
    raise ValueError("unknown predeclared joint scenario")


def future_protocol() -> dict:
    """Pure mathematical fixed design; no archive, DB, model scoring or start."""
    alpha = FAMILY_ALPHA / 4
    planning = {}
    comparisons = []
    for game in GAMES:
        p0, rows = fair_p0(game), []
        p1 = p0 + PLANNING_DELTA
        for family_size in (2, 4):
            a = FAMILY_ALPHA / family_size
            scenarios = []
            for scenario in JOINT_SCENARIOS:
                joint = _joint(p0, p1, scenario)
                q = p0 + p1 - 2 * joint
                item = stats.paired_sample_size(p0, PLANNING_DELTA, q, alpha=a,
                                                power=TARGET_POWER)
                scenarios.append({**item, "scenario": scenario,
                                  "joint_success": joint})
            comparisons.append({"game": game, "family_size": family_size,
                                "analytic_exact_80": exact_binomial_plan(p0, p1, a),
                                "paired_normal_80": scenarios})
        for scenario in JOINT_SCENARIOS:
            joint = _joint(p0, p1, scenario)
            rows.append({**stats.paired_sample_size(
                p0, PLANNING_DELTA, p0 + p1 - 2 * joint, alpha=alpha,
                power=COMPONENT_PLANNING_POWER), "scenario": scenario,
                "joint_success": joint})
        analytic90 = exact_binomial_plan(p0, p1, alpha, COMPONENT_PLANNING_POWER)
        initial_n = max(analytic90["n"], *(row["n_approx"] for row in rows))
        n = 100 * ceil(initial_n / 100)
        planning[game] = {
            "p0": p0, "p1_planning": p1,
            "fixed_n": n, "analytic_exact_90": analytic90,
            "paired_normal_90": rows,
            "analytic_power_at_fixed_n": stats.binomial_upper_tail(
                _critical_hits(n, p0, alpha), n, p1),
            "approx_years_at_156_periods_per_year": n / 156,
            "calendar_conversion_is_illustrative_not_a_verified_schedule": True,
        }
    return {
        "schema": "V46_D2_FUTURE_MATHEMATICAL_PROTOCOL_1",
        "scope": "PROSPECTIVE_DESIGN_NOT_STARTED_NO_NEW_OUTCOMES",
        "candidates": list(CANDIDATES), "games": list(GAMES),
        "hypotheses": [hypothesis_key(game, model)
                       for game in GAMES for model in CANDIDATES],
        "family_size": 4, "family_alpha": FAMILY_ALPHA,
        "bonferroni_planning_alpha": alpha, "target_iut_power": TARGET_POWER,
        "component_planning_power": COMPONENT_PLANNING_POWER,
        "delta_planning_alternative": PLANNING_DELTA,
        "effect_claim": "SUPERIORITY_OVER_ZERO_ONLY_NOT_PROOF_DELTA_AT_LEAST_0_01",
        "iut": "max(p_analytic_fair,p_paired_exact); Holm over all four IUT p values",
        "confidence_intervals": {
            "report": "95% per-comparison exact analytic and conservative paired difference intervals",
            "family_reporting": "Optional 98.75% intervals for each component across four hypotheses give component-wise simultaneous-by-Bonferroni coverage; not joint coverage across both components",
            "paired_method": "CP four one-sided discordant-marginal bounds; assumption IID multinomial",
            "not_an_extra_gate": "no additional CI lower>0 or observed>=.01 gating",
        },
        "games_planning": planning, "one_vs_two_candidate_comparison": comparisons,
        "iut_power_bound": "If both actual component powers >=0.9 at this fixed alternative, union bound gives conjunction power >=0.8, without independence. Normal planning alone does not certify either power.",
        "simulation": {
            "seed": SIMULATION_SEED, "replications_per_cell": SIMULATION_REPLICATIONS,
            "joint_scenarios": list(JOINT_SCENARIOS),
            "alternative_configurations": [list(row) for row in NULL_CONFIGURATIONS],
            "configuration_scope": "Exactly four predeclared configurations, not all sixteen; no empirical claim of exhaustive strong-FWER validation",
            "sampling": "IID binary counts; common same-game NULL, candidates conditionally independent given NULL; independent games",
            "report": "Per-hypothesis IUT power at Bonferroni and Holm, family-any rejection, true-null FWER, marginal 95% Wilson Monte Carlo intervals",
            "classification": {
                "power_for_nonzero_delta": "PASS if MC lower>=0.8; FAIL if MC upper<0.8; otherwise INCONCLUSIVE",
                "fwer_with_true_nulls": "PASS_SPECIFIED_SYNTHETIC_LAW if MC upper<=0.05; FAIL if MC lower>0.05; otherwise INCONCLUSIVE",
                "no_true_nulls": "FWER classification NOT_APPLICABLE",
                "null_hypothesis_power": "Power classification NOT_APPLICABLE_FOR_TRUE_NULL",
                "interval_scope": "Marginal 95% Wilson intervals, not simultaneous intervals or a proof of calibration in untested laws",
                "response": "Report the fixed result as is; no outcome-driven sample-size, seed, scenario or configuration changes",
            },
            "no_post_simulation_retargeting": True,
            "not_a_test_of_candidate_predictive_skill": True,
        },
        "stopping_rule": "One final analysis at fixed_n for each game; no efficacy peeking, optional extension, seed replacement, dropped periods, candidate replacement or early promotion. Integrity failure blocks confirmation and is retained in the audit log.",
        "confirmatory_gate": "All provenance and inferential preconditions satisfied, then Holm-adjusted IUT p<=0.05; no additional CI lower>0 or observed>=.01 gating",
        "mandatory_preconditions": [
            "Independently timestamped pre-draw code/parameter/plan seals and every forecast",
            "Authenticated official legal issue plus trustworthy complete as-of source history",
            "Entirely new outcomes after this registration; no oldtest or dev rebranding",
            "A defensible IID paired binary model for McNemar/paired CIs; otherwise BLOCKED",
            "Conditionally fair independent draws, or conditional hit probability bounded by p0, for analytic exact-null calibration",
        ],
        "secondary_eprocess": "Frozen fair-null e-process may provide valid sequential evidence without IID paired observations under predictable forecasts and conditionally uniform draws; cannot repair forecast provenance, paired-IID gate, or justify early promotion in this fixed-n protocol",
        "prospective_start": "BLOCKED_UNTIL_OFFICIAL_TARGET_AND_TRUSTED_SEAL_AVAILABLE",
        "independent_prospective_samples": 0, "formal_A": 0, "decision": "NO_EDGE",
    }


def _binomial_cdf(n: int, p: float) -> tuple[float, ...]:
    """Mode-centered stable binomial law for exact-count synthetic sampling."""
    if n == 0 or p == 0:
        return (1.0,) * (n + 1)
    if p == 1:
        return (0.0,) * n + (1.0,)
    mode = min(n, int((n + 1) * p))
    masses = [0.0] * (n + 1)
    masses[mode] = exp(lgamma(n + 1) - lgamma(mode + 1) - lgamma(n - mode + 1)
                       + mode * log(p) + (n - mode) * log1p(-p))
    for k in range(mode, 0, -1):
        masses[k - 1] = masses[k] * k / (n - k + 1) * (1 - p) / p
    for k in range(mode, n):
        masses[k + 1] = masses[k] * (n - k) / (k + 1) * p / (1 - p)
    total = fsum(masses)
    cumulative, result = 0.0, []
    for mass in masses:
        cumulative += mass / total
        result.append(min(1.0, cumulative))
    result[-1] = 1.0
    return tuple(result)


def simulate_protocol() -> dict:
    """Run only the already fixed count experiment; never read real results.

    A shared NULL count couples the two candidates within each game. These
    abstract IID binary tables need not be realizable by particular lottery
    ticket triples. They test inferential operating characteristics only.
    """
    protocol, rng = future_protocol(), Random(SIMULATION_SEED)
    keys = protocol["hypotheses"]
    cdfs: dict[tuple[int, float], tuple[float, ...]] = {}
    tail_cache: dict[tuple[int, int, float], float] = {}

    def draw(n: int, p: float) -> int:
        key = (n, p)
        if key not in cdfs:
            cdfs[key] = _binomial_cdf(n, p)
        return bisect_left(cdfs[key], rng.random())

    def tail(k: int, n: int, p: float) -> float:
        key = (k, n, p)
        if key not in tail_cache:
            tail_cache[key] = stats.binomial_upper_tail(k, n, p)
        return tail_cache[key]

    def estimate(count: int) -> dict:
        return {"count": count, "estimate": count / SIMULATION_REPLICATIONS,
                "mc_ci95_wilson": stats.wilson_interval(count, SIMULATION_REPLICATIONS)}

    def power_estimate(count: int, alternative: bool) -> dict:
        result = estimate(count)
        lower, upper = result["mc_ci95_wilson"]
        result["classification"] = (
            "NOT_APPLICABLE_FOR_TRUE_NULL" if not alternative
            else "PASS" if lower >= TARGET_POWER
            else "FAIL" if upper < TARGET_POWER
            else "INCONCLUSIVE")
        return result

    def fwer_estimate(count: int, has_true_nulls: bool) -> dict:
        result = estimate(count)
        lower, upper = result["mc_ci95_wilson"]
        result["classification"] = (
            "NOT_APPLICABLE" if not has_true_nulls
            else "PASS_SPECIFIED_SYNTHETIC_LAW" if upper <= FAMILY_ALPHA
            else "FAIL" if lower > FAMILY_ALPHA
            else "INCONCLUSIVE")
        return result

    cells = []
    for scenario in JOINT_SCENARIOS:
        for configuration in NULL_CONFIGURATIONS:
            rejections, component_hits = [0] * 4, [[0, 0, 0] for _ in range(4)]
            family_any = false_any = 0
            for _ in range(SIMULATION_REPLICATIONS):
                pvalues = {}
                for game_index, game in enumerate(GAMES):
                    p0 = fair_p0(game)
                    n = protocol["games_planning"][game]["fixed_n"]
                    null_count = draw(n, p0)
                    for candidate_index in range(2):
                        index = 2 * game_index + candidate_index
                        p1 = p0 + configuration[index] * PLANNING_DELTA
                        joint = _joint(p0, p1, scenario)
                        both = draw(null_count, joint / p0)
                        wins = draw(n - null_count, (p1 - joint) / (1 - p0))
                        losses, hits = null_count - both, both + wins
                        analytic = tail(hits, n, p0)
                        paired = tail(wins, wins + losses, 0.5)
                        pvalues[keys[index]] = max(analytic, paired)
                        component_hits[index][0] += analytic <= FAMILY_ALPHA / 4
                        component_hits[index][1] += paired <= FAMILY_ALPHA / 4
                        component_hits[index][2] += max(analytic, paired) <= FAMILY_ALPHA / 4
                adjusted = stats.holm_adjust(pvalues)
                rejected = [adjusted[key] <= FAMILY_ALPHA for key in keys]
                for index, value in enumerate(rejected):
                    rejections[index] += value
                family_any += any(rejected)
                false_any += any(value and not configuration[index]
                                 for index, value in enumerate(rejected))
            cells.append({"scenario": scenario,
                          "alternative_configuration": list(configuration),
                          "family_any_rejection": estimate(family_any),
                          "true_null_fwer": fwer_estimate(false_any, not all(configuration)),
                          "hypotheses": {key: {
                              "true_delta": configuration[index] * PLANNING_DELTA,
                              "iut_holm_rejection": power_estimate(rejections[index], bool(configuration[index])),
                              "iut_at_bonferroni": power_estimate(component_hits[index][2], bool(configuration[index])),
                              "analytic_at_bonferroni": estimate(component_hits[index][0]),
                              "paired_at_bonferroni": estimate(component_hits[index][1]),
                          } for index, key in enumerate(keys)}})
            # CDFs depend on many random remaining counts; bound memory per cell.
            cdfs.clear()
    return {"schema": "V46_D2_SYNTHETIC_INFERENCE_OPERATING_CHARACTERISTICS_1",
            "seed": SIMULATION_SEED, "replications_per_cell": SIMULATION_REPLICATIONS,
            "cells": cells,
            "configuration_scope": "Four fixed configurations, not all sixteen; marginal MC intervals are not simultaneous",
            "scope": "SIMULATED_IID_BINARY_COUNTS_NOT_REAL_PREDICTIVE_EVIDENCE",
            "ci_gate_not_simulated": "Only the predeclared p-value IUT gate is simulated; no additional CI lower>0 or observed>=.01 gating",
            "no_candidate_outcomes_used": True,
            "formal_A": 0, "decision": "NO_EDGE"}
