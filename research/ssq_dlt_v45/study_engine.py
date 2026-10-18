"""D2-only chronological research replay with an isolated fixed candidate.

The five existing producers are reproduced without changing models.py.  Hot60
and pair counts roll forward, while EWMA retains models.py's exact summation
order.  Each prediction uses only the rows preceding its target row.  Historical
issue labels are retrospective labels: this module does not prove publication
availability, an official future target, trusted pre-draw freezing, or an edge.
"""
from __future__ import annotations

import hashlib
import itertools
from collections import Counter, deque
from pathlib import Path
from types import MappingProxyType

from . import models


CANDIDATE_MODEL = "R45-PAIR-RESIDUAL"
CANDIDATE_VERSION = "1.0.0"
WINDOW = 60
STUDY_MODEL_VERSIONS = MappingProxyType({
    **models.MODEL_VERSIONS, CANDIDATE_MODEL: CANDIDATE_VERSION,
})
MODEL_IDS = tuple(STUDY_MODEL_VERSIONS)
NULL_MODEL = models.NULL_MODEL
DEFAULT_SEED = models.DEFAULT_SEED


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def study_registry() -> dict:
    """Fresh research roster, fixed hypothesis and current source identities."""
    return {
        "schema": "ssq-dlt-v45-d2-study-registry-1",
        "scope": "RESEARCH_ONLY",
        "models": dict(STUDY_MODEL_VERSIONS),
        "existing_registry_sha256": models.REGISTRY_SHA256,
        "existing_model_source_sha256": models.source_sha256(),
        "study_engine_source_sha256": source_sha256(),
        "seed": DEFAULT_SEED,
        "candidate": {
            "model": CANDIDATE_MODEL,
            "version": CANDIDATE_VERSION,
            "window": WINDOW,
            "hypothesis": (
                "Removing marginal-frequency co-occurrence from last-60 pair "
                "counts improves future D2 full-hit rate against same-issue "
                "fixed-seed Random NULL. The hypothesis fails without an "
                "independent prospective improvement after multiplicity control."
            ),
            "score": "pair_count - count_a * count_b / observed_window_size",
            "observed_window_size": "min(60, training_size)",
            "comparison_implementation": (
                "Exact integer numerator pair_count * observed_window_size "
                "- count_a * count_b, since all candidate pairs share denominator"
            ),
            "ties": ["higher raw pair_count", "higher marginal sum", "ascending pair"],
            "parameters_tuned": False,
        },
        "target_labels": "RETROSPECTIVE_ISSUE_LABELS_ONLY",
        "asof_publication_verified": False,
        "formal_aliases": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
    }


def _validate_seed(seed: int) -> None:
    if type(seed) is not int or seed < 0:
        raise models.ModelBlocked("NONNEGATIVE_INTEGER_SEED_REQUIRED")


class _D2State:
    """Private prefix-only state; outcomes enter only after their prediction."""

    def __init__(self, game: str, maximum_size: int):
        self.game = game
        self.upper, self.front_count, _, _ = models.RULES[game]
        self.fronts: list[tuple[int, ...]] = []
        self.recent: deque[tuple[int, ...]] = deque()
        self.hot = [0.0] * (self.upper + 1)
        self.pair_counts: Counter = Counter()
        self.pairs = tuple(itertools.combinations(range(1, self.upper + 1), 2))
        # Reuse exactly the same weights and left-to-right cumulative sums as
        # models._scores.  An EWMA recurrence changes floating-point ties.
        self.weights = [2.0 ** (-age / 20.0) for age in range(maximum_size)]
        self.total_weights = [0.0]
        for weight in self.weights:
            self.total_weights.append(self.total_weights[-1] + weight)

    def append(self, row: dict) -> None:
        front = tuple(row["front"])
        self.fronts.append(front)
        self.recent.append(front)
        for number in front:
            self.hot[number] += 1
        self.pair_counts.update(itertools.combinations(sorted(front), 2))
        if len(self.recent) > WINDOW:
            old = self.recent.popleft()
            for number in old:
                self.hot[number] -= 1
            self.pair_counts.subtract(itertools.combinations(sorted(old), 2))

    def predict(self, issue: str, seed: int) -> dict[str, list[int]]:
        ewma = [0.0] * (self.upper + 1)
        for age, front in enumerate(reversed(self.fronts)):
            weight = self.weights[age]
            for number in front:
                ewma[number] += weight
        observed = len(self.recent)
        prior = 20.0 * self.front_count / self.upper
        total_weight = self.total_weights[len(self.fronts)]
        mix = [0.0] + [
            0.5 * (self.hot[n] + prior) / (observed + 20.0)
            + 0.5 * (ewma[n] + prior) / (total_weight + 20.0)
            for n in range(1, self.upper + 1)
        ]
        scores = {"R45-HOT60": self.hot, "R45-EWMA": ewma,
                  "R45-SHRINKMIX": mix}
        output = {
            name: sorted(sorted(range(1, self.upper + 1),
                                key=lambda n: (-score[n], n))[:2])
            for name, score in scores.items()
        }
        best_pair = min(self.pairs, key=lambda pair: (
            -self.pair_counts[pair], -sum(self.hot[n] for n in pair), pair))
        output[models.PRIMARY_MODEL] = list(best_pair)
        output[models.NULL_MODEL] = sorted(models._sample(
            seed, self.game, issue, models.NULL_MODEL, "dan", 2, self.upper))
        # Convert exact integral marginal counts from hot; a common denominator
        # allows integer comparison and preserves mathematical residual ties.
        candidate = min(self.pairs, key=lambda pair: (
            -(self.pair_counts[pair] * observed
              - int(self.hot[pair[0]]) * int(self.hot[pair[1]])),
            -self.pair_counts[pair], -sum(self.hot[n] for n in pair), pair))
        output[CANDIDATE_MODEL] = list(candidate)
        return output


def predict_d2_all(game: str, issue: str, history: list[dict],
                   seed: int = DEFAULT_SEED) -> dict[str, list[int]]:
    """Return one fixed pair per producer, using admitted supplied history only.

    Like models.generate, UNASSIGNED is permitted for a research preview; it
    cannot establish an official future issue or prospective admission.
    """
    models.validate_history(game, issue, history)
    _validate_seed(seed)
    state = _D2State(game, len(history))
    for row in history:
        state.append(row)
    return state.predict(issue, seed)


def walk_forward(game: str, history: list[dict], start: int = 120,
                 stop: int | None = None, *, seed: int = DEFAULT_SEED) -> list[dict]:
    """Replay targets [start, stop), training strictly on history[:index].

    The complete supplied archive is validated for numeric issue order and
    number legality. This validation is not a proof of source publication time
    or of complete official periods. No outcome enters producer state before
    its prediction. Input rows and returned rows share no mutable number lists.
    """
    models.validate_history(game, "UNASSIGNED", history)
    _validate_seed(seed)
    end = len(history) if stop is None else stop
    if (type(start) is not int or type(end) is not int
            or not 0 <= start <= end <= len(history)):
        raise models.ModelBlocked("INVALID_WALK_FORWARD_BOUNDS")
    state = _D2State(game, end)
    rows = []
    for index, draw in enumerate(history[:end]):
        if index >= start:
            predictions = state.predict(draw["issue"], seed)
            rows.append({
                "game": game,
                "issue": draw["issue"],
                "draw_date": draw.get("draw_date", draw.get("date")),
                "training_end_issue": history[index - 1]["issue"] if index else None,
                "training_size": index,
                "predictions": predictions,
                "draw_front": list(draw["front"]),
            })
        state.append(draw)
    return rows
