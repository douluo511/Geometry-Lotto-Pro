from __future__ import annotations

import math
from dataclasses import dataclass

from .domain import Draw


FEATURE_NAMES = (
    "frequency_20_z",
    "frequency_60_z",
    "frequency_120_z",
    "ewma_120_z",
    "trend_20_120",
    "trend_20_60",
)

# Deliberately excluded from the default predictive feature vector.
# In particular, omission/gap is not treated as "overdue" evidence.
EXCLUDED_DEFAULT_FEATURES = (
    "gap",
    "recency",
    "transition",
    "pair_graph",
    "geometry_state",
    "geometry_transition",
    "parity",
    "zone_ratio",
    "sum_range",
    "ac_value",
    "span",
    "tail_pattern",
)

DEFAULT_DECAY = 0.97
DEFAULT_RIDGE_L2 = 1.0
DEFAULT_TRAIN_POINTS = 240


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    if area == "front":
        return draw.front
    if area == "back":
        return draw.back
    raise ValueError(f"unknown area: {area}")


def _meta(area: str) -> tuple[int, int]:
    if area == "front":
        return (33, 6)
    if area == "back":
        return (16, 1)
    raise ValueError(f"unknown area: {area}")


def uniform_marginal_probability(area: str) -> float:
    max_n, pick = _meta(area)
    return pick / max_n


def exact_two_dan_random_baseline() -> dict[str, float]:
    """Exact null distribution for two fixed red-ball dans under the SSQ game contract."""
    total = math.comb(33, 6)
    p0 = math.comb(31, 6) / total
    p1 = 2 * math.comb(31, 5) / total
    p2 = math.comb(31, 4) / total
    return {
        "zero_hits": p0,
        "one_hit": p1,
        "two_hits": p2,
        "at_least_one": p1 + p2,
    }


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-12), 1.0 - 1e-12)
    return math.log(p / (1.0 - p))


def _window_z(history: list[Draw], area: str, window: int) -> dict[int, float]:
    max_n, pick = _meta(area)
    use = history[-window:]
    n = len(use)
    if n <= 0:
        return {number: 0.0 for number in range(1, max_n + 1)}
    p0 = pick / max_n
    denom = math.sqrt(n * p0 * (1.0 - p0))
    counts = {number: 0 for number in range(1, max_n + 1)}
    for draw in use:
        for number in _area(draw, area):
            counts[number] += 1
    return {
        number: (counts[number] - n * p0) / denom
        for number in range(1, max_n + 1)
    }


def _ewma_z(
    history: list[Draw],
    area: str,
    window: int = 120,
    decay: float = DEFAULT_DECAY,
) -> dict[int, float]:
    if not (0.0 < decay <= 1.0):
        raise ValueError("decay must be in (0, 1]")
    max_n, pick = _meta(area)
    p0 = pick / max_n
    use = history[-window:]
    if not use:
        return {number: 0.0 for number in range(1, max_n + 1)}

    weights = [decay ** age for age in range(len(use))]
    denom = math.sqrt(p0 * (1.0 - p0) * sum(w * w for w in weights))
    reversed_draws = list(reversed(use))
    result: dict[int, float] = {}
    for number in range(1, max_n + 1):
        numerator = 0.0
        for age, draw in enumerate(reversed_draws):
            indicator = 1.0 if number in _area(draw, area) else 0.0
            numerator += weights[age] * (indicator - p0)
        result[number] = numerator / denom
    return result


def feature_map(
    history: list[Draw],
    area: str,
    decay: float = DEFAULT_DECAY,
) -> dict[int, tuple[float, ...]]:
    if len(history) < 120:
        raise ValueError("SSQ ridge multiscale candidate requires at least 120 historical draws")
    z20 = _window_z(history, area, 20)
    z60 = _window_z(history, area, 60)
    z120 = _window_z(history, area, 120)
    ewma = _ewma_z(history, area, 120, decay)
    max_n, _pick = _meta(area)
    return {
        number: (
            z20[number],
            z60[number],
            z120[number],
            ewma[number],
            z20[number] - z120[number],
            z20[number] - z60[number],
        )
        for number in range(1, max_n + 1)
    }


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    matrix = [list(row) + [float(rhs)] for row, rhs in zip(a, b)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            raise ValueError("ridge normal equation is singular")
        if pivot != col:
            matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        scale = matrix[col][col]
        matrix[col] = [value / scale for value in matrix[col]]
        for row in range(n):
            if row == col:
                continue
            factor = matrix[row][col]
            if abs(factor) <= 1e-18:
                continue
            matrix[row] = [
                matrix[row][j] - factor * matrix[col][j]
                for j in range(n + 1)
            ]
    return [matrix[i][-1] for i in range(n)]


def _fit_logistic_ridge(
    rows: list[tuple[tuple[float, ...], int]],
    baseline: float,
    l2: float,
    iterations: int = 12,
) -> list[float]:
    if l2 < 0.0:
        raise ValueError("l2 must be non-negative")
    if not rows:
        raise ValueError("no training rows")
    dimension = 1 + len(FEATURE_NAMES)
    beta = [_logit(baseline)] + [0.0] * (dimension - 1)
    for _ in range(iterations):
        lhs = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
        rhs = [0.0 for _ in range(dimension)]
        for features, target in rows:
            x = (1.0,) + tuple(float(v) for v in features)
            eta = sum(beta[j] * x[j] for j in range(dimension))
            p = _sigmoid(eta)
            weight = max(p * (1.0 - p), 1e-6)
            working = eta + (float(target) - p) / weight
            for j in range(dimension):
                rhs[j] += weight * x[j] * working
                for k in range(dimension):
                    lhs[j][k] += weight * x[j] * x[k]
        for j in range(1, dimension):
            lhs[j][j] += l2
        updated = _solve_linear(lhs, rhs)
        if max(abs(updated[j] - beta[j]) for j in range(dimension)) < 1e-9:
            beta = updated
            break
        beta = updated
    return beta


def _training_rows(
    draws: list[Draw],
    area: str,
    train_points: int,
    decay: float,
) -> list[tuple[tuple[float, ...], int]]:
    if train_points <= 0:
        raise ValueError("train_points must be positive")
    max_n, _pick = _meta(area)
    start = max(120, len(draws) - train_points)
    rows: list[tuple[tuple[float, ...], int]] = []
    for target_index in range(start, len(draws)):
        # Critical chronology rule: target draw is never included in its own features.
        history = draws[:target_index]
        features = feature_map(history, area, decay)
        actual = set(_area(draws[target_index], area))
        for number in range(1, max_n + 1):
            rows.append((features[number], 1 if number in actual else 0))
    if not rows:
        raise ValueError("insufficient history for ridge training rows")
    return rows


def _calibrate_logits_to_pick(logits: dict[int, float], pick: int) -> dict[int, float]:
    low = -30.0
    high = 30.0
    for _ in range(100):
        mid = (low + high) / 2.0
        total = sum(_sigmoid(value + mid) for value in logits.values())
        if total > pick:
            high = mid
        else:
            low = mid
    shift = (low + high) / 2.0
    return {number: _sigmoid(value + shift) for number, value in logits.items()}


@dataclass(frozen=True)
class RidgeMultiscaleResult:
    area: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    research_probabilities: dict[int, float]
    production_probabilities: dict[int, float]
    research_ranking: list[int]
    rho: float
    baseline_probability: float
    train_rows: int

    def to_dict(self) -> dict:
        return {
            "area": self.area,
            "feature_names": list(self.feature_names),
            "coefficients": list(self.coefficients),
            "research_probabilities": dict(self.research_probabilities),
            "production_probabilities": dict(self.production_probabilities),
            "research_ranking": list(self.research_ranking),
            "rho": self.rho,
            "baseline_probability": self.baseline_probability,
            "train_rows": self.train_rows,
        }


def fit_ridge_multiscale(
    draws: list[Draw],
    area: str,
    *,
    rho: float = 0.0,
    train_points: int = DEFAULT_TRAIN_POINTS,
    decay: float = DEFAULT_DECAY,
    l2: float = DEFAULT_RIDGE_L2,
) -> RidgeMultiscaleResult:
    """Research-only SSQ candidate behind a hard uniform-baseline shrink gate."""
    if len(draws) < 121:
        raise ValueError("SSQ ridge multiscale candidate requires at least 121 draws")
    if not (0.0 <= rho <= 1.0):
        raise ValueError("rho must be in [0, 1]")

    max_n, pick = _meta(area)
    p0 = pick / max_n
    rows = _training_rows(draws, area, train_points, decay)
    beta = _fit_logistic_ridge(rows, p0, l2)

    current = feature_map(draws, area, decay)
    logits = {
        number: beta[0] + sum(
            beta[j + 1] * current[number][j]
            for j in range(len(FEATURE_NAMES))
        )
        for number in range(1, max_n + 1)
    }
    research = _calibrate_logits_to_pick(logits, pick)
    production = {
        number: (1.0 - rho) * p0 + rho * research[number]
        for number in range(1, max_n + 1)
    }
    ranking = sorted(research, key=lambda n: (-research[n], n))
    return RidgeMultiscaleResult(
        area=area,
        feature_names=FEATURE_NAMES,
        coefficients=tuple(float(x) for x in beta),
        research_probabilities=research,
        production_probabilities=production,
        research_ranking=ranking,
        rho=float(rho),
        baseline_probability=float(p0),
        train_rows=len(rows),
    )


def research_two_dan_and_ticket(
    draws: list[Draw],
    *,
    rho: float = 0.0,
) -> dict[str, object]:
    """Return research ranking only; no production edge is implied or authorized."""
    front = fit_ridge_multiscale(draws, "front", rho=rho)
    back = fit_ridge_multiscale(draws, "back", rho=rho)
    return {
        "research_dan_front": list(front.research_ranking[:2]),
        "research_front": sorted(front.research_ranking[:6]),
        "research_back": list(back.research_ranking[:1]),
        "rho": float(rho),
        "production_edge_authorized": bool(rho > 0.0),
        "front_baseline_probability": front.baseline_probability,
        "back_baseline_probability": back.baseline_probability,
        "two_dan_random_baseline": exact_two_dan_random_baseline(),
    }
