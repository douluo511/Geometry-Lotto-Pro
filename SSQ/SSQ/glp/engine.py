from __future__ import annotations

import heapq
import itertools
import math
import random
from collections import Counter, defaultdict
from typing import Iterable

from glp.constants import (
    BACK_MAX, BACK_PICK, FRONT_MAX, FRONT_PICK, MODEL_VERSION,
    PROMOTION_POLICY, SELECTOR_VERSION,
)
from glp.domain import Draw, Prediction, Ranking
from glp.util import sha256_json, utc_now


def _area(draw: Draw, name: str) -> tuple[int, ...]:
    return tuple(draw.front if name == "front" else draw.back)


def _universe(area: str) -> range:
    return range(1, (FRONT_MAX if area == "front" else BACK_MAX) + 1)


def _pick(area: str) -> int:
    return FRONT_PICK if area == "front" else BACK_PICK


def _zmap(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    xs = list(values.values())
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / max(1, len(xs))
    sd = math.sqrt(var) or 1.0
    return {k: (v - mean) / sd for k, v in values.items()}


def _rank_from_scores(scores: dict[int, float], seed: int = 0) -> list[int]:
    # Deterministic micro-jitter only breaks exact ties; it cannot create signal.
    rng = random.Random(seed)
    jitter = {n: rng.random() * 1e-12 for n in scores}
    return sorted(scores, key=lambda n: (scores[n] + jitter[n], -n), reverse=True)


def feature_vectors(draws: list[Draw], area: str, window: int = 120) -> dict[str, dict[int, float]]:
    """Compute only past-looking features for the next draw.

    Geometry is a first-class path here, not merely a combination penalty:
    geometry_state measures local spatial occupancy on the number line, while
    geometry_transition estimates how prior geometry states transition into
    next-draw membership.
    """
    nums = list(_universe(area))
    if not draws:
        return {k: {n: 0.0 for n in nums} for k in (
            "frequency", "recency", "gap", "transition", "pair_graph",
            "geometry_state", "geometry_transition",
        )}

    hist = draws[-max(1, window):]
    # All features are deliberately bounded to a frozen lookback. This keeps
    # walk-forward cost linear in evaluation count instead of quadratic in the
    # full history length, while remaining strictly past-only.
    scan = draws[-max(240, window):]
    recent30 = draws[-min(30, len(draws)):]
    recent120 = draws[-min(120, len(draws)):]

    freq = Counter(n for d in hist for n in _area(d, area))
    freq30 = Counter(n for d in recent30 for n in _area(d, area))
    freq120 = Counter(n for d in recent120 for n in _area(d, area))

    # Recency/gap in one reverse scan (strictly past-only).
    last_seen: dict[int, int] = {}
    for age, d in enumerate(reversed(scan), start=1):
        for n in _area(d, area):
            if n not in last_seen:
                last_seen[n] = age
    gaps = {n: float(last_seen.get(n, len(scan) + 1)) for n in nums}
    recency = {n: 1.0 / gaps[n] for n in nums}

    # Transition from the most recent draw to historical following draws.
    transition_counts = Counter()
    transition_exposure = 0
    anchor = set(_area(draws[-1], area))
    for i in range(1, len(scan)):
        if anchor.intersection(_area(scan[i - 1], area)):
            transition_counts.update(_area(scan[i], area))
            transition_exposure += 1
    transition = {n: transition_counts[n] / max(1, transition_exposure) for n in nums}

    # Pair graph: how strongly each number co-occurs with numbers in the latest draw.
    pair_counts = defaultdict(float)
    pair_exposure = defaultdict(float)
    for d in hist:
        vals = tuple(_area(d, area))
        for a, b in itertools.combinations(vals, 2):
            pair_counts[(min(a, b), max(a, b))] += 1.0
        for n in vals:
            pair_exposure[n] += 1.0
    pair_graph = {}
    for n in nums:
        score = 0.0
        for a in anchor:
            if a == n:
                continue
            score += pair_counts[(min(a, n), max(a, n))]
        pair_graph[n] = score / max(1.0, sum(pair_exposure[a] for a in anchor))

    # Geometry state computed in O(history * picks * radius), rather than
    # O(universe * history * picks), so the 1200+ walk-forward contract remains practical.
    radius = 3 if area == "front" else 2
    local_density = {n: 0.0 for n in nums}
    center_num = 0.0
    center_den = 0.0
    lo, hi = nums[0], nums[-1]
    for age, d in enumerate(reversed(hist), start=1):
        w = 1.0 / math.sqrt(age)
        vals = _area(d, area)
        for x in vals:
            for n in range(max(lo, x - radius), min(hi, x + radius) + 1):
                local_density[n] += w
        if vals:
            center_num += w * (sum(vals) / len(vals))
            center_den += w
    center_avg = center_num / center_den if center_den else 0.0
    geom_state = {n: local_density[n] + 0.35 / (1.0 + abs(n - center_avg)) for n in nums}

    # Geometry transition: match historical predecessor geometry to latest state,
    # then count which numbers appeared in the following draw.
    geom_transition_counts = Counter()
    geom_weight = 0.0
    latest_vals = tuple(sorted(anchor))
    latest_span = (max(latest_vals) - min(latest_vals)) if latest_vals else 0
    latest_center = (sum(latest_vals) / len(latest_vals)) if latest_vals else 0.0
    start = 1
    for i in range(start, len(scan)):
        prev = tuple(_area(scan[i - 1], area))
        if not prev:
            continue
        span = max(prev) - min(prev)
        center = sum(prev) / len(prev)
        dist = abs(span - latest_span) + 0.25 * abs(center - latest_center)
        w = 1.0 / (1.0 + dist)
        geom_transition_counts.update({n: w for n in _area(scan[i], area)})
        geom_weight += w
    geom_transition = {n: geom_transition_counts[n] / max(1e-9, geom_weight) for n in nums}

    # Long/short frequency is intentionally retained only as research evidence.
    frequency = {
        n: 0.65 * (freq[n] / max(1, len(hist)))
           + 0.20 * (freq30[n] / max(1, len(recent30)))
           + 0.15 * (freq120[n] / max(1, len(recent120)))
        for n in nums
    }

    return {
        "frequency": _zmap(frequency),
        "recency": _zmap(recency),
        "gap": _zmap(gaps),
        "transition": _zmap(transition),
        "pair_graph": _zmap(pair_graph),
        "geometry_state": _zmap(geom_state),
        "geometry_transition": _zmap(geom_transition),
    }


MODEL_COMPONENTS = (
    "simple_frequency", "recency", "gap", "transition", "pair_graph",
    "geometry_state", "geometry_transition", "research_ensemble",
)


def model_scores_from_features(features: dict[str, dict[int, float]]) -> dict[str, dict[int, float]]:
    nums = sorted(next(iter(features.values())).keys())
    out: dict[str, dict[int, float]] = {}
    out["simple_frequency"] = dict(features["frequency"])
    out["recency"] = dict(features["recency"])
    # Gap is inverted: large gaps do not get privileged merely for being absent.
    out["gap"] = {n: -features["gap"][n] for n in nums}
    out["transition"] = dict(features["transition"])
    out["pair_graph"] = dict(features["pair_graph"])
    out["geometry_state"] = dict(features["geometry_state"])
    out["geometry_transition"] = dict(features["geometry_transition"])
    weights = {
        "simple_frequency": 0.16,
        "recency": 0.08,
        "gap": 0.06,
        "transition": 0.18,
        "pair_graph": 0.14,
        "geometry_state": 0.18,
        "geometry_transition": 0.20,
    }
    out["research_ensemble"] = {
        n: sum(weights[k] * out[k][n] for k in weights) for n in nums
    }
    return out


def individual_model_rankings(
    draws: list[Draw], area: str, window: int = 120, seed: int = 0
) -> dict[str, list[int]]:
    features = feature_vectors(draws, area, window=window)
    score_sets = model_scores_from_features(features)
    return {name: _rank_from_scores(scores, seed=seed) for name, scores in score_sets.items()}


def _deterministic_uniform_ranking(area: str, salt: str) -> list[int]:
    seed = int(sha256_json({"salt": salt, "area": area, "uniform": True})[:16], 16)
    vals = list(_universe(area))
    random.Random(seed).shuffle(vals)
    return vals


def score_complete_space(
    draws: list[Draw], area: str, window: int = 120, top_n: int = 20
) -> dict[str, object]:
    """Score the complete legal combination space for display/research only."""
    pick = _pick(area)
    universe = list(_universe(area))
    features = feature_vectors(draws, area, window=window)
    scores = model_scores_from_features(features)["research_ensemble"]
    if pick == 1:
        rows = [((n,), scores[n]) for n in universe]
        rows.sort(key=lambda x: x[1], reverse=True)
        return {"count": len(rows), "top": rows[:top_n]}

    heap: list[tuple[float, tuple[int, ...]]] = []
    count = 0
    for combo in itertools.combinations(universe, pick):
        count += 1
        base = sum(scores[n] for n in combo) / pick
        gaps = [b - a for a, b in zip(combo, combo[1:])]
        span = combo[-1] - combo[0]
        # Mild structural term; never granted production status unless evidence passes.
        geometry = -0.015 * abs(span - (FRONT_MAX if area == "front" else BACK_MAX) * 0.62)
        parity_penalty = -0.02 * abs(sum(n % 2 for n in combo) - pick / 2.0)
        spacing = -0.01 * (sum(abs(g - (sum(gaps) / len(gaps))) for g in gaps) if gaps else 0.0)
        value = base + geometry + parity_penalty + spacing
        item = (value, combo)
        if len(heap) < top_n:
            heapq.heappush(heap, item)
        elif value > heap[0][0]:
            heapq.heapreplace(heap, item)
    top = sorted(heap, reverse=True)
    return {"count": count, "top": [(combo, round(score, 8)) for score, combo in top]}


def model_identity() -> dict[str, object]:
    model_payload = {
        "version": MODEL_VERSION,
        "components": MODEL_COMPONENTS,
        "windows": PROMOTION_POLICY["windows"],
        "weights": "frozen-v8",
    }
    selector_payload = {
        "version": SELECTOR_VERSION,
        "policy": PROMOTION_POLICY,
        "states": ("NULL_DAN", "CERTIFIED_DAN"),
    }
    return {
        "model_version": MODEL_VERSION,
        "selector_version": SELECTOR_VERSION,
        "model_hash": sha256_json(model_payload),
        "selector_hash": sha256_json(selector_payload),
    }


def _next_target(draws: list[Draw]) -> tuple[str, str]:
    from datetime import datetime, timedelta
    latest = draws[-1]
    dt = datetime.strptime(latest.draw_date, "%Y-%m-%d").date()
    d = dt + timedelta(days=1)
    while d.weekday() not in (1, 3, 6):  # Tue / Thu / Sun
        d += timedelta(days=1)
    if d.year != dt.year:
        issue = f"{d.year}001"
    else:
        try:
            issue = str(int(latest.issue) + 1).zfill(len(latest.issue))
        except Exception:
            issue = latest.issue + "-NEXT"
    return issue, d.isoformat()


def _ranking_obj(ranked: list[int], scores: dict[int, float], features: dict[str, dict[int, float]]) -> Ranking:
    # Domain Ranking in the frozen baseline accepts these keyword fields.
    return Ranking(
        numbers=tuple(ranked),
        scores=tuple(float(scores[n]) for n in ranked),
        feature_scores={k: [float(v.get(n, 0.0)) for n in ranked] for k, v in features.items()},
    )


def make_prediction(
    draws: list[Draw],
    canonical_hash: str,
    evidence: dict[str, object] | None = None,
    formal: bool = True,
) -> tuple[Prediction, dict[str, object]]:
    if not draws:
        raise ValueError("no SSQ history")
    evidence = evidence or {}
    edge_state = str(evidence.get("edge_state", "NO_EDGE"))
    certified = str(evidence.get("dan_state", "NULL_DAN")) == "CERTIFIED_DAN"

    front_features = feature_vectors(draws, "front", window=120)
    back_features = feature_vectors(draws, "back", window=120)
    front_scores = model_scores_from_features(front_features)["research_ensemble"]
    back_scores = model_scores_from_features(back_features)["research_ensemble"]
    front_research = _rank_from_scores(front_scores, seed=17)
    back_research = _rank_from_scores(back_scores, seed=17)

    target_issue, target_date = _next_target(draws)
    identity = model_identity()

    if edge_state == "EDGE_PROVEN" and certified:
        front_rank = front_research
        back_rank = back_research
        production_weights = {"uniform_baseline": 0.0, "research_ensemble": 1.0}
    else:
        # Honest baseline: varies deterministically with the canonical context but
        # never claims a historical pattern is a calibrated winning probability.
        front_rank = _deterministic_uniform_ranking("front", canonical_hash + target_issue)
        back_rank = _deterministic_uniform_ranking("back", canonical_hash + target_issue)
        production_weights = {"uniform_baseline": 1.0, "research_ensemble": 0.0}

    front_rank_scores = {n: float(len(front_rank) - i) for i, n in enumerate(front_rank)}
    back_rank_scores = {n: float(len(back_rank) - i) for i, n in enumerate(back_rank)}
    front_obj = _ranking_obj(front_rank, front_rank_scores, front_features)
    back_obj = _ranking_obj(back_rank, back_rank_scores, back_features)

    court_hash = str(evidence.get("court_hash") or "")
    score_payload = {
        "canonical_hash": canonical_hash,
        "target_issue": target_issue,
        "front": front_rank,
        "back": back_rank,
        "edge_state": edge_state,
        "dan_state": "CERTIFIED_DAN" if certified else "NULL_DAN",
        "model_hash": identity["model_hash"],
        "selector_hash": identity["selector_hash"],
        "court_hash": court_hash,
        "production_weights": production_weights,
    }
    score_hash = sha256_json(score_payload)
    prediction_id = sha256_json({"score_hash": score_hash, "created_for": target_issue})[:32]

    # Freeze hash is a content hash over the immutable pre-draw payload.
    freeze_core = {
        "prediction_id": prediction_id,
        "target_issue": target_issue,
        "target_date": target_date,
        "canonical_hash": canonical_hash,
        "model_hash": identity["model_hash"],
        "selector_hash": identity["selector_hash"],
        "score_hash": score_hash,
        "edge_state": edge_state,
        "dan_state": "CERTIFIED_DAN" if certified else "NULL_DAN",
    }
    freeze_hash = sha256_json(freeze_core)

    pred = Prediction(
        prediction_id=prediction_id,
        target_issue=target_issue,
        target_date=target_date,
        created_at=utc_now(),
        front=list(front_rank[:FRONT_PICK]),
        back=list(back_rank[:BACK_PICK]),
        canonical_hash=canonical_hash,
        front_ranking=front_obj,
        back_ranking=back_obj,
        dan_state="CERTIFIED_DAN" if certified else "NULL_DAN",
        edge_state=edge_state,
        research_dan_front=tuple(front_research[:2]),
        research_dan_back=tuple(back_research[:1]),
        model_hash=str(identity["model_hash"]),
        selector_hash=str(identity["selector_hash"]),
        score_hash=score_hash,
        freeze_hash=freeze_hash,
        note=(
            "EDGE_PROVEN production ranking" if edge_state == "EDGE_PROVEN" and certified
            else "NO_EDGE/NULL_DAN: production ranking is an auditable uniform baseline; research ranking is isolated"
        ),
    )

    trace = {
        "schema": "effect-trace-v8",
        "canonical_hash": canonical_hash,
        "target_issue": target_issue,
        "model_hash": identity["model_hash"],
        "selector_hash": identity["selector_hash"],
        "score_hash": score_hash,
        "court_hash": court_hash,
        "production_weights": production_weights,
        "research_front_top": front_research[:12],
        "research_back_top": back_research[:8],
        "research_dan_front": front_research[:2],
        "research_dan_back": back_research[:1],
        "edge_state": edge_state,
        "dan_state": pred.dan_state,
        "formal": bool(formal),
        "complete_space": {
            "front_count": math.comb(FRONT_MAX, FRONT_PICK),
            "back_count": math.comb(BACK_MAX, BACK_PICK),
        },
    }
    trace["effect_trace_hash"] = sha256_json(trace)
    return pred, trace


def replay_prediction(prediction: Prediction, actual: Draw) -> dict[str, object]:
    front_rank = list(prediction.front_ranking.numbers)
    back_rank = list(prediction.back_ranking.numbers)
    actual_front = set(actual.front)
    actual_back = set(actual.back)
    top_front = set(front_rank[:FRONT_PICK])
    top_back = set(back_rank[:BACK_PICK])
    front_hits = len(top_front & actual_front)
    back_hits = len(top_back & actual_back)
    front_positions = {n: front_rank.index(n) + 1 for n in actual.front if n in front_rank}
    back_positions = {n: back_rank.index(n) + 1 for n in actual.back if n in back_rank}
    return {
        "prediction_id": prediction.prediction_id,
        "actual_issue": actual.issue,
        "actual_front": list(actual.front),
        "actual_back": list(actual.back),
        "front_hits": front_hits,
        "back_hits": back_hits,
        "winner_rank_front": front_positions,
        "winner_rank_back": back_positions,
        "research_dan_front_hits": len(set(prediction.research_dan_front) & actual_front),
        "research_dan_back_hits": len(set(prediction.research_dan_back) & actual_back),
        "immutable_freeze_hash": prediction.freeze_hash,
        "ranking_lineage_complete": bool(prediction.score_hash and prediction.model_hash and prediction.selector_hash),
    }
