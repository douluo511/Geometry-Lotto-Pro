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
MIN_TRAIN = 240
MIN_OOS = 1200

CANDIDATE_CONFIGS = (
    ("full", None),
    ("remove_frequency", {"frequency": 0.0}),
    ("remove_transition", {"transition": 0.0}),
    ("remove_geometry", {"geometry": 0.0}),
    ("frequency_only", {"frequency": 1.0, "transition": 0.0, "geometry": 0.0, "stability": 0.0}),
)
ROBUST_WINDOW_SETS = {
    "default": DEFAULT_WINDOWS,
    "short": (5, 10, 20),
    "long": (20, 40, 80),
}
ROBUST_SEED_SETS = {
    "default": DEFAULT_SEEDS,
    "early": (11, 29, 47),
    "late": (83, 131, 197, 263),
}
INDEPENDENT_HOLDOUT_FRACTION = 1.0 / 3.0
LEAVE_ONE_PERIOD_OUT_COUNT = 6
REALITY_CHECK_REPS = 600


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
        support = 0
        for seed in seeds:
            jitter = (random.Random(_stable_seed(seed, issue, n)).random() - 0.5) * 0.006
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
    weights: dict[str, float] | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> list[dict]:
    rows = []
    for i in range(min_train, len(draws)):
        ranking = rank_prefix(draws, state, i, windows=windows, seeds=seeds, weights=weights)
        picks = [x["number"] for x in ranking[:PICK_SIZE]]
        hits = _hits(picks, draws[i])
        rows.append({"issue": draws[i].issue, "hits": hits, "excess": hits - RANDOM_EXPECTATION})
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


def era_means(rows: list[dict]) -> list[float]:
    if len(rows) < 6:
        return []
    cut = len(rows) // 3
    eras = [rows[:cut], rows[cut : cut * 2], rows[cut * 2 :]]
    return [_mean(x["excess"] for x in era) for era in eras]


def ablation(draws: list[Draw], state: PrefixState) -> list[dict]:
    configs = CANDIDATE_CONFIGS
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



def _holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        candidate = min(1.0, float(value) * (m - index))
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def _split_development_holdout(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    if len(rows) < 2:
        return list(rows), []
    holdout_n = max(1, int(math.ceil(len(rows) * INDEPENDENT_HOLDOUT_FRACTION)))
    holdout_n = min(holdout_n, len(rows) - 1)
    return rows[:-holdout_n], rows[-holdout_n:]


def _leave_one_period_out(rows: list[dict], periods: int = LEAVE_ONE_PERIOD_OUT_COUNT) -> dict:
    if periods < 2 or len(rows) < periods * 20:
        return {
            "status": "NOT VERIFIED",
            "periods": periods,
            "reason": "insufficient independent holdout rows",
        }
    windows = []
    for index in range(periods):
        start = index * len(rows) // periods
        stop = (index + 1) * len(rows) // periods
        chunk = rows[start:stop]
        values = [float(x["excess"]) for x in chunk]
        windows.append({
            "period": index + 1,
            "start_issue": chunk[0]["issue"],
            "end_issue": chunk[-1]["issue"],
            "n": len(chunk),
            "mean_excess": _mean(values),
        })
    return {
        "status": "PASS",
        "periods": periods,
        "windows": windows,
        "all_periods_positive": all(x["mean_excess"] > 0 for x in windows),
    }


def _reality_check(candidate_holdouts: dict[str, list[dict]]) -> dict:
    if not candidate_holdouts:
        return {"status": "NOT VERIFIED", "reason": "candidate holdout family is empty"}
    names = sorted(candidate_holdouts)
    issues = [[row["issue"] for row in candidate_holdouts[name]] for name in names]
    if not issues[0] or any(seq != issues[0] for seq in issues[1:]):
        return {"status": "NOT VERIFIED", "reason": "candidate holdouts are not issue-aligned"}
    series = {
        name: [float(row["excess"]) for row in candidate_holdouts[name]]
        for name in names
    }
    n = len(issues[0])
    if n < 60:
        return {"status": "NOT VERIFIED", "reason": "independent holdout too short for max-model null"}
    observed_means = {name: _mean(values) for name, values in series.items()}
    observed_max = max(observed_means.values())
    centered = {
        name: [value - observed_means[name] for value in values]
        for name, values in series.items()
    }
    block = 5
    starts = list(range(0, n - block + 1))
    rng = random.Random(_stable_seed("happy8", "reality-check", n))
    ge = 0
    for _ in range(REALITY_CHECK_REPS):
        indexes: list[int] = []
        while len(indexes) < n:
            start = starts[rng.randrange(len(starts))]
            indexes.extend(range(start, start + block))
        indexes = indexes[:n]
        null_max = max(
            _mean(centered[name][i] for i in indexes)
            for name in names
        )
        if null_max >= max(0.0, observed_max):
            ge += 1
    p_value = (ge + 1) / (REALITY_CHECK_REPS + 1)
    return {
        "status": "PASS",
        "method": "centered_moving_block_max_model_bootstrap",
        "candidate_count": len(names),
        "holdout_n": n,
        "block_length": block,
        "reps": REALITY_CHECK_REPS,
        "observed_candidate_means": observed_means,
        "observed_max_mean_excess": observed_max,
        "p_value": p_value,
        "significant_alpha_0_01": observed_max > 0 and p_value < 0.01,
    }


def _candidate_pool_validation(draws: list[Draw], state: PrefixState) -> dict:
    evaluations: dict[str, dict] = {}
    holdouts: dict[str, list[dict]] = {}
    raw_p: dict[str, float] = {}
    for name, weights in CANDIDATE_CONFIGS:
        rows = walk_forward(draws, state, weights=weights)
        development, holdout = _split_development_holdout(rows)
        holdout_values = [float(x["excess"]) for x in holdout]
        development_values = [float(x["excess"]) for x in development]
        p_value = sign_flip_p(
            holdout_values,
            seed=_stable_seed("candidate-holdout", name),
            reps=1200,
        ) if holdout_values else 1.0
        raw_p[name] = p_value
        holdouts[name] = holdout
        evaluations[name] = {
            "model": name,
            "weights": weights or "DEFAULT",
            "oos_n": len(rows),
            "development_n": len(development),
            "holdout_n": len(holdout),
            "development_mean_excess": _mean(development_values),
            "holdout_mean_excess": _mean(holdout_values),
            "holdout_bootstrap_lower": bootstrap_lower(
                holdout_values,
                seed=_stable_seed("candidate-bootstrap", name),
                reps=600,
            ),
            "holdout_signflip_p": p_value,
            "leave_one_period_out": _leave_one_period_out(holdout),
            "rows": rows,
        }

    selected = None
    selectable = [
        (name, item)
        for name, item in evaluations.items()
        if item["development_n"] > 0 and item["holdout_n"] > 0
    ]
    if selectable:
        selected = max(
            selectable,
            key=lambda pair: (pair[1]["development_mean_excess"], pair[0]),
        )[0]

    holm = _holm_adjust(raw_p)
    for name, adjusted in holm.items():
        evaluations[name]["holdout_holm_p"] = adjusted

    reality = _reality_check(holdouts)
    qualified = []
    if reality.get("status") == "PASS" and reality.get("significant_alpha_0_01") is True:
        for name, item in evaluations.items():
            lopo = item["leave_one_period_out"]
            if (
                item["holdout_mean_excess"] > 0
                and item["holdout_bootstrap_lower"] is not None
                and item["holdout_bootstrap_lower"] > 0
                and float(item.get("holdout_holm_p", 1.0)) < 0.01
                and lopo.get("status") == "PASS"
                and lopo.get("all_periods_positive") is True
            ):
                qualified.append(name)

    public = {}
    for name, item in evaluations.items():
        public[name] = {k: v for k, v in item.items() if k != "rows"}

    method_status = "PASS" if (
        len(evaluations) == len(CANDIDATE_CONFIGS)
        and selected is not None
        and reality.get("status") == "PASS"
        and all("holdout_holm_p" in item for item in evaluations.values())
        and all(item["leave_one_period_out"].get("status") == "PASS" for item in evaluations.values())
    ) else "NOT VERIFIED"
    return {
        "status": method_status,
        "selection_rule": "highest development mean excess; independent chronological final third is never used for selection",
        "selected_by_development": selected,
        "candidate_count": len(evaluations),
        "candidates": public,
        "holm_adjusted_holdout_p": holm,
        "reality_check": reality,
        "qualified_models": sorted(qualified),
        "selected_model_qualified": bool(selected and selected in qualified),
        "_rows": {name: item["rows"] for name, item in evaluations.items()},
    }


def _future_leakage_challenge(draws: list[Draw], state: PrefixState) -> dict:
    if len(draws) <= MIN_TRAIN + 2:
        return {"status": "NOT VERIFIED", "reason": "history too short for future-mutation challenge"}
    candidates = sorted({
        MIN_TRAIN,
        MIN_TRAIN + (len(draws) - MIN_TRAIN) // 2,
        len(draws) - 1,
    })
    checks = []
    for prefix_len in candidates:
        mutated = list(draws[:prefix_len])
        for offset, draw in enumerate(draws[prefix_len:]):
            shift = 17 + (offset % 11)
            numbers = [((int(n) - 1 + shift) % UNIVERSE) + 1 for n in draw.numbers]
            mutated.append(Draw.from_values(draw.issue, draw.draw_date, numbers))
        mutated_state = build_prefix_state(mutated)
        original_rank = rank_prefix(draws, state, prefix_len)
        mutated_rank = rank_prefix(mutated, mutated_state, prefix_len)
        original_signature = [
            (int(row["number"]), round(float(row["score"]), 14), int(row["rank"]))
            for row in original_rank
        ]
        mutated_signature = [
            (int(row["number"]), round(float(row["score"]), 14), int(row["rank"]))
            for row in mutated_rank
        ]
        checks.append({
            "prefix_len": prefix_len,
            "source_issue": draws[prefix_len - 1].issue,
            "future_rows_mutated": len(draws) - prefix_len,
            "ranking_unchanged": original_signature == mutated_signature,
        })
    return {
        "status": "PASS" if checks and all(x["ranking_unchanged"] for x in checks) else "FAIL",
        "challenge": "replace every future draw after each ranking prefix with a bijective number rotation",
        "checks": checks,
    }


def _window_seed_perturbation(draws: list[Draw], state: PrefixState) -> dict:
    available = len(draws) - MIN_TRAIN
    if available <= 0:
        return {"status": "NOT VERIFIED", "reason": "history too short for perturbation probes"}
    probe_count = min(18, available)
    if probe_count == 1:
        prefixes = [MIN_TRAIN]
    else:
        prefixes = sorted({
            MIN_TRAIN + i * (available - 1) // (probe_count - 1)
            for i in range(probe_count)
        })
    reference = {}
    for prefix in prefixes:
        ranking = rank_prefix(draws, state, prefix)
        reference[prefix] = {int(row["number"]) for row in ranking[:PICK_SIZE]}

    cases = []
    for window_name, windows in ROBUST_WINDOW_SETS.items():
        for seed_name, seeds in ROBUST_SEED_SETS.items():
            overlaps = []
            for prefix in prefixes:
                ranking = rank_prefix(
                    draws, state, prefix, windows=windows, seeds=seeds
                )
                picks = {int(row["number"]) for row in ranking[:PICK_SIZE]}
                overlaps.append(len(picks & reference[prefix]) / PICK_SIZE)
            cases.append({
                "window_set": window_name,
                "seed_set": seed_name,
                "windows": list(windows),
                "seeds": list(seeds),
                "probe_count": len(prefixes),
                "mean_top10_overlap_with_default": _mean(overlaps),
                "min_top10_overlap_with_default": min(overlaps) if overlaps else None,
            })
    expected = len(ROBUST_WINDOW_SETS) * len(ROBUST_SEED_SETS)
    complete = len(cases) == expected and all(
        math.isfinite(float(x["mean_top10_overlap_with_default"]))
        and math.isfinite(float(x["min_top10_overlap_with_default"]))
        for x in cases
    )
    return {
        "status": "PASS" if complete else "NOT VERIFIED",
        "scope": "sensitivity diagnostic only; overlap is not evidence of predictive edge",
        "prefixes": prefixes,
        "case_count": len(cases),
        "cases": cases,
    }


def validate_history(draws: list[Draw], *, canonical_hash: str) -> dict:
    if not draws:
        raise ValueError("scientific validation requires official history")
    for draw in draws:
        draw.validate()
    ordered = sorted(draws, key=lambda d: (d.draw_date, d.issue))
    if ordered != draws:
        raise ValueError("official history must be canonical chronological order")
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("duplicate issue in scientific history")
    if not canonical_hash or len(canonical_hash) != 64:
        raise ValueError("scientific validation requires the current canonical SHA-256")

    state = build_prefix_state(draws)
    candidate_validation = _candidate_pool_validation(draws, state)
    candidate_rows = candidate_validation.pop("_rows")
    selected_name = candidate_validation.get("selected_by_development")
    if selected_name and selected_name in candidate_rows:
        rows = candidate_rows[selected_name]
    else:
        rows = walk_forward(draws, state)

    excess = [float(x["excess"]) for x in rows]
    lower = bootstrap_lower(excess)
    p_value = sign_flip_p(excess)
    eras = era_means(rows)
    mean_excess = _mean(excess)
    leakage = _future_leakage_challenge(draws, state)
    perturbation = _window_seed_perturbation(draws, state)

    selected_candidate = (
        candidate_validation.get("candidates", {}).get(str(selected_name), {})
        if selected_name
        else {}
    )
    selected_lopo = selected_candidate.get("leave_one_period_out", {})
    reality = candidate_validation.get("reality_check", {})
    false_gain_elimination = "PASS" if (
        candidate_validation.get("status") == "PASS"
        and reality.get("status") == "PASS"
        and all(
            "holdout_holm_p" in item
            for item in candidate_validation.get("candidates", {}).values()
        )
    ) else "NOT VERIFIED"

    gates = {
        "data_integrity": "PASS",
        "sample_size": "PASS" if len(draws) >= MIN_TRAIN + MIN_OOS else "FAIL",
        "oos_size": "PASS" if len(rows) >= MIN_OOS else "FAIL",
        "candidate_pool_independent_validation": candidate_validation.get("status", "NOT VERIFIED"),
        "multi_window_multi_seed": perturbation.get("status", "NOT VERIFIED"),
        "reality_check_max_model_null": reality.get("status", "NOT VERIFIED"),
        "holm_multiple_testing": "PASS" if candidate_validation.get("holm_adjusted_holdout_p") else "NOT VERIFIED",
        "leave_one_period_out": selected_lopo.get("status", "NOT VERIFIED"),
        "leakage_future_mutation": leakage.get("status", "NOT VERIFIED"),
        "false_gain_elimination": false_gain_elimination,
        # Legacy edge diagnostics remain visible but never substitute for the
        # corrected candidate-family/holdout decision above.
        "excess_positive": "PASS" if mean_excess >= 0.15 else "FAIL",
        "bootstrap_lower_positive": "PASS" if lower is not None and lower > 0 else "FAIL",
        "permutation_signflip_alpha_0_01": "PASS" if p_value < 0.01 else "FAIL",
        "leave_one_era_out": "PASS" if len(eras) == 3 and all(x > 0 for x in eras) else "FAIL",
        "leakage_sentinel": leakage.get("status", "NOT VERIFIED"),
        "prospective": "PENDING",
    }

    selected_qualified = candidate_validation.get("selected_model_qualified") is True
    methodological_keys = (
        "candidate_pool_independent_validation",
        "multi_window_multi_seed",
        "reality_check_max_model_null",
        "holm_multiple_testing",
        "leave_one_period_out",
        "leakage_future_mutation",
        "false_gain_elimination",
    )
    methodology_complete = all(gates[k] == "PASS" for k in methodological_keys)
    pre_prospective_edge = selected_qualified and methodology_complete
    edge_pass = pre_prospective_edge and gates["prospective"] == "PASS"

    selected_weights = None
    for name, weights in CANDIDATE_CONFIGS:
        if name == selected_name:
            selected_weights = weights
            break
    current = rank_prefix(draws, state, len(draws), weights=selected_weights)
    candidate10 = sorted(x["number"] for x in current[:PICK_SIZE])
    result = {
        "schema": "happy8-scientific-validation-v2",
        "status": "PASS",
        "software_verdict": "PASS" if methodology_complete or len(draws) < MIN_TRAIN + MIN_OOS else "FAIL",
        "canonical_hash": canonical_hash,
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "baseline": {
            "single_number_probability": DRAW_SIZE / UNIVERSE,
            "pick10_expected_hits": RANDOM_EXPECTATION,
        },
        "oos": {
            "selected_model": selected_name,
            "n": len(rows),
            "mean_hits": _mean(x["hits"] for x in rows),
            "mean_excess": mean_excess,
            "bootstrap_95_lower": lower,
            "signflip_p": p_value,
            "era_excess": eras,
        },
        "gates": gates,
        "candidate_pool": candidate_validation,
        "multi_window_seed_robustness": perturbation,
        "leakage_challenge": leakage,
        "pre_prospective_edge_qualified": pre_prospective_edge,
        "edge_state": "VALIDATED_EDGE" if edge_pass else "NO_EDGE",
        "dan_state": "VALIDATED_DAN" if edge_pass else "NULL_DAN",
        "production_model": str(selected_name) if edge_pass else "uniform_baseline",
        "candidate10_research_only": candidate10,
        "formal_dan": candidate10[:4] if edge_pass else [],
        "note": (
            "Frozen candidate pool is selected on development OOS only, then independently "
            "tested on the chronological final-third holdout with dependence-aware max-model "
            "Reality Check, Holm correction, leave-one-period-out, future-mutation leakage "
            "challenge and window/seed sensitivity diagnostics. Prospective remains PENDING, "
            "so no production edge/dan is certified."
        ),
    }
    # Backward-compatible ablation surface, now derived from the same frozen
    # candidate family instead of rerunning an untracked denominator.
    result["ablations"] = [
        {
            "model": name,
            "oos_n": item.get("oos_n"),
            "mean_excess": _mean(float(x["excess"]) for x in candidate_rows.get(name, [])),
            "bootstrap_lower": bootstrap_lower(
                [float(x["excess"]) for x in candidate_rows.get(name, [])],
                seed=_stable_seed("ablation", name),
                reps=400,
            ) if candidate_rows.get(name) else None,
        }
        for name, item in candidate_validation.get("candidates", {}).items()
    ]
    if not edge_pass and result["formal_dan"]:
        raise AssertionError("NO_EDGE must not emit formal dan")
    return result

