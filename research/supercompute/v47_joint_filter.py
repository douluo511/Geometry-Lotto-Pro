"""Joint front-number filter: all required appear AND all excluded are absent.

Eleven correlated positive signals vote for two "required" front balls and
eleven correlated negative signals vote for two "excluded" front balls.
Both constraints must hold simultaneously: A subset of draw, E disjoint draw.
The exact retained combinatorial space is calculated before searching.
This is an exploratory ranking, NOT a demonstrated full-jackpot advantage.
"""
from __future__ import annotations

from collections import Counter
import itertools
import math

from research.supercompute.v47_models import SPECS, validate_ticket


def fair_constraint_probability(game, required_size=2, excluded_size=2):
    """Probability a fixed disjoint A,E both satisfy their two requirements."""
    maximum, picked, _, _ = SPECS[game]
    if (not 0 <= required_size <= picked or excluded_size < 0 or
            maximum - required_size - excluded_size < picked - required_size):
        raise ValueError("impossible constraints")
    retained = math.comb(maximum - required_size - excluded_size,
                         picked - required_size)
    return retained / math.comb(maximum, picked)


def _mean_probabilities(records, game, area):
    fm, fp, bm, bp = SPECS[game]
    maximum = fm if area == "front" else bm
    picked = fp if area == "front" else bp
    vectors = []
    for record in records:
        p = record["prediction"]
        if record["direction"] == "subset":
            v = p["marginals"][area]
        else:
            v = p["candidate_marginals"][area]
        if len(v) != maximum + 1 or any(
                not math.isfinite(x) or not 0 <= x <= 1 for x in v[1:]):
            raise ValueError("invalid model marginal signal")
        vectors.append(v)
    if len(vectors) != 22:
        raise ValueError("joint filter requires all 22 model signals")
    # Averaging correlated scores, NOT multiplying them as independent odds.
    ans = [0.0] + [sum(v[n] for v in vectors) / len(vectors)
                   for n in range(1, maximum + 1)]
    # Some of the weak physics proxies may not have mass k.
    # Normalization by ranking does not assert calibrated probabilities.
    if max(ans[1:]) <= 0:
        raise ValueError("zero joint model signal")
    return ans


def select_joint_constraints(records, game, required_count=2, excluded_count=2):
    """A/E selection with overlap resolved before applying hard constraints."""
    if game not in SPECS or len(records) != 22:
        raise ValueError("unknown lottery or incomplete model registry")
    maximum, picked, _, _ = SPECS[game]
    if not (1 <= required_count <= picked
            and 1 <= excluded_count <= maximum - picked):
        raise ValueError("invalid constraint sizes")
    ids = [r["model_id"] for r in records]
    expected = [f"M{i:02d}{suffix}" for i in range(1, 12)
                for suffix in ("+", "-")]
    if ids != expected:
        raise ValueError("not eleven true positive-negative model pairs")
    pos, neg = Counter(), Counter()
    for r in records:
        if r["direction"] == "subset":
            selected = r["prediction"]["ticket"]["dan2"]
            if len(selected) != 2 or not set(selected).issubset(
                    r["prediction"]["ticket"]["front"]):
                raise ValueError("positive include pair not from candidate ticket")
            pos.update(selected)
        elif r["direction"] == "disjoint":
            selected = r["prediction"]["excluded_pair"]
            if len(selected) != 2 or len(set(selected)) != 2:
                raise ValueError("negative exclude pair not two distinct balls")
            neg.update(selected)
        else:
            raise ValueError("outdated non-disjoint negative event is forbidden")
    if any(n < 1 or n > maximum for n in set(pos) | set(neg)):
        raise ValueError("out of range model vote")
    marg = _mean_probabilities(records, game, "front")
    included = sorted(
        sorted(range(1, maximum + 1),
               key=lambda n: (-pos[n], -marg[n], n))[:required_count])
    # Explicitly prevent contradictory hard sets; retain the rejected
    # exclusion votes in an evidence trail instead of silently dropping them.
    excluded = sorted(
        sorted((n for n in range(1, maximum + 1) if n not in included),
               key=lambda n: (-neg[n], marg[n], n))[:excluded_count])
    if set(included) & set(excluded):
        raise AssertionError("joint included/excluded conflict not resolved")
    conflicts = sorted(set(pos) & set(neg))
    return {
        "required": included,
        "excluded": excluded,
        "required_vote_counts": {str(n): pos[n] for n in sorted(pos)},
        "excluded_vote_counts": {str(n): neg[n] for n in sorted(neg)},
        "conflict_numbers": conflicts,
        "conflict_resolution": "positive_hard_constraint_takes_precedence; "
                               "excluded_candidates_skipping_required",
        "required_model_support": {str(n): pos[n] for n in included},
        "excluded_model_support": {str(n): neg[n] for n in excluded},
        "signals_are_correlated": True,
        "voting_is_not_calibrated_probability": True,
        "required_size": required_count,
        "excluded_size": excluded_count,
    }


def _score_ticket(front, back, front_signal, back_signal):
    return (sum(math.log(max(1e-9, front_signal[n])) for n in front)
            + sum(math.log(max(1e-9, back_signal[n])) for n in back))


def construct_joint_search(records, game, *, limit=8, required_count=2,
                           excluded_count=2):
    """Enumerate ALL legal front combinations; rank legal front+back tickets."""
    if not 1 <= limit <= 100:
        raise ValueError("invalid result limit")
    fm, fp, bm, bp = SPECS[game]
    contract = select_joint_constraints(
        records, game, required_count=required_count,
        excluded_count=excluded_count)
    required, excluded = set(contract["required"]), set(contract["excluded"])
    remaining = sorted(set(range(1, fm + 1)) - required - excluded)
    k = fp - len(required)
    combos = math.comb(len(remaining), k)
    if combos < 1:
        raise ValueError("joint constraint space empty")
    front_signal = _mean_probabilities(records, game, "front")
    back_signal = _mean_probabilities(records, game, "back")
    ranked_front = []
    for tail in itertools.combinations(remaining, k):
        candidate = tuple(sorted(required | set(tail)))
        if not required.issubset(candidate) or not excluded.isdisjoint(candidate):
            raise AssertionError("joint search violated the strict constraints")
        score = sum(math.log(max(1e-9, front_signal[n])) for n in candidate)
        ranked_front.append((score, candidate))
    if len(ranked_front) != combos:
        raise AssertionError("joint enumeration did not exhaust front constraints")
    ranked_front.sort(key=lambda e: (-e[0], e[1]))
    # Search all possible backs; do not falsely claim that only searching
    # the front/red area fixes the jackpot's blue/back area.
    ranked_back = []
    for b in itertools.combinations(range(1, bm + 1), bp):
        score = sum(math.log(max(1e-9, back_signal[n])) for n in b)
        ranked_back.append((score, b))
    ranked_back.sort(key=lambda e: (-e[0], e[1]))
    # Full combination scoring is separable in these additive heuristics,
    # so restricting to top limit fronts and top limit backs is exact
    # for finding the top limit pairs.
    ranked_joint = sorted(
        ((fs + bs, f, b) for fs, f in ranked_front[:limit]
         for bs, b in ranked_back[:limit]),
        key=lambda item: (-item[0], item[1], item[2]))[:limit]
    tickets = []
    for score, front, back in ranked_joint:
        ticket = {"front": list(front), "back": list(back),
                  "dan2": list(contract["required"]),
                  "heuristic_score": round(score, 9),
                  "formal_prediction": False}
        validate_ticket(ticket, game)
        if not required.issubset(ticket["front"]) or not excluded.isdisjoint(
                ticket["front"]):
            raise AssertionError("output ticket not from filtered space")
        tickets.append(ticket)
    total_front = math.comb(fm, fp)
    total_back = math.comb(bm, bp)
    return {
        "schema": "SSQDLT_V47_JOINT_HARD_CONSTRAINT_V1",
        "game": game,
        "mathematical_events": {
            "positive": "A_SUBSET_OF_DRAW",
            "negative": "E_DISJOINT_DRAW",
            "joint": "A_SUBSET_DRAW_AND_E_DISJOINT_DRAW"},
        "constraints": contract,
        "original_front_combinations": total_front,
        "retained_front_combinations": combos,
        "original_full_ticket_combinations": total_front * total_back,
        "retained_full_ticket_combinations": combos * total_back,
        "remaining_fraction": combos / total_front,
        "fair_probability_constraints_all_correct": fair_constraint_probability(
            game, len(required), len(excluded)),
        "front_space_reduction_factor": total_front / combos,
        "model_count_used": len(records),
        "ticket_count": len(tickets),
        "tickets": tickets,
        "search_method": "exhaustive_front_search; exhaustive_back_search; "
                         "mean_correlated_marginal_log_scores",
        "confidence": "UNVERIFIED_EXPLORATORY",
        "edge": "NO_EDGE",
        "not_a_jackpot_probability_improvement_claim": True,
    }


def score_joint_search(search, actual, game):
    validate_ticket(actual, game)
    if search.get("game") != game:
        raise ValueError("game mismatch")
    req = set(search["constraints"]["required"])
    ex = set(search["constraints"]["excluded"])
    actual_front = set(actual["front"])
    pos = req.issubset(actual_front)
    neg = ex.isdisjoint(actual_front)
    full = [t for t in search["tickets"]
            if t["front"] == actual["front"] and t["back"] == actual["back"]]
    return {
        "required_all_appear": pos,
        "excluded_all_absent": neg,
        "joint_filter_keeps_actual_front": pos and neg,
        "winning_front_in_retained_space": pos and neg,
        "exact_jackpot_ticket_hits": len(full),
        "candidate_count": len(search["tickets"]),
        "full_jackpot_success": bool(full),
        "fair_reference": search["fair_probability_constraints_all_correct"],
        "prediction_edge": "NO_EDGE",
    }
