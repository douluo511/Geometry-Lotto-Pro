from __future__ import annotations

import heapq
import itertools
import math
from collections import Counter, defaultdict
from typing import Iterable

from .constants import MODEL_VERSION, SELECTOR_VERSION, PROMOTION_POLICY
from .domain import Draw, Prediction, Ranking
from .util import next_draw_date, next_issue, parse_date, sha256_json, utc_now, zscores

BASE_MODELS = (
    "simple_frequency", "recency", "gap", "transition", "pair_graph",
    "geometry_state", "geometry_transition",
)
COMPLETE_SPACE_WEIGHTS = {"geometry_fit": 0.16, "pair_fit": 0.025}

ENSEMBLE_WEIGHTS = {
    "simple_frequency": 0.18,
    "recency": 0.12,
    "gap": 0.10,
    "transition": 0.15,
    "pair_graph": 0.10,
    "geometry_state": 0.17,
    "geometry_transition": 0.18,
}


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    return draw.front if area == "front" else draw.back


def _meta(area: str) -> tuple[int, int]:
    return (35, 5) if area == "front" else (12, 2)


def _zdict(raw: dict[int, float], max_n: int) -> dict[int, float]:
    vals = [raw.get(n, 0.0) for n in range(1, max_n + 1)]
    z = zscores(vals)
    return {n: z[n - 1] for n in range(1, max_n + 1)}


def _geometry_signature(nums: Iterable[int], max_n: int) -> tuple[float, float, float, float, float]:
    xs = sorted(float(n) / max_n for n in nums)
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    spread = math.sqrt(var)
    span = xs[-1] - xs[0]
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    center_balance = sum(-1.0 if x < 0.5 else 1.0 for x in xs) / len(xs)
    return (mean, spread, span, mean_gap, center_balance)


def _sig_dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _weighted_frequency(draws: list[Draw], area: str, max_n: int, half_life: float = 40.0) -> dict[int, float]:
    raw = {n: 0.0 for n in range(1, max_n + 1)}
    for age, d in enumerate(reversed(draws)):
        w = math.exp(-math.log(2) * age / half_life)
        for n in _area(d, area):
            raw[n] += w
    return _zdict(raw, max_n)


def feature_vectors(draws: list[Draw], area: str) -> dict[str, dict[int, float]]:
    max_n, _pick = _meta(area)
    if not draws:
        return {k: {n: 0.0 for n in range(1, max_n + 1)} for k in (
            "frequency_30", "frequency_120", "recency", "gap", "transition", "pair_graph", "geometry_state", "geometry_transition"
        )}
    recent30 = draws[-30:]
    recent120 = draws[-120:]
    freq30 = Counter(n for d in recent30 for n in _area(d, area))
    freq120 = Counter(n for d in recent120 for n in _area(d, area))
    frequency_30 = _zdict({n: float(freq30[n]) for n in range(1, max_n + 1)}, max_n)
    frequency_120 = _zdict({n: float(freq120[n]) for n in range(1, max_n + 1)}, max_n)
    recency = _weighted_frequency(draws[-240:], area, max_n)

    # Gap is deliberately one candidate path, never assumed predictive.
    last_seen = {n: len(draws) for n in range(1, max_n + 1)}
    for age, d in enumerate(reversed(draws)):
        for n in _area(d, area):
            if last_seen[n] == len(draws):
                last_seen[n] = age
    gap = _zdict({n: float(last_seen[n]) for n in range(1, max_n + 1)}, max_n)

    # Cross-draw transition: P(next number | numbers in previous draw).
    trans_raw = {n: 0.0 for n in range(1, max_n + 1)}
    last = set(_area(draws[-1], area))
    for prev, nxt in zip(draws[-361:-1], draws[-360:]):
        prev_nums = set(_area(prev, area))
        overlap = len(prev_nums & last)
        if overlap:
            w = overlap / max(1, len(last))
            for n in _area(nxt, area):
                trans_raw[n] += w
    transition = _zdict(trans_raw, max_n)

    # Pair graph centrality. It is explicitly subject to ablation and may be DEAD_PATH.
    pair_counts: Counter[tuple[int, int]] = Counter()
    node = Counter()
    for d in draws[-360:]:
        nums = tuple(_area(d, area))
        for n in nums:
            node[n] += 1
        for a, b in itertools.combinations(nums, 2):
            pair_counts[tuple(sorted((a, b)))] += 1
    pair_raw = {}
    for n in range(1, max_n + 1):
        pair_raw[n] = sum(c / max(1.0, math.sqrt(node[n] * node[m])) for (a, b), c in pair_counts.items() for m in ([b] if a == n else ([a] if b == n else [])))
    pair_graph = _zdict(pair_raw, max_n)

    # Geometry transition: nearest historical previous-shape -> next-number density.
    window = draws[-361:]
    current_sig = _geometry_signature(_area(draws[-1], area), max_n)
    geo_transition_raw = {n: 0.0 for n in range(1, max_n + 1)}
    predicted_sig_acc = [0.0] * 5
    total_w = 0.0
    for prev, nxt in zip(window[:-1], window[1:]):
        s_prev = _geometry_signature(_area(prev, area), max_n)
        dist = _sig_dist(current_sig, s_prev)
        w = math.exp(-7.5 * dist)
        if w < 1e-5:
            continue
        total_w += w
        for n in _area(nxt, area):
            geo_transition_raw[n] += w
        s_next = _geometry_signature(_area(nxt, area), max_n)
        for j, x in enumerate(s_next):
            predicted_sig_acc[j] += w * x
    geometry_transition = _zdict(geo_transition_raw, max_n)

    # Geometry state: estimate the next geometric state first, then score numbers from
    # historical draws whose own state resembles that predicted state.
    if total_w > 0:
        predicted_sig = tuple(x / total_w for x in predicted_sig_acc)
    else:
        predicted_sig = current_sig
    geo_state_raw = {n: 0.0 for n in range(1, max_n + 1)}
    for d in draws[-360:]:
        sig = _geometry_signature(_area(d, area), max_n)
        w = math.exp(-8.0 * _sig_dist(predicted_sig, sig))
        for n in _area(d, area):
            geo_state_raw[n] += w
    geometry_state = _zdict(geo_state_raw, max_n)

    return {
        "frequency_30": frequency_30,
        "frequency_120": frequency_120,
        "recency": recency,
        "gap": gap,
        "transition": transition,
        "pair_graph": pair_graph,
        "geometry_state": geometry_state,
        "geometry_transition": geometry_transition,
    }


def individual_model_scores(draws: list[Draw], area: str) -> dict[str, dict[int, float]]:
    f = feature_vectors(draws, area)
    max_n, _ = _meta(area)
    scores: dict[str, dict[int, float]] = {
        "simple_frequency": f["frequency_120"],
        "recency": f["recency"],
        "gap": f["gap"],
        "transition": f["transition"],
        "pair_graph": f["pair_graph"],
        "geometry_state": f["geometry_state"],
        "geometry_transition": f["geometry_transition"],
    }
    ensemble = {n: sum(ENSEMBLE_WEIGHTS[m] * scores[m][n] for m in BASE_MODELS) for n in range(1, max_n + 1)}
    scores["research_ensemble"] = ensemble
    return scores


def ranking_from_scores(scores: dict[int, float]) -> list[int]:
    return sorted(scores, key=lambda n: (-scores[n], n))


def individual_model_rankings(draws: list[Draw], area: str) -> dict[str, list[int]]:
    return {m: ranking_from_scores(s) for m, s in individual_model_scores(draws, area).items()}


def ensemble_ranking_from_components(component_scores: dict[str, dict[int, float]], include: Iterable[str] | None = None, override: dict[str, dict[int, float]] | None = None) -> list[int]:
    include_set = set(include or BASE_MODELS)
    max_n = max(next(iter(component_scores.values())).keys())
    override = override or {}
    weights = {m: ENSEMBLE_WEIGHTS[m] for m in BASE_MODELS if m in include_set}
    total = sum(weights.values()) or 1.0
    result = {}
    for n in range(1, max_n + 1):
        result[n] = sum((weights[m] / total) * override.get(m, component_scores[m])[n] for m in weights)
    return ranking_from_scores(result)


def _predicted_geometry_signature(draws: list[Draw], area: str) -> tuple[float, ...]:
    max_n, _ = _meta(area)
    current = _geometry_signature(_area(draws[-1], area), max_n)
    candidates = []
    for prev, nxt in zip(draws[-241:-1], draws[-240:]):
        d = _sig_dist(current, _geometry_signature(_area(prev, area), max_n))
        w = math.exp(-7.5 * d)
        candidates.append((w, _geometry_signature(_area(nxt, area), max_n)))
    sw = sum(w for w, _ in candidates) or 1.0
    return tuple(sum(w * sig[j] for w, sig in candidates) / sw for j in range(5))


def _pair_counts(draws: list[Draw], area: str) -> Counter[tuple[int, int]]:
    counts: Counter[tuple[int, int]] = Counter()
    for d in draws[-240:]:
        for a, b in itertools.combinations(_area(d, area), 2):
            counts[tuple(sorted((a, b)))] += 1
    return counts


def score_complete_space(draws: list[Draw], area: str, enabled_models: Iterable[str] | None = None) -> Ranking:
    max_n, pick = _meta(area)
    model_scores = individual_model_scores(draws, area)
    include = [m for m in (enabled_models or BASE_MODELS) if m in BASE_MODELS]
    if not include:
        include = list(BASE_MODELS)
    weights = {m: ENSEMBLE_WEIGHTS[m] for m in include}
    sw = sum(weights.values()) or 1.0
    ind = {n: sum(weights[m] * model_scores[m][n] for m in include) / sw for n in range(1, max_n + 1)}

    # Expensive historical summaries are computed once; each combination is then O(pick^2).
    predicted_sig = _predicted_geometry_signature(draws, area)
    pair_counts = _pair_counts(draws, area)
    heap: list[tuple[float, tuple[int, ...]]] = []
    for combo in itertools.combinations(range(1, max_n + 1), pick):
        geometry_fit = -_sig_dist(_geometry_signature(combo, max_n), predicted_sig)
        pairs = list(itertools.combinations(combo, 2))
        pair_fit = sum(pair_counts[tuple(sorted(p))] for p in pairs) / max(1, len(pairs))
        score = sum(ind[n] for n in combo) + COMPLETE_SPACE_WEIGHTS["geometry_fit"] * geometry_fit + COMPLETE_SPACE_WEIGHTS["pair_fit"] * pair_fit
        item = (score, combo)
        if len(heap) < 20:
            heapq.heappush(heap, item)
        elif score > heap[0][0]:
            heapq.heapreplace(heap, item)
    best = max(heap)
    return Ranking(
        numbers=list(best[1]),
        scores={n: float(ind[n]) for n in ind},
        feature_scores={k: {n: float(v) for n, v in s.items()} for k, s in model_scores.items()},
    )

def model_identity() -> dict:
    model_spec = {
        "model_version": MODEL_VERSION,
        "selector_version": SELECTOR_VERSION,
        "base_models": BASE_MODELS,
        "ensemble_weights": ENSEMBLE_WEIGHTS,
        "complete_space_weights": COMPLETE_SPACE_WEIGHTS,
        "geometry": "state+cross-draw-transition",
    }
    return {
        "model_hash": sha256_json(model_spec),
        "selector_hash": sha256_json({"selector": SELECTOR_VERSION, "policy": PROMOTION_POLICY}),
        "production_weights": {"uniform_baseline": 1.0, "research_ensemble": 0.0},
        "spec": model_spec,
    }


def make_prediction(draws: list[Draw], canonical_hash: str, latest_court: dict | None = None):
    if len(draws) < 240:
        raise ValueError("至少需要 240 期已验证历史数据")
    court = latest_court or {}
    scientific_gate = court.get("scientific_gate") == "PASS" and court.get("software_verdict") == "PASS"
    edge_proven = scientific_gate and court.get("edge_gate") == "PASS" and court.get("edge_state") == "EDGE_PROVEN"
    dan_certified = edge_proven and court.get("dan_firewall", {}).get("decision") == "CERTIFIED_DAN"
    validated_raw = court.get("validated_components")
    if edge_proven:
        if not isinstance(validated_raw, list) or not validated_raw:
            raise ValueError("EDGE_PROVEN 缺少经过验证的组件，拒绝预测")
        unknown = [m for m in validated_raw if m not in BASE_MODELS]
        if unknown:
            raise ValueError(f"EDGE_PROVEN 包含未知验证组件: {unknown}")
        validated = list(validated_raw)
    else:
        validated = list(BASE_MODELS)

    front_rank = score_complete_space(draws, "front", validated if edge_proven else BASE_MODELS)
    back_rank = score_complete_space(draws, "back", validated if edge_proven else BASE_MODELS)
    front_order = ranking_from_scores(front_rank.scores)
    back_order = ranking_from_scores(back_rank.scores)
    ident = model_identity()
    if edge_proven:
        production_weights = {"uniform_baseline": 0.0, "research_ensemble": 1.0}
    else:
        production_weights = ident["production_weights"]
    target_issue = next_issue(draws[-1].issue, draws[-1].draw_date)
    target_date = next_draw_date(parse_date(draws[-1].draw_date)).isoformat()
    score_hash = sha256_json({"front": front_rank.scores, "back": back_rank.scores, "validated": validated})
    prediction_id = sha256_json({"canonical_hash": canonical_hash, "target_issue": target_issue, "model_hash": ident["model_hash"], "score_hash": score_hash})[:20]
    prediction = Prediction(
        prediction_id=prediction_id,
        target_issue=target_issue,
        target_date=target_date,
        created_at=utc_now(),
        front=sorted(front_rank.numbers),
        back=sorted(back_rank.numbers),
        front_ranking=front_order,
        back_ranking=back_order,
        dan_state="CERTIFIED_DAN" if dan_certified else "NULL_DAN",
        edge_state="EDGE_PROVEN" if edge_proven else "NO_EDGE",
        research_dan_front=front_order[:2],
        research_dan_back=back_order[:1],
        canonical_hash=canonical_hash,
        model_hash=ident["model_hash"],
        selector_hash=ident["selector_hash"],
        score_hash=score_hash,
        note="研究候选；只有严格证据门通过时才允许 EDGE_PROVEN/CERTIFIED_DAN。",
    )
    trace = {
        "complete_space": {"front": math.comb(35, 5), "back": math.comb(12, 2)},
        "production_weights": production_weights,
        "scientific_gate": court.get("scientific_gate", "UNKNOWN"),
        "edge_gate": court.get("edge_gate", "FAIL"),
        "validated_components": validated if edge_proven else [],
        "dead_paths": court.get("dead_paths", []),
        "model_hash": ident["model_hash"],
        "selector_hash": ident["selector_hash"],
    }
    return prediction, trace


def replay_prediction(prediction: Prediction, actual: Draw) -> dict:
    front_positions = {n: i + 1 for i, n in enumerate(prediction.front_ranking)}
    back_positions = {n: i + 1 for i, n in enumerate(prediction.back_ranking)}
    front_hits = sorted(set(prediction.front) & set(actual.front))
    back_hits = sorted(set(prediction.back) & set(actual.back))
    return {
        "prediction_id": prediction.prediction_id,
        "target_issue": prediction.target_issue,
        "actual_issue": actual.issue,
        "front_hits": front_hits,
        "back_hits": back_hits,
        "front_hit_count": len(front_hits),
        "back_hit_count": len(back_hits),
        "dan_front_hits": sorted(set(prediction.research_dan_front) & set(actual.front)),
        "dan_back_hits": sorted(set(prediction.research_dan_back) & set(actual.back)),
        "front_winner_ranks": {str(n): front_positions.get(n, 35) for n in actual.front},
        "back_winner_ranks": {str(n): back_positions.get(n, 12) for n in actual.back},
        "selector_hash": prediction.selector_hash,
        "freeze_hash": prediction.freeze_hash,
    }
