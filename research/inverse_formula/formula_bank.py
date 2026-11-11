"""Research-only accumulating reverse-formula bank and audited voting ensemble.

A formula is created from a known draw, then evaluated strictly on later
draws. Scores from those later draws determine capped vote weights. Neither
the target draw nor any later result is used to produce its prediction.

Do not promote this exploratory mechanism to official V4.7 / fixed NULL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from research.inverse_formula.probe import (
    SSQ, DLT, Draw, Game, compare, load_history,
)
from research.inverse_formula.reverse_search import (
    METHODS, ReverseFormula, apply_formula, reverse_fit,
)

DEFAULT_LOOKBACK = 24
DEFAULT_MIN_FOLLOWUPS = 5
DEFAULT_MAX_PER_FAMILY = 2


def _canonical_hash(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _formula_id(formula: ReverseFormula, anchor_issue: int) -> str:
    return _canonical_hash({
        "anchor_issue": anchor_issue,
        "family": formula.method,
        "front_offsets": formula.front_offsets,
        "back_offsets": formula.back_offsets,
    })[:20]


def catalog(prefix: list[Draw], game: Game,
            lookback: int = DEFAULT_LOOKBACK,
            min_followups: int = DEFAULT_MIN_FOLLOWUPS) -> list[dict]:
    """Candidate formulas and performance data known at the cutoff only."""
    n = len(prefix)
    if min_followups < 1 or lookback < 1 or n < min_followups + 3:
        raise ValueError("insufficient history or invalid library settings")
    last_anchor = n - min_followups - 1
    first_anchor = max(2, last_anchor - lookback + 1)
    bank = []
    for anchor in range(first_anchor, last_anchor + 1):
        for method in METHODS:
            formula = reverse_fit(prefix, game, anchor, method)
            counts = Counter()
            for period in range(anchor + 1, n):
                score = compare(apply_formula(formula, prefix[:period], game),
                                prefix[period])
                counts.update(score)
            length = n - anchor - 1
            expected_front = length * (game.front_pick ** 2) / game.front_max
            expected_back = length * (game.back_pick ** 2) / game.back_max
            # Prespecified modest shrinkage: no performance score here is a
            # calibrated win probability; caps limit noisy formula domination.
            weight = 1.0
            weight += (counts["front_hits"] - expected_front) / (expected_front + 12)
            weight += 0.2 * ((counts["back_hits"] - expected_back) /
                              (expected_back + 12))
            weight = round(max(0.3, min(2.0, weight)), 8)
            bank.append({
                "formula_id": _formula_id(formula, prefix[anchor].issue),
                "formula": formula,
                "anchor_issue": prefix[anchor].issue,
                "family": method,
                "validated_issues": length,
                "validation_first_issue": prefix[anchor + 1].issue,
                "validation_last_issue": prefix[-1].issue,
                "validation_full_hits": counts["full"],
                "validation_front_hits": counts["front_hits"],
                "validation_back_hits": counts["back_hits"],
                "vote_weight": weight,
            })
    return bank


def _rank(bank: list[dict], max_per_family: int,
          top_k: int) -> list[dict]:
    if max_per_family < 1 or top_k < 1:
        raise ValueError("invalid ensemble capacity")
    ranked = sorted(bank,
                    key=lambda r: (-r["vote_weight"],
                                   -r["validated_issues"],
                                   r["family"],
                                   r["anchor_issue"],
                                   r["formula_id"]))
    selected = []
    use_count = Counter()
    for row in ranked:
        if use_count[row["family"]] >= max_per_family:
            continue
        selected.append(row)
        use_count[row["family"]] += 1
        if len(selected) >= top_k:
            break
    return selected


def predict_with_bank(prefix: list[Draw], game: Game, *,
                      lookback: int = DEFAULT_LOOKBACK,
                      min_followups: int = DEFAULT_MIN_FOLLOWUPS,
                      top_k: int = 12,
                      max_per_family: int = DEFAULT_MAX_PER_FAMILY) -> dict:
    """Callable per-period ensemble, returning a complete decision audit."""
    if not prefix:
        raise ValueError("empty history")
    bank = catalog(prefix, game, lookback, min_followups)
    selected = _rank(bank, max_per_family, top_k)
    front_votes: dict[int, float] = defaultdict(float)
    back_votes: dict[int, float] = defaultdict(float)
    chosen_rows = []
    for row in selected:
        front, back = apply_formula(row["formula"], prefix, game)
        for number in front:
            front_votes[number] += row["vote_weight"]
        for number in back:
            back_votes[number] += row["vote_weight"]
        chosen_rows.append({
            "formula_id": row["formula_id"],
            "anchor_issue": row["anchor_issue"],
            "family": row["family"],
            "formula_parameters": asdict(row["formula"]),
            "validated_issues": row["validated_issues"],
            "validation_first_issue": row["validation_first_issue"],
            "validation_last_issue": row["validation_last_issue"],
            "validation_full_hits": row["validation_full_hits"],
            "validation_front_hits": row["validation_front_hits"],
            "validation_back_hits": row["validation_back_hits"],
            "vote_weight": row["vote_weight"],
            "suggested_front": front,
            "suggested_back": back,
        })
    front_order = sorted(range(1, game.front_max + 1),
                         key=lambda num: (-front_votes[num], num))
    back_order = sorted(range(1, game.back_max + 1),
                        key=lambda num: (-back_votes[num], num))
    d2_pair = tuple(sorted(front_order[:2]))
    front = tuple(sorted(front_order[:game.front_pick]))
    back = tuple(sorted(back_order[:game.back_pick]))
    # Explicit D2 picks, not the numerically smallest 2 numbers in front.
    if not set(d2_pair).issubset(front):
        raise AssertionError("D2 must be included in the full ticket")
    audit = {
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "history_count": len(prefix),
        "candidate_count": len(bank),
        "candidate_families": list(METHODS),
        "selection_rule": {
            "top_k": top_k, "max_per_family": max_per_family,
            "lookback": lookback, "min_followups": min_followups,
            "weight": "capped, shrunk post-anchor accuracy; not win probability",
            "tie_break": "lower ball number",
        },
        "selected_formulas": chosen_rows,
        "prediction": {"front": front, "back": back, "d2_pair": d2_pair},
        "vote_ranking": {
            "front": [[num, round(front_votes[num], 8)] for num in front_order],
            "back": [[num, round(back_votes[num], 8)] for num in back_order],
        },
        "research_status": "NOT_PROSPECTIVELY_VALIDATED_NO_EDGE",
        "warning": "A historical answer-fitted library is not evidence of predictability.",
    }
    audit["decision_sha256"] = _canonical_hash(audit)
    return audit


def _research_null(issue: int, game: Game) -> tuple[
        tuple[tuple[int, ...], tuple[int, ...]], tuple[int, ...]]:
    """Issue-only control: no outcome object can enter the random selector.

    This research NULL remains separate from the frozen V4.7 Random NULL.
    """
    if type(issue) is not int or issue < 1:
        raise ValueError("research NULL requires a positive target issue")
    rng = random.Random(20261111 + 100000 * (1 if game.name == "SSQ" else 2)
                        + issue)
    pair = tuple(sorted(rng.sample(range(1, game.front_max + 1), 2)))
    remaining = [v for v in range(1, game.front_max + 1) if v not in pair]
    rest = rng.sample(remaining, game.front_pick - 2)
    front = tuple(sorted(pair + tuple(rest)))
    back = tuple(sorted(rng.sample(range(1, game.back_max + 1),
                                   game.back_pick)))
    return (front, back), pair


def walk_forward_bank(draws: list[Draw], game: Game, *,
                      start: int = 30, **config: int) -> dict:
    if start < 8 or start >= len(draws):
        raise ValueError("start must allow history and held-out targets")
    replay = []
    for index in range(start, len(draws)):
        # Every forecast includes at most draws[:index].
        decision = predict_with_bank(draws[:index], game, **config)
        # Both experiment and research control are FIXED before target is read.
        null_ticket, null_pair = _research_null(decision["target_issue"], game)
        actual = draws[index]
        p = decision["prediction"]
        ticket = (tuple(p["front"]), tuple(p["back"]))
        pair = tuple(p["d2_pair"])
        metric = compare(ticket, actual)
        d2 = int(set(pair).issubset(actual.front))
        null_metric = compare(null_ticket, actual)
        null_d2 = int(set(null_pair).issubset(actual.front))
        replay.append({
            "issue": actual.issue,
            "asof_issue": decision["asof_issue"],
            "prediction": p,
            "decision_sha256": decision["decision_sha256"],
            "selected_formula_ids": [r["formula_id"]
                                     for r in decision["selected_formulas"]],
            "formula_count": decision["candidate_count"],
            "full_hit": metric["full"],
            "d2_hit": d2,
            "front_hits": metric["front_hits"],
            "back_hits": metric["back_hits"],
            "research_null": {
                "prediction": {"front": null_ticket[0], "back": null_ticket[1],
                               "d2_pair": null_pair},
                "full_hit": null_metric["full"],
                "d2_hit": null_d2,
            },
        })
    n = len(replay)
    return {
        "game": game.name, "replay_start_issue": replay[0]["issue"],
        "replay_end_issue": replay[-1]["issue"],
        "evaluated_issues": n,
        "exact_hits": sum(r["full_hit"] for r in replay),
        "d2_hits": sum(r["d2_hit"] for r in replay),
        "d2_rate": sum(r["d2_hit"] for r in replay) / n,
        "research_null_d2_hits": sum(r["research_null"]["d2_hit"] for r in replay),
        "research_null_exact_hits": sum(r["research_null"]["full_hit"] for r in replay),
        "theoretical_d2_rate": (game.front_pick * (game.front_pick - 1)) /
                               (game.front_max * (game.front_max - 1)),
        "per_issue_audit": replay,
        "interpretation": "historical past-only replay, NOT registered future proof",
    }


def archive_all_observed_formulas(draws: list[Draw], game: Game) -> list[dict]:
    """Export every formula learned AFTER its anchor draw for future inspection.

    The research ensemble uses a bounded recency window, but the archive
    retains older answer-fitted formulas without overwriting their identity.
    """
    archived = []
    for anchor in range(2, len(draws)):
        for method in METHODS:
            formula = reverse_fit(draws, game, anchor, method)
            archived.append({
                "formula_id": _formula_id(formula, draws[anchor].issue),
                "anchor_issue": draws[anchor].issue,
                "created_after_issue_known": draws[anchor].issue,
                "family": method,
                "formula_parameters": asdict(formula),
                "original_reconstruction": {
                    "front": draws[anchor].front, "back": draws[anchor].back
                },
                "meaning": "posthoc_identity_not_forecast",
            })
    return archived


def report(path: Path, game: Game, **config: int) -> dict:
    draws, source_sha = load_history(path, game)
    archive = archive_all_observed_formulas(draws, game)
    return {
        "source_sha256": source_sha,
        "history_issues": [draws[0].issue, draws[-1].issue],
        "formula_archive_count": len(archive),
        "formula_archive": archive,
        "walk_forward": walk_forward_bank(draws, game, **config),
        "next_research_candidate": predict_with_bank(draws, game),
        "official_v47_modified": False,
        "research_status": "NO_EDGE_UNTIL_INDEPENDENT_VERIFICATION",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ssq", type=Path,
                    default=Path(__file__).with_name("ssq_2026.txt"))
    ap.add_argument("--dlt", type=Path,
                    default=Path(__file__).with_name("dlt_2026.txt"))
    ap.add_argument("--start", type=int, default=30)
    ap.add_argument("--out", type=Path,
                    help="optional JSON audit file, no formal ledger writes")
    args = ap.parse_args()
    results = {
        "ssq": report(args.ssq, SSQ, start=args.start),
        "dlt": report(args.dlt, DLT, start=args.start),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, ensure_ascii=False,
                                      indent=2), encoding="utf-8")
    print(json.dumps({
        name: {
            "source_sha256": value["source_sha256"],
            "walk_forward": {k: v for k, v in value["walk_forward"].items()
                             if k != "per_issue_audit"},
            "next_research_candidate": {
                "asof_issue": value["next_research_candidate"]["asof_issue"],
                "target_issue": value["next_research_candidate"]["target_issue"],
                "candidate_count": value["next_research_candidate"]["candidate_count"],
                "selected_formula_ids":
                    [r["formula_id"] for r in
                     value["next_research_candidate"]["selected_formulas"]],
                "prediction": value["next_research_candidate"]["prediction"],
                "decision_sha256":
                    value["next_research_candidate"]["decision_sha256"],
            },
        } for name, value in results.items()
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
