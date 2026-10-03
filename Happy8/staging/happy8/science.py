from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Iterable

from .domain import Draw

UNIVERSE = 80
DRAW_SIZE = 20
PICK_SIZE = 10
RANDOM_EXPECTATION = PICK_SIZE * DRAW_SIZE / UNIVERSE
DEFAULT_WINDOWS = (5, 10, 20, 40, 80)
DEFAULT_SEEDS = (11, 29, 47, 83, 131, 197, 263)
WINDOW_PERTURBATIONS = (
    (5, 10, 20),
    (10, 20, 40),
    (20, 40, 80),
    (5, 20, 80),
)
SEED_PERTURBATIONS = (
    (11, 29, 47),
    (83, 131, 197),
    (263, 307, 401),
)
MIN_TRAIN = 240
MIN_OOS = 1200
LOPO_PERIODS = 6


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _stable_seed(*parts: object) -> int:
    raw = ":".join(str(x) for x in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


@dataclass(frozen=True)
class PrefixState:
    occurrence: list[list[int]]
    prev_seen: list[list[int]]
    stay_hit: list[list[int]]


def build_prefix_state(draws: list[Draw]) -> PrefixState:
    occurrence = [[0] * (UNIVERSE + 1)]
    prev_seen = [[0] * (UNIVERSE + 1)]
    stay_hit = [[0] * (UNIVERSE + 1)]
    for i, draw in enumerate(draws):
        occ = occurrence[-1].copy()
        for n in draw.numbers:
            occ[n] += 1
        occurrence.append(occ)

        ps = prev_seen[-1].copy()
        sh = stay_hit[-1].copy()
        if i > 0:
            current = set(draw.numbers)
            for n in draws[i - 1].numbers:
                ps[n] += 1
                if n in current:
                    sh[n] += 1
        prev_seen.append(ps)
        stay_hit.append(sh)
    return PrefixState(occurrence=occurrence, prev_seen=prev_seen, stay_hit=stay_hit)


def _frequency_signal(state: PrefixState, prefix_len: int, number: int, window: int) -> float:
    sample_len = min(window, prefix_len)
    if sample_len <= 0:
        return 0.0
    start = prefix_len - sample_len
    count = state.occurrence[prefix_len][number] - state.occurrence[start][number]
    shrink = sample_len / (sample_len + 40.0)
    return ((count / sample_len) - 0.25) * shrink


def _transition_signal(state: PrefixState, prefix_len: int, number: int) -> float:
    seen = state.prev_seen[prefix_len][number]
    hit = state.stay_hit[prefix_len][number]
    return (((hit + 5.0) / (seen + 20.0)) - 0.25) * (seen / (seen + 60.0))


def _geometry_signal(last_draw: Draw, number: int) -> float:
    bins = [0] * 8
    for n in last_draw.numbers:
        bins[(n - 1) // 10] += 1
    return (2.5 - bins[(number - 1) // 10]) / 80.0


def rank_prefix(
    draws: list[Draw],
    state: PrefixState,
    prefix_len: int,
    *,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    if prefix_len < 1 or prefix_len > len(draws):
        raise ValueError("invalid ranking prefix length")
    w = {"frequency": 0.62, "transition": 0.18, "geometry": 0.08, "stability": 0.12}
    if weights:
        w.update(weights)
    issue = draws[prefix_len - 1].issue
    last = draws[prefix_len - 1]
    rows: list[dict] = []
    for n in range(1, UNIVERSE + 1):
        fs = [_frequency_signal(state, prefix_len, n, window) for window in windows]
        avg = _mean(fs)
        consensus = sum(1 for x in fs if x > 0) / len(fs)
        std = math.sqrt(_mean((x - avg) ** 2 for x in fs))
        stability = 1.0 - min(1.0, std * 8.0)
        transition = _transition_signal(state, prefix_len, n)
        geometry = _geometry_signal(last, n)
        base = (
            w["frequency"] * avg
            + w["transition"] * transition
            + w["geometry"] * geometry
            + w["stability"] * (stability - 0.5) / 20.0
        )
        if base >= 0.003:
            support = len(seeds)
        elif base <= -0.003:
            support = 0
        else:
            support = 0
            denominator = float((1 << 64) - 1)
            for seed in seeds:
                unit = _stable_seed(seed, issue, n) / denominator
                jitter = (unit - 0.5) * 0.006
                if base + jitter > 0:
                    support += 1
        rows.append(
            {
                "number": n,
                "score": base,
                "consensus": consensus,
                "stability": stability,
                "seed_support": support / len(seeds),
                "frequency_signal": avg,
                "transition_signal": transition,
                "geometry_signal": geometry,
            }
        )
    rows.sort(key=lambda x: (-x["score"], -x["seed_support"], x["number"]))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def _hits(picks: list[int], draw: Draw) -> int:
    target = set(draw.numbers)
    return sum(1 for n in picks if n in target)


def walk_forward(
    draws: list[Draw],
    state: PrefixState,
    *,
    min_train: int = MIN_TRAIN,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    rows = []
    for i in range(min_train, len(draws)):
        ranking = rank_prefix(
            draws,
            state,
            i,
            windows=windows,
            seeds=seeds,
            weights=weights,
        )
        picks = [x["number"] for x in ranking[:PICK_SIZE]]
        hits = _hits(picks, draws[i])
        rows.append(
            {
                "issue": draws[i].issue,
                "draw_date": draws[i].draw_date,
                "hits": hits,
                "excess": hits - RANDOM_EXPECTATION,
            }
        )
    return rows


def bootstrap_lower(values: list[float], *, seed: int = 20260920, reps: int = 1000) -> float | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(reps):
        samples.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    samples.sort()
    return samples[int(reps * 0.025)]


def sign_flip_p(values: list[float], *, seed: int = 90210, reps: int = 2000) -> float:
    if not values:
        return 1.0
    observed = _mean(values)
    rng = random.Random(seed)
    ge = 0
    for _ in range(reps):
        trial = sum(v if rng.random() >= 0.5 else -v for v in values) / len(values)
        if trial >= observed:
            ge += 1
    return (ge + 1) / (reps + 1)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, p_value) in enumerate(ordered):
        raw = min(1.0, max(0.0, float(p_value)) * (m - index))
        running = max(running, raw)
        adjusted[name] = min(1.0, running)
    return adjusted


def max_model_reality_check(
    series: dict[str, list[float]],
    *,
    seed: int = 515151,
    reps: int = 1200,
) -> dict:
    if not series:
        raise ValueError("reality check requires candidate model series")
    lengths = {len(values) for values in series.values()}
    if len(lengths) != 1 or 0 in lengths:
        raise ValueError("candidate model series must be aligned and non-empty")
    n = next(iter(lengths))
    observed_means = {name: _mean(values) for name, values in series.items()}
    observed_max = max(observed_means.values())
    if observed_max <= 0:
        return {
            "reps": reps,
            "observed_max_mean_excess": observed_max,
            "p_value": 1.0,
        }
    rng = random.Random(seed)
    ge = 0
    names = sorted(series)
    for _ in range(reps):
        signs = [1.0 if rng.random() >= 0.5 else -1.0 for _ in range(n)]
        trial_max = max(
            sum(value * signs[i] for i, value in enumerate(series[name])) / n
            for name in names
        )
        if trial_max >= observed_max:
            ge += 1
    return {
        "reps": reps,
        "observed_max_mean_excess": observed_max,
        "p_value": (ge + 1) / (reps + 1),
    }


def era_means(rows: list[dict]) -> list[float]:
    if len(rows) < 6:
        return []
    cut = len(rows) // 3
    eras = [rows[:cut], rows[cut : cut * 2], rows[cut * 2 :]]
    return [_mean(x["excess"] for x in era) for era in eras]


def _model_configs() -> list[tuple[str, dict[str, float] | None]]:
    return [
        ("full", None),
        ("frequency_only", {"frequency": 1.0, "transition": 0.0, "geometry": 0.0, "stability": 0.0}),
        ("transition_only", {"frequency": 0.0, "transition": 1.0, "geometry": 0.0, "stability": 0.0}),
        ("geometry_only", {"frequency": 0.0, "transition": 0.0, "geometry": 1.0, "stability": 0.0}),
        ("remove_frequency", {"frequency": 0.0}),
        ("remove_transition", {"transition": 0.0}),
        ("remove_geometry", {"geometry": 0.0}),
    ]


def evaluate_candidate_pool(
    draws: list[Draw],
    state: PrefixState,
) -> tuple[list[dict], dict[str, list[float]], dict[str, list[dict]]]:
    reports: list[dict] = []
    series: dict[str, list[float]] = {}
    rows_by_model: dict[str, list[dict]] = {}
    for name, weights in _model_configs():
        rows = walk_forward(draws, state, weights=weights)
        excess = [row["excess"] for row in rows]
        p_value = sign_flip_p(excess, seed=_stable_seed("candidate", name), reps=1200)
        reports.append(
            {
                "model": name,
                "oos_n": len(rows),
                "mean_excess": _mean(excess),
                "bootstrap_lower": bootstrap_lower(
                    excess,
                    seed=_stable_seed("candidate-bootstrap", name),
                    reps=500,
                ),
                "signflip_p": p_value,
            }
        )
        series[name] = excess
        rows_by_model[name] = rows
    adjusted = holm_adjust({row["model"]: row["signflip_p"] for row in reports})
    for row in reports:
        row["holm_p"] = adjusted[row["model"]]
        row["qualified_without_prospective"] = bool(
            row["oos_n"] >= MIN_OOS
            and row["mean_excess"] >= 0.15
            and row["bootstrap_lower"] is not None
            and row["bootstrap_lower"] > 0
            and row["signflip_p"] < 0.01
            and row["holm_p"] < 0.05
        )
    return reports, series, rows_by_model


def perturbation_report(
    draws: list[Draw],
    state: PrefixState,
) -> dict:
    windows: list[dict] = []
    for group in WINDOW_PERTURBATIONS:
        rows = walk_forward(draws, state, windows=group)
        excess = [row["excess"] for row in rows]
        windows.append(
            {
                "windows": list(group),
                "oos_n": len(rows),
                "mean_excess": _mean(excess),
                "bootstrap_lower": bootstrap_lower(
                    excess,
                    seed=_stable_seed("window", *group),
                    reps=300,
                ),
            }
        )
    seeds: list[dict] = []
    for group in SEED_PERTURBATIONS:
        rows = walk_forward(draws, state, seeds=group)
        excess = [row["excess"] for row in rows]
        seeds.append(
            {
                "seeds": list(group),
                "oos_n": len(rows),
                "mean_excess": _mean(excess),
                "bootstrap_lower": bootstrap_lower(
                    excess,
                    seed=_stable_seed("seed", *group),
                    reps=300,
                ),
            }
        )
    return {"windows": windows, "seeds": seeds}


def leave_one_period_out(
    candidate_series: dict[str, list[float]],
    rows_by_model: dict[str, list[dict]],
    *,
    periods: int = LOPO_PERIODS,
) -> list[dict]:
    if not candidate_series:
        return []
    names = sorted(candidate_series)
    n = len(candidate_series[names[0]])
    if n < periods * 2:
        return []
    if any(len(candidate_series[name]) != n for name in names):
        raise ValueError("unaligned candidate series")
    base_rows = rows_by_model[names[0]]
    fold_bounds = [(i * n // periods, (i + 1) * n // periods) for i in range(periods)]
    result = []
    all_indices = list(range(n))
    for fold, (start, end) in enumerate(fold_bounds, 1):
        holdout = set(range(start, end))
        train_indices = [i for i in all_indices if i not in holdout]
        train_means = {
            name: _mean(candidate_series[name][i] for i in train_indices)
            for name in names
        }
        selected = max(names, key=lambda name: (train_means[name], name))
        holdout_values = candidate_series[selected][start:end]
        result.append(
            {
                "period": fold,
                "start_issue": base_rows[start]["issue"],
                "end_issue": base_rows[end - 1]["issue"],
                "selected_model_without_period": selected,
                "training_mean_excess": train_means[selected],
                "holdout_mean_excess": _mean(holdout_values),
                "holdout_n": len(holdout_values),
            }
        )
    return result


def leakage_challenge(draws: list[Draw]) -> dict:
    if len(draws) <= MIN_TRAIN + 10:
        return {"status": "FAIL", "probes": [], "reason": "insufficient history"}
    probes = sorted(
        {
            MIN_TRAIN,
            MIN_TRAIN + (len(draws) - MIN_TRAIN) // 3,
            MIN_TRAIN + 2 * (len(draws) - MIN_TRAIN) // 3,
        }
    )
    results = []
    original_state = build_prefix_state(draws)
    for prefix_len in probes:
        original = rank_prefix(draws, original_state, prefix_len)
        mutated = list(draws)
        for i in range(prefix_len, len(mutated)):
            rotated = tuple(sorted((((n - 1 + 17) % UNIVERSE) + 1) for n in mutated[i].numbers))
            mutated[i] = Draw.from_values(mutated[i].issue, mutated[i].draw_date, rotated)
        mutated_state = build_prefix_state(mutated)
        challenged = rank_prefix(mutated, mutated_state, prefix_len)
        original_signature = [
            (row["number"], round(float(row["score"]), 14), round(float(row["seed_support"]), 14))
            for row in original
        ]
        challenged_signature = [
            (row["number"], round(float(row["score"]), 14), round(float(row["seed_support"]), 14))
            for row in challenged
        ]
        results.append(
            {
                "prefix_len": prefix_len,
                "issue": draws[prefix_len - 1].issue,
                "unchanged_after_future_mutation": original_signature == challenged_signature,
            }
        )
    status = "PASS" if results and all(row["unchanged_after_future_mutation"] for row in results) else "FAIL"
    return {
        "status": status,
        "challenge": "mutate only future draws; prefix ranking must remain byte-equivalent in ordered score signature",
        "probes": results,
    }


def ablation(draws: list[Draw], state: PrefixState) -> list[dict]:
    configs = [
        ("full", None),
        ("remove_frequency", {"frequency": 0.0}),
        ("remove_transition", {"transition": 0.0}),
        ("remove_geometry", {"geometry": 0.0}),
        ("frequency_only", {"frequency": 1.0, "transition": 0.0, "geometry": 0.0, "stability": 0.0}),
    ]
    result = []
    for name, weights in configs:
        rows = walk_forward(draws, state, weights=weights)
        excess = [x["excess"] for x in rows]
        result.append(
            {
                "model": name,
                "oos_n": len(rows),
                "mean_excess": _mean(excess),
                "bootstrap_lower": bootstrap_lower(excess, seed=_stable_seed("ablation", name), reps=400),
            }
        )
    return result


def validate_history(draws: list[Draw], *, canonical_hash: str) -> dict:
    if not draws:
        raise ValueError("scientific validation requires official history")
    if not canonical_hash or len(canonical_hash) < 32:
        raise ValueError("scientific validation requires canonical history hash")
    for draw in draws:
        draw.validate()
    ordered = sorted(draws, key=lambda d: (d.draw_date, d.issue))
    if ordered != draws:
        raise ValueError("official history must be canonical chronological order")
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("duplicate issue in scientific history")

    state = build_prefix_state(draws)
    rows = walk_forward(draws, state)
    excess = [x["excess"] for x in rows]
    lower = bootstrap_lower(excess)
    p_value = sign_flip_p(excess)
    eras = era_means(rows)
    ablations = ablation(draws, state)
    candidate_pool, candidate_series, rows_by_model = evaluate_candidate_pool(draws, state)
    perturbations = perturbation_report(draws, state)
    reality = max_model_reality_check(candidate_series)
    lopo = leave_one_period_out(candidate_series, rows_by_model)
    leakage = leakage_challenge(draws)
    mean_excess = _mean(excess)

    candidate_oos = {row["oos_n"] for row in candidate_pool}
    protocol_gates = {
        "candidate_pool_independent_validation": (
            "PASS" if len(candidate_pool) >= 7 and candidate_oos == {len(rows)} else "FAIL"
        ),
        "multi_window_perturbation": (
            "PASS"
            if len(perturbations["windows"]) == len(WINDOW_PERTURBATIONS)
            and all(row["oos_n"] == len(rows) for row in perturbations["windows"])
            else "FAIL"
        ),
        "multi_seed_perturbation": (
            "PASS"
            if len(perturbations["seeds"]) == len(SEED_PERTURBATIONS)
            and all(row["oos_n"] == len(rows) for row in perturbations["seeds"])
            else "FAIL"
        ),
        "reality_check_executed": (
            "PASS" if 0.0 <= float(reality["p_value"]) <= 1.0 and reality["reps"] >= 1000 else "FAIL"
        ),
        "holm_correction_executed": (
            "PASS"
            if candidate_pool and all(0.0 <= float(row["holm_p"]) <= 1.0 for row in candidate_pool)
            else "FAIL"
        ),
        "leave_one_period_out_executed": (
            "PASS" if len(lopo) == LOPO_PERIODS and all(row["holdout_n"] > 0 for row in lopo) else "FAIL"
        ),
        "leakage_challenge": leakage["status"],
        "canonical_hash_bound": "PASS",
    }
    software_verdict = "PASS" if all(value == "PASS" for value in protocol_gates.values()) else "FAIL"

    qualified_models = [
        row["model"] for row in candidate_pool if row["qualified_without_prospective"]
    ]
    champion = None
    if qualified_models:
        champion = max(
            qualified_models,
            key=lambda name: next(
                row["mean_excess"] for row in candidate_pool if row["model"] == name
            ),
        )

    window_positive = bool(
        perturbations["windows"] and all(row["mean_excess"] > 0 for row in perturbations["windows"])
    )
    seed_positive = bool(
        perturbations["seeds"] and all(row["mean_excess"] > 0 for row in perturbations["seeds"])
    )
    lopo_positive = bool(lopo and all(row["holdout_mean_excess"] > 0 for row in lopo))

    gates = {
        "data_integrity": "PASS",
        "sample_size": "PASS" if len(draws) >= MIN_TRAIN + MIN_OOS else "FAIL",
        "oos_size": "PASS" if len(rows) >= MIN_OOS else "FAIL",
        "excess_positive": "PASS" if mean_excess >= 0.15 else "FAIL",
        "bootstrap_lower_positive": "PASS" if lower is not None and lower > 0 else "FAIL",
        "permutation_signflip_alpha_0_01": "PASS" if p_value < 0.01 else "FAIL",
        "leave_one_era_out": "PASS" if len(eras) == 3 and all(x > 0 for x in eras) else "FAIL",
        "candidate_pool_has_qualified_model": "PASS" if qualified_models else "FAIL",
        "multi_window_robustness": "PASS" if window_positive else "FAIL",
        "multi_seed_robustness": "PASS" if seed_positive else "FAIL",
        "reality_check_alpha_0_05": "PASS" if float(reality["p_value"]) < 0.05 else "FAIL",
        "holm_alpha_0_05": (
            "PASS"
            if champion is not None
            and next(row["holm_p"] for row in candidate_pool if row["model"] == champion) < 0.05
            else "FAIL"
        ),
        "leave_one_period_out": "PASS" if lopo_positive else "FAIL",
        "leakage_sentinel": leakage["status"],
        "prospective": "PENDING",
    }
    edge_keys = (
        "sample_size",
        "oos_size",
        "excess_positive",
        "bootstrap_lower_positive",
        "permutation_signflip_alpha_0_01",
        "leave_one_era_out",
        "candidate_pool_has_qualified_model",
        "multi_window_robustness",
        "multi_seed_robustness",
        "reality_check_alpha_0_05",
        "holm_alpha_0_05",
        "leave_one_period_out",
        "leakage_sentinel",
    )
    edge_pass = (
        software_verdict == "PASS"
        and all(gates[k] == "PASS" for k in edge_keys)
        and gates["prospective"] == "PASS"
    )

    current = rank_prefix(draws, state, len(draws))
    candidate10 = sorted(x["number"] for x in current[:PICK_SIZE])
    result = {
        "schema": "happy8-scientific-validation-v2",
        "status": "PASS" if software_verdict == "PASS" else "FAIL",
        "software_verdict": software_verdict,
        "canonical_hash": canonical_hash,
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "baseline": {
            "single_number_probability": DRAW_SIZE / UNIVERSE,
            "pick10_expected_hits": RANDOM_EXPECTATION,
            "baseline_model": "uniform_random_without_replacement",
        },
        "oos": {
            "n": len(rows),
            "mean_hits": _mean(x["hits"] for x in rows),
            "mean_excess": mean_excess,
            "bootstrap_95_lower": lower,
            "signflip_p": p_value,
            "era_excess": eras,
        },
        "protocol_gates": protocol_gates,
        "gates": gates,
        "candidate_pool": candidate_pool,
        "qualified_models_without_prospective": qualified_models,
        "champion_without_prospective": champion,
        "reality_check": reality,
        "multiple_testing": {
            "method": "Holm",
            "family_size": len(candidate_pool),
            "adjusted_p": {row["model"]: row["holm_p"] for row in candidate_pool},
        },
        "perturbations": perturbations,
        "leave_one_period_out": lopo,
        "leakage_challenge": leakage,
        "ablations": ablations,
        "edge_state": "VALIDATED_EDGE" if edge_pass else "NO_EDGE",
        "dan_state": "VALIDATED_DAN" if edge_pass else "NULL_DAN",
        "production_model": champion if edge_pass and champion else "uniform_baseline",
        "candidate10_research_only": candidate10,
        "formal_dan": candidate10[:4] if edge_pass else [],
        "note": (
            "Scientific protocol includes explicit candidate-pool validation, multi-window and "
            "multi-seed perturbations, a max-model Reality Check, Holm correction, leave-one-period-out "
            "model-selection holdouts, and a future-mutation leakage challenge bound to the canonical hash. "
            "Prospective evidence remains PENDING, so no production edge/dan is certified."
        ),
    }
    if not edge_pass and result["formal_dan"]:
        raise AssertionError("NO_EDGE must not emit formal dan")
    return result
