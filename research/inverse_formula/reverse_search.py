"""Reverse-search mathematical formulas against observed lottery outcomes.

Research only. A per-draw inverse formula is an *after-the-draw* identity:
its offsets are learned from the answer. Never treat its exact recovery as
a pre-draw prediction or automatically promote it to the V4.7 engine.

The independent walk-forward portion chooses formulas using earlier results
only; no target result enters the forecast call.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from research.inverse_formula.probe import (
    DLT, SSQ, Draw, Game, compare, load_history, normalize,
)

METHODS = (
    "previous_plus_offset",
    "previous_mirror_plus_offset",
    "previous_double_plus_offset",
    "two_back_plus_offset",
    "previous_two_sum_plus_offset",
    "issue_index_plus_offset",
)


@dataclass(frozen=True)
class ReverseFormula:
    method: str
    anchor_index: int
    front_offsets: tuple[int, ...]
    back_offsets: tuple[int, ...]


def _base(method: str, prefix: list[Draw], next_index: int,
          side: str) -> tuple[int, ...]:
    """Produce the *unshifted* vector using only data before next_index."""
    if next_index != len(prefix):
        raise ValueError("forecast requires an exact past-only prefix")
    if method not in METHODS:
        raise ValueError(f"unknown inverse formula: {method}")
    if len(prefix) < 2:
        raise ValueError("at least two past draws are required")

    previous = getattr(prefix[-1], side)
    earlier = getattr(prefix[-2], side)
    if method == "previous_plus_offset":
        return tuple(v - 1 for v in previous)
    if method == "previous_mirror_plus_offset":
        return tuple(-(v - 1) for v in previous)
    if method == "previous_double_plus_offset":
        return tuple(2 * (v - 1) for v in previous)
    if method == "two_back_plus_offset":
        return tuple(v - 1 for v in earlier)
    if method == "previous_two_sum_plus_offset":
        return tuple((a - 1) + (b - 1) for a, b in zip(previous, earlier))
    return tuple(next_index for _ in previous)


def reverse_fit(draws: list[Draw], game: Game, anchor_index: int,
                method: str) -> ReverseFormula:
    """Solve offsets using the actual anchor outcome: post-hoc ONLY."""
    if anchor_index < 2 or anchor_index >= len(draws):
        raise ValueError("anchor must have two earlier draws and an outcome")
    prefix = draws[:anchor_index]
    actual = draws[anchor_index]
    fb = _base(method, prefix, anchor_index, "front")
    bb = _base(method, prefix, anchor_index, "back")
    return ReverseFormula(
        method=method,
        anchor_index=anchor_index,
        front_offsets=tuple(((v - 1) - b) % game.front_max
                            for v, b in zip(actual.front, fb)),
        back_offsets=tuple(((v - 1) - b) % game.back_max
                           for v, b in zip(actual.back, bb)),
    )


def apply_formula(formula: ReverseFormula, prefix: list[Draw],
                  game: Game) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Predict the next ticket without reading its actual outcome."""
    index = len(prefix)
    fb = _base(formula.method, prefix, index, "front")
    bb = _base(formula.method, prefix, index, "back")
    front = [((b + d) % game.front_max) + 1
             for b, d in zip(fb, formula.front_offsets)]
    back = [((b + d) % game.back_max) + 1
            for b, d in zip(bb, formula.back_offsets)]
    if len(front) != game.front_pick or len(back) != game.back_pick:
        raise ValueError("invalid formula dimensions")
    return normalize(front, game.front_max), normalize(back, game.back_max)


def oracle_reconstruction(draws: list[Draw], game: Game) -> dict:
    """How many historical outcomes can be fitted AFTER viewing them?

    This is retrospective formula coverage, NOT a forecasting metric.
    """
    trials = exact = 0
    per_method = Counter()
    for anchor in range(2, len(draws)):
        for method in METHODS:
            formula = reverse_fit(draws, game, anchor, method)
            result = compare(apply_formula(formula, draws[:anchor], game),
                             draws[anchor])
            trials += 1
            exact += result["full"]
            per_method[method] += result["full"]
    return {
        "eligible_draws": len(draws) - 2,
        "formula_families": len(METHODS),
        "retrospective_fit_trials": trials,
        "retrospective_exact_matches": exact,
        "retrospective_exact_rate": exact / trials if trials else None,
        "exact_by_method": dict(per_method),
        "WARNING": "answer-derived parameters; not a prediction",
    }


def select_from_past(prefix: list[Draw], game: Game,
                     min_followups: int = 5,
                     max_anchor_age: int = 35) -> tuple[ReverseFormula, dict]:
    """Select one inverse formula without access to the next outcome.

    Every candidate was reverse-fitted to an earlier observed outcome.
    Ranking excludes that candidate's anchor and uses ONLY subsequent
    outcomes that were already known at the current decision time.
    """
    n = len(prefix)
    if n < min_followups + 3:
        raise ValueError("insufficient past observations for selection")

    best = None
    best_key = None
    best_stats = None
    last_anchor = n - min_followups - 1
    first_anchor = max(2, last_anchor - max_anchor_age + 1)
    for anchor in range(first_anchor, last_anchor + 1):
        followups = n - anchor - 1
        for method_order, method in enumerate(METHODS):
            formula = reverse_fit(prefix, game, anchor, method)
            full = d2 = front_hits = 0
            for i in range(anchor + 1, n):
                score = compare(apply_formula(formula, prefix[:i], game),
                                prefix[i])
                full += score["full"]
                d2 += score["d2"]
                front_hits += score["front_hits"]

            # Rational scores avoid floating point tie instability.
            # Selection statistics are in-sample; only the next period
            # counts as an out-of-sample result.
            rank = (full / followups, d2 / followups,
                    front_hits / followups, -method_order, -anchor)
            if best_key is None or rank > best_key:
                best_key = rank
                best = formula
                best_stats = {
                    "post_anchor_known_evaluations": followups,
                    "post_anchor_known_full": full,
                    "post_anchor_known_d2": d2,
                    "post_anchor_known_front_hits": front_hits,
                }
    if best is None or best_stats is None:
        raise AssertionError("no eligible formula")
    return best, best_stats


def walk_forward(draws: list[Draw], game: Game,
                 min_history: int = 30) -> dict:
    """Simulate one ticket for each target issue with a strict past cutoff."""
    if len(draws) <= min_history:
        raise ValueError("not enough draws for walk-forward test")
    outcomes = []
    for target_index in range(min_history, len(draws)):
        known = draws[:target_index]
        chosen, selection_stats = select_from_past(known, game)
        predicted = apply_formula(chosen, known, game)
        actual = draws[target_index]  # Used only AFTER prediction is fixed.
        score = compare(predicted, actual)
        outcomes.append({
            "issue": actual.issue,
            "asof_issue": known[-1].issue,
            "formula_anchor_issue": known[chosen.anchor_index].issue,
            "family": chosen.method,
            "prediction": {"front": predicted[0], "back": predicted[1]},
            "score": score,
            "selection_evidence": selection_stats,
        })
    return {
        "method": "rolling_one_step_past_only",
        "issue_range": [outcomes[0]["issue"], outcomes[-1]["issue"]],
        "evaluated_issues": len(outcomes),
        "exact_hits": sum(r["score"]["full"] for r in outcomes),
        "d2_hits": sum(r["score"]["d2"] for r in outcomes),
        "front_hits_total": sum(r["score"]["front_hits"] for r in outcomes),
        "back_hits_total": sum(r["score"]["back_hits"] for r in outcomes),
        "formula_families_selected": dict(Counter(r["family"] for r in outcomes)),
        "per_issue_audit": outcomes,
        "status": "RESEARCH_ONLY_NO_ESTABLISHED_EDGE",
    }


def experiment(path: Path, game: Game, min_history: int = 30) -> dict:
    draws, source_sha = load_history(path, game)
    return {
        "game": game.name,
        "source_sha256": source_sha,
        "history_issues": [draws[0].issue, draws[-1].issue],
        "inverse_after_outcome": oracle_reconstruction(draws, game),
        "pre_draw_simulated": walk_forward(draws, game, min_history),
        "future_edge_claim": "NONE",
        "formal_v47_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssq", type=Path,
                        default=Path(__file__).with_name("ssq_2026.txt"))
    parser.add_argument("--dlt", type=Path,
                        default=Path(__file__).with_name("dlt_2026.txt"))
    parser.add_argument("--min-history", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps({"experiments": [
        experiment(args.ssq, SSQ, args.min_history),
        experiment(args.dlt, DLT, args.min_history),
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
