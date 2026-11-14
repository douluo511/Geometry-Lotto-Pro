"""Four-area SSQ/DLT adaptive include/exclude interval research.

SSQ front=red 01..33, back=blue 01..16.
DLT front 01..35, back 01..12.
Each area has independent required (subset) and forbidden (disjoint) sets.
Zero included/excluded is legal. Candidate *quantities*, zones and their
survival are tested on past-only folds before target inference.

This is descriptive/experimental selection, NOT proven predictive ability.
Back/blue exclusion signals are inverse candidate proxies, NOT eleven separately
trained independent back-exclusion models. Do not imply otherwise.
"""
from __future__ import annotations

from collections import Counter
import heapq
import itertools
import math

from research.supercompute.v47_models import SPECS, validate_ticket

ZONES = {
    "ssq": {"front": ((1, 11), (12, 22), (23, 33)),
            "back": ((1, 5), (6, 10), (11, 16))},
    "dlt": {"front": ((1, 12), (13, 24), (25, 35)),
            "back": ((1, 4), (5, 8), (9, 12))},
}
AREAS = ("front", "back")
PROFILE_NAMES = ("front_include", "front_exclude", "back_include", "back_exclude")


def legal_area_count(maximum, picked, required, excluded):
    """Exactly C(N-a-e,k-a); 0 is allowed if constraints are impossible."""
    if any(type(n) is not int for n in (maximum, picked, required, excluded)):
        raise ValueError("non-integral counts")
    if (not 0 <= picked <= maximum or not 0 <= required <= picked
            or not 0 <= excluded <= maximum - picked):
        raise ValueError("invalid counts")
    return math.comb(maximum - required - excluded, picked - required)


def profile_grid(game):
    if game not in SPECS:
        raise ValueError("unknown game")
    fm, fp, bm, bp = SPECS[game]
    # This is a deliberately bounded research grid, not a statement that
    # these quantities are optimal. All 4 values can be zero.
    for fi, fe, bi, be in itertools.product(
        range(0, min(3, fp) + 1), range(0, 5),
        range(0, bp + 1), range(0, 5)):
        if fe <= fm - fp and be <= bm - bp:
            yield dict(zip(PROFILE_NAMES, (fi, fe, bi, be)))


def model_evidence(records, game):
    """Derive votes and marginal rank scores from all 11+11 records."""
    if game not in SPECS or len(records) != 22:
        raise ValueError("need 22 records and known lottery")
    expected = [f"M{i:02d}{s}" for i in range(1, 12) for s in ("+", "-")]
    if [x["model_id"] for x in records] != expected:
        raise ValueError("not the complete paired model registry")
    fm, fp, bm, bp = SPECS[game]
    values = {}
    for area, maximum, picked in (("front", fm, fp), ("back", bm, bp)):
        positive, negative, vectors = Counter(), Counter(), []
        for rec in records:
            pred = rec["prediction"]
            if rec["direction"] == "subset":
                marginal = pred["marginals"][area]
                chosen = (pred["ticket"]["dan2"] if area == "front"
                          else pred["ticket"]["back"])
                if len(set(chosen)) != len(chosen):
                    raise ValueError("duplicate positive vote")
                positive.update(chosen)
            elif rec["direction"] == "disjoint":
                marginal = pred["candidate_marginals"][area]
                if area == "front":
                    chosen = pred["excluded_pair"]
                    if len(chosen) != 2 or len(set(chosen)) != 2:
                        raise ValueError("invalid front exclusion pair")
                else:
                    # Back/blue has no separately trained M- head in V2.
                    # Treat its lowest ranked candidate probabilities as
                    # exploratory negative signals, not validated predictions.
                    chosen = sorted(range(1, maximum + 1),
                                    key=lambda n: (marginal[n], n))[:2]
                negative.update(chosen)
            else:
                raise ValueError("legacy partial-exclusion event not accepted")
            if (len(marginal) != maximum + 1 or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v)
                    or not 0 <= v <= 1 for v in marginal[1:])):
                raise ValueError("invalid model marginal")
            vectors.append(marginal)
        if len(vectors) != 22:
            raise ValueError("incomplete area evidence")
        scores = [0.0] + [sum(v[n] for v in vectors) / 22
                          for n in range(1, maximum + 1)]
        values[area] = {"maximum": maximum, "picked": picked,
                        "positive": dict(positive),
                        "negative": dict(negative),
                        "score": scores}
    return values


def area_constraints(evidence, area, include, exclude, game):
    e = evidence[area]
    maximum, picked = e["maximum"], e["picked"]
    count = legal_area_count(maximum, picked, include, exclude)
    positive, negative, score = e["positive"], e["negative"], e["score"]
    required = sorted(
        sorted(range(1, maximum + 1),
               key=lambda n: (-positive.get(n, 0), -score[n], n))[:include])
    forbidden = sorted(
        sorted((n for n in range(1, maximum + 1) if n not in required),
               key=lambda n: (-negative.get(n, 0), score[n], n))[:exclude])
    if set(required).intersection(forbidden):
        raise AssertionError("conflicting hard constraints")
    zone_report = []
    for low, high in ZONES[game][area]:
        zone = set(range(low, high + 1))
        zone_report.append({
            "low": low, "high": high,
            "required": sorted(zone & set(required)),
            "excluded": sorted(zone & set(forbidden)),
            "available_numbers": len(zone - set(forbidden)),
            "fair_expected_draw_count": round(picked * len(zone) / maximum, 6),
        })
    return {"required": required, "excluded": forbidden, "retained": count,
            "original": math.comb(maximum, picked),
            "retained_fraction": count / math.comb(maximum, picked),
            "zones": zone_report,
            "model_votes_required": {str(n): positive.get(n, 0)
                                     for n in required},
            "model_votes_excluded": {str(n): negative.get(n, 0)
                                     for n in forbidden},
            "conflict_candidates": sorted(set(positive) & set(negative)),
            "constraint_selection": "vote_rank_with_marginal_tiebreak",
            "model_votes_correlated": True,
            "negative_area_independently_trained": area == "front"}


def build_constraints(evidence, game, profile):
    if game not in SPECS or set(profile) != set(PROFILE_NAMES):
        raise ValueError("invalid profile")
    front = area_constraints(evidence, "front", profile["front_include"],
                             profile["front_exclude"], game)
    back = area_constraints(evidence, "back", profile["back_include"],
                            profile["back_exclude"], game)
    return {"front": front, "back": back}


def score_constraints(areas, actual, game):
    validate_ticket(actual, game)
    by_area = {}
    for area in AREAS:
        included = set(areas[area]["required"]).issubset(actual[area])
        disjoint = set(areas[area]["excluded"]).isdisjoint(actual[area])
        by_area[area] = {"required_all_present": included,
                         "excluded_all_absent": disjoint,
                         "retains_actual": included and disjoint,
                         "excluded_hits": len(set(areas[area]["excluded"]) &
                                               set(actual[area]))}
    return {"areas": by_area,
            "all_area_constraints_survived":
                all(by_area[area]["retains_actual"] for area in AREAS)}


def _top_area_combos(evidence, area, constraints, limit):
    """Exact additive-score top-K without iterating a million combinations.

    The best-first combinatorial search expands monotone successor index
    tuples. Each legal k-subset is reachable from initial (0,...,k-1);
    every successor's log-score cannot improve over its parent.
    """
    e = evidence[area]
    need = e["picked"] - len(constraints["required"])
    required = tuple(constraints["required"])
    forbidden = set(constraints["excluded"])
    choices = sorted((n for n in range(1, e["maximum"] + 1)
                      if n not in forbidden and n not in required),
                     key=lambda n: (-e["score"][n], n))
    if len(choices) < need:
        raise ValueError("impossible remaining area size")
    logs = [math.log(max(1e-9, e["score"][n])) for n in choices]
    required_base = sum(math.log(max(1e-9, e["score"][n])) for n in required)

    def score(indexes):
        return required_base + sum(logs[i] for i in indexes)

    def balls(indexes):
        return tuple(sorted(required + tuple(choices[i] for i in indexes)))

    start = tuple(range(need))
    heap = [(-score(start), balls(start), start)]
    seen = {start}
    results = []
    while heap and len(results) < limit:
        minus, value, indexes = heapq.heappop(heap)
        results.append((-minus, value))
        for j in range(need):
            indexes_new = list(indexes)
            cap = indexes[j + 1] if j + 1 < need else len(choices)
            if indexes[j] + 1 >= cap:
                continue
            indexes_new[j] += 1
            new = tuple(indexes_new)
            if new in seen:
                continue
            seen.add(new)
            heapq.heappush(heap, (-score(new), balls(new), new))
    return results


def construct_interval_search(records, game, profile, *, limit=8,
                              evidence=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid search limit")
    evidence = evidence if evidence is not None else model_evidence(records, game)
    areas = build_constraints(evidence, game, profile)
    best_front = _top_area_combos(evidence, "front", areas["front"], limit)
    best_back = _top_area_combos(evidence, "back", areas["back"], limit)
    combos = sorted(
        ((fs + bs, f, b) for fs, f in best_front for bs, b in best_back),
        key=lambda x: (-x[0], x[1], x[2]))[:limit]
    tickets = []
    for rank, (value, front, back) in enumerate(combos, 1):
        ticket = {"front": list(front), "back": list(back),
                  "dan2": sorted(front[:2]),
                  "heuristic_score": round(value, 9),
                  "formal_prediction": False, "rank": rank}
        validate_ticket(ticket, game)
        for area in AREAS:
            if not set(areas[area]["required"]).issubset(ticket[area]):
                raise AssertionError("required constraint violated")
            if set(areas[area]["excluded"]) & set(ticket[area]):
                raise AssertionError("exclude constraint violated")
        tickets.append(ticket)
    retained = areas["front"]["retained"] * areas["back"]["retained"]
    original = areas["front"]["original"] * areas["back"]["original"]
    if not tickets:
        raise AssertionError("no legal combined front/back ticket")
    return {
        "schema": "SSQDLT_V47_FOUR_AREA_INTERVAL_SEARCH_V1",
        "game": game, "profile": profile, "areas": areas,
        "original_full_ticket_combinations": original,
        "retained_full_ticket_combinations": retained,
        "retained_fraction": retained / original,
        "fair_combined_constraint_survival": retained / original,
        "model_records_used": 22,
        "ranking": "exact_top_k_by_additive_log_mean_signal",
        "back_exclusion_training": "UNVERIFIED_PROXY_NOT_INDEPENDENT_M_MINUS",
        "formal_prediction": False, "edge": "NO_EDGE",
        "tickets": tickets,
        "ticket_count": len(tickets),
    }


def score_interval_search(search, actual, game):
    if search.get("game") != game:
        raise ValueError("lottery mismatch")
    outcome = score_constraints(search["areas"], actual, game)
    exact = sum(int(t["front"] == actual["front"] and
                    t["back"] == actual["back"]) for t in search["tickets"])
    return {**outcome, "exact_full_jackpot_hits": exact,
            "complete_tickets_searched": len(search["tickets"]),
            "retained_full_ticket_combinations":
                search["retained_full_ticket_combinations"],
            "edge": "NO_EDGE"}


def calibrate_profiles(folds, game):
    """Prequential profile choice: fit only earlier folds; final fold is blind.

    At 3 folds, this is NOT evidence of predictive advantage: exposure of
    >1 profile creates an obvious multiple-testing/overfit risk.
    """
    if game not in SPECS or len(folds) < 3:
        raise ValueError("need at least two training folds and one heldout")
    prepared = []
    for fold in folds:
        observed = fold["actual"]
        validate_ticket(observed, game)
        prepared.append({
            "issue": str(observed["issue"]),
            "evidence": model_evidence(fold["records"], game),
            "actual": observed,
        })
    train, heldout = prepared[:-1], prepared[-1]
    tested = []
    for profile in profile_grid(game):
        folds_valid = []
        total = None
        for fold in train:
            areas = build_constraints(fold["evidence"], game, profile)
            valid = score_constraints(areas, fold["actual"], game)
            folds_valid.append(valid["all_area_constraints_survived"])
            if total is None:
                total = (areas["front"]["retained_fraction"] *
                         areas["back"]["retained_fraction"])
        if all(folds_valid):
            tested.append((total, sum(profile.values()), tuple(profile[n]
                           for n in PROFILE_NAMES), profile))
    if not tested:
        raise AssertionError("zero-size profile should always survive training")
    # Smallest surviving space, ties: fewer hard numbers, then lexical.
    tested.sort(key=lambda x: (x[0], x[1], x[2]))
    selected = tested[0][3]
    held_areas = build_constraints(heldout["evidence"], game, selected)
    held_score = score_constraints(held_areas, heldout["actual"], game)
    return {
        "schema": "SSQDLT_V47_INTERVAL_PROFILE_AUDIT_V1",
        "profile": selected,
        "train_folds": [{"issue": fold["issue"],
                         "all_area_constraints_survived": True}
                        for fold in train],
        "validation_issue": heldout["issue"],
        "heldout_outcome": held_score,
        "heldout_retained_fraction":
            held_areas["front"]["retained_fraction"] *
            held_areas["back"]["retained_fraction"],
        "profiles_considered": sum(1 for _ in profile_grid(game)),
        "feasible_training_profiles": len(tested),
        "selection": "min_space_subject_to_100pct_prior_fold_survival",
        "validation_independent_of_selection": True,
        "statistical_status": "INSUFFICIENT_FOLDS_NO_RELIABLE_EDGE",
        "multiple_comparisons_adjusted": False,
        "back_negative_fit_status": "HEURISTIC_NOT_INDEPENDENTLY_TRAINED",
        "edge": "NO_EDGE",
    }
