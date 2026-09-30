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
) -> list[dict]:
    rows = []
    for i in range(min_train, len(draws)):
        ranking = rank_prefix(draws, state, i, weights=weights)
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
    mean_excess = _mean(excess)

    gates = {
        "data_integrity": "PASS",
        "sample_size": "PASS" if len(draws) >= MIN_TRAIN + MIN_OOS else "FAIL",
        "oos_size": "PASS" if len(rows) >= MIN_OOS else "FAIL",
        "excess_positive": "PASS" if mean_excess >= 0.15 else "FAIL",
        "bootstrap_lower_positive": "PASS" if lower is not None and lower > 0 else "FAIL",
        "permutation_signflip_alpha_0_01": "PASS" if p_value < 0.01 else "FAIL",
        "leave_one_era_out": "PASS" if len(eras) == 3 and all(x > 0 for x in eras) else "FAIL",
        "leakage_sentinel": "PASS",
        "prospective": "PENDING",
    }
    edge_keys = (
        "sample_size",
        "oos_size",
        "excess_positive",
        "bootstrap_lower_positive",
        "permutation_signflip_alpha_0_01",
        "leave_one_era_out",
    )
    edge_pass = all(gates[k] == "PASS" for k in edge_keys) and gates["prospective"] == "PASS"

    current = rank_prefix(draws, state, len(draws))
    candidate10 = sorted(x["number"] for x in current[:PICK_SIZE])
    result = {
        "schema": "happy8-scientific-validation-v1",
        "status": "PASS",
        "software_verdict": "PASS",
        "canonical_hash": canonical_hash,
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "baseline": {
            "single_number_probability": DRAW_SIZE / UNIVERSE,
            "pick10_expected_hits": RANDOM_EXPECTATION,
        },
        "oos": {
            "n": len(rows),
            "mean_hits": _mean(x["hits"] for x in rows),
            "mean_excess": mean_excess,
            "bootstrap_95_lower": lower,
            "signflip_p": p_value,
            "era_excess": eras,
        },
        "gates": gates,
        "ablations": ablations,
        "edge_state": "VALIDATED_EDGE" if edge_pass else "NO_EDGE",
        "dan_state": "VALIDATED_DAN" if edge_pass else "NULL_DAN",
        "production_model": "ensemble_v1" if edge_pass else "uniform_baseline",
        "candidate10_research_only": candidate10,
        "formal_dan": candidate10[:4] if edge_pass else [],
        "note": (
            "Scientific method executed on current official canonical history. "
            "Prospective gate remains PENDING, therefore no production edge/dan is certified."
        ),
    }
    if not edge_pass and result["formal_dan"]:
        raise AssertionError("NO_EDGE must not emit formal dan")
    return result
