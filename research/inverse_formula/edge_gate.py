"""Strict exploratory edge audit: complete-ticket and D2 vs issue-only NULL.

Existing historical fixtures are not authenticated preregistered forecasts.
This module is a *falsification report*, not a prediction-promotion gate.
It NEVER edits formal V4.7, its frozen Random NULL, or an official ledger.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from research.inverse_formula.formula_bank import (
    _research_null, predict_with_bank, walk_forward_bank,
)
from research.inverse_formula.independent_experts import digest, wilson95
from research.inverse_formula.probe import DLT, SSQ, Draw, Game, compare, load_history


def exact_upper_tail(k: int, n: int, p: float) -> float:
    """One-sided exact Binomial tail, descriptive only for these explorations."""
    if type(n) is not int or type(k) is not int or n < 1 or not 0 <= k <= n:
        raise ValueError("invalid binomial trial counts")
    if type(p) not in (int, float) or not 0 <= p <= 1:
        raise ValueError("invalid binomial null probability")
    return min(1.0, math.fsum(math.comb(n, i) * (p ** i) *
                              ((1 - p) ** (n - i))
                              for i in range(k, n + 1)))


def _ticket(raw: dict, game: Game) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    if not isinstance(raw, dict) or set(raw) != {"front", "back", "d2_pair"}:
        raise ValueError("incomplete ticket/D2 choice")
    f, b, d2 = (tuple(raw[name]) for name in ("front", "back", "d2_pair"))
    for nums, count, maximum in (
        (f, game.front_pick, game.front_max),
        (b, game.back_pick, game.back_max),
        (d2, 2, game.front_max),
    ):
        if (len(nums) != count or tuple(sorted(set(nums))) != nums
                or any(type(num) is not int or num < 1 or num > maximum
                       for num in nums)):
            raise ValueError("illegal ticket or D2 pair")
    if not set(d2).issubset(f):
        raise ValueError("D2 pair outside complete ticket")
    return f, b, d2


def independent_score(draws: list[Draw], game: Game,
                      trials: list[dict], *, start: int) -> dict:
    """Recompute all scores against source data; no dropping the losing rows."""
    if start < 30 or len(draws) <= start or len(trials) != len(draws) - start:
        raise ValueError("missing, truncated, or impossible replay")
    if any(draws[i].issue != draws[i - 1].issue + 1
           for i in range(1, len(draws))):
        raise ValueError("duplicate, missing or unordered issue")
    pairs = []
    full = d2 = null_full = null_d2 = wins = losses = 0
    for index, trial in enumerate(trials, start=start):
        actual = draws[index]
        target = draws[index - 1].issue + 1
        if (actual.issue != target
                or trial.get("issue") != target
                or trial.get("asof_issue") != draws[index - 1].issue):
            raise ValueError("replay target/cutoff mismatch")
        f, b, pair = _ticket(trial["prediction"], game)
        n_f, n_b, n_pair = _ticket(trial["research_null"]["prediction"], game)
        expected_null, expected_pair = _research_null(target, game)
        if ((n_f, n_b), n_pair) != (expected_null, expected_pair):
            raise ValueError("research control changed or used future outcome")
        predicted = compare((f, b), actual)
        control = compare((n_f, n_b), actual)
        got_full = predicted["full"]
        got_d2 = int(set(pair).issubset(actual.front))
        got_null_full = control["full"]
        got_null_d2 = int(set(n_pair).issubset(actual.front))
        if (got_full != trial["full_hit"]
                or got_d2 != trial["d2_hit"]
                or got_null_full != trial["research_null"]["full_hit"]
                or got_null_d2 != trial["research_null"]["d2_hit"]):
            raise ValueError("outcome score or selected D2 pair was altered")
        full += got_full
        d2 += got_d2
        null_full += got_null_full
        null_d2 += got_null_d2
        wins += int(got_d2 == 1 and got_null_d2 == 0)
        losses += int(got_d2 == 0 and got_null_d2 == 1)
        pairs.append({
            "issue": target,
            "asof_issue": target - 1,
            "decision_sha256": trial["decision_sha256"],
            "full_hit": got_full, "d2_hit": got_d2,
            "research_null_full_hit": got_null_full,
            "research_null_d2_hit": got_null_d2,
        })
    n = len(pairs)
    d2_fair = math.comb(game.front_pick, 2) / math.comb(game.front_max, 2)
    ticket_space = (math.comb(game.front_max, game.front_pick) *
                    math.comb(game.back_max, game.back_pick))
    return {
        "game": game.name,
        "evaluated_issues": n,
        "replay_first_issue": pairs[0]["issue"],
        "replay_last_issue": pairs[-1]["issue"],
        "full_ticket": {
            "hits": full, "rate": full / n,
            "wilson95": wilson95(full, n),
            "fair_probability_per_ticket": 1 / ticket_space,
            "fair_outcome_space": ticket_space,
            "exact_one_sided_p_exploratory": exact_upper_tail(
                full, n, 1 / ticket_space),
        },
        "d2": {
            "hits": d2, "rate": d2 / n,
            "wilson95": wilson95(d2, n),
            "fair_probability_per_pair": d2_fair,
            "exact_one_sided_p_exploratory": exact_upper_tail(d2, n, d2_fair),
        },
        "research_null": {
            "d2_hits": null_d2, "full_ticket_hits": null_full,
            "research_null_only_not_fixed_v47": True,
        },
        "same_draw_paired_research_null": {
            "wins": wins, "losses": losses, "ties": n - wins - losses,
            "discordant": wins + losses,
            "exact_one_sided_p_exploratory": (
                exact_upper_tail(wins, wins + losses, 0.5)
                if wins + losses else 1.0
            ),
        },
        "per_issue_audit": pairs,
        "hypothesis_family_registration_verified": False,
        "multiple_testing_correction_authorized": False,
        "historical_training_formula_selection_is_exploratory": True,
        "external_source_authenticated": False,
        "external_pre_draw_timestamp_verified": False,
        "independent_prospective_draws": 0,
        "formal_v47_fixed_random_null_used": False,
        "formal_promotion_allowed": False,
        "status": "NO_EDGE",
    }


def audit_game(draws: list[Draw], game: Game, *, start: int = 30) -> dict:
    """Internal rolling replay; NOT proof of out-of-sample prospective edge."""
    replay = walk_forward_bank(draws, game, start=start)
    result = independent_score(draws, game, replay["per_issue_audit"],
                               start=start)
    if (result["full_ticket"]["hits"] != replay["exact_hits"]
            or result["d2"]["hits"] != replay["d2_hits"]
            or result["research_null"]["d2_hits"] != replay["research_null_d2_hits"]):
        raise ValueError("independent replay disagrees with formula bank summary")
    result["report_sha256"] = digest(result)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=30)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.start < 30:
        ap.error("a past-only 30-issue warmup is required")
    documents = {}
    for game, stem in ((SSQ, "ssq"), (DLT, "dlt")):
        history, source_sha = load_history(
            Path(__file__).with_name(stem + "_2026.txt"), game)
        documents[game.name] = {
            "source_fixture_sha256": source_sha,
            "audit": audit_game(history, game, start=args.start),
        }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(documents, ensure_ascii=False,
                                       sort_keys=True, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({game: {
        "full_hits": doc["audit"]["full_ticket"]["hits"],
        "d2_hits": doc["audit"]["d2"]["hits"],
        "research_null_d2_hits": doc["audit"]["research_null"]["d2_hits"],
        "periods": doc["audit"]["evaluated_issues"],
        "report_sha256": doc["audit"]["report_sha256"],
        "status": "NO_EDGE",
    } for game, doc in documents.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
