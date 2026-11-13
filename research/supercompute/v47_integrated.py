"""Unified 11-stage SSQ/DLT next-candidate research pipeline.

Runs FIVE named statistical selector families and SIX supporting layers as one
pipeline. All evolution and evaluation use only draws preceding a prediction.
The physics layer is explicitly uncalibrated. No claim of a proven lottery edge.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

from research.supercompute.v47_models import (
    DEFAULT, MODELS, SPECS, backtest, candidates, canonical,
    geometry, geometry_state, geometry_transition, inclusion_probabilities,
    m1_math, m2_refutation, m3_calibration, monte_carlo, pair_residuals,
    parameters, physics_toy, seed_from, validate_history, validate_ticket,
    weighted_counts, shrink, zone_state,
)

FAMILIES = ("HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger")
REQUIREMENTS = (
    "1:HOT60", "2:EWMA", "3:ShrinkMix", "4:Pairwise-D2",
    "5:Challenger", "6:statistics", "7:combination_freeze_score",
    "8:geometry", "9:probability_simulation",
    "10:uncalibrated_physics", "11:M1_M2_M3",
)
GENES = ("window", "half_life", "prior", "mix", "pair_weight", "geo_weight")
# Fixed BEFORE looking at the evaluation tail; sum is exactly one.
ENSEMBLE = {"HOT60": .18, "EWMA": .18, "ShrinkMix": .18,
            "Pairwise-D2": .18, "Challenger": .28}


def _identity(genome):
    return hashlib.sha256(canonical(parameters(genome))).hexdigest()[:12]


def _fitness(rows, game, genome, validation):
    """Walk-forward fitness; each fold sees ONLY rows strictly before itself."""
    start = len(rows) - validation
    errors, misses = [], 0
    for i in range(start, len(rows)):
        history, actual = rows[:i], rows[i]
        for area, (ceiling, _) in (
                ("front", SPECS[game][:2]), ("back", SPECS[game][2:])):
            prob = inclusion_probabilities(history, game, area, "Challenger", genome)
            observed = set(actual[area])
            errors.extend((prob[n] - int(n in observed)) ** 2
                          for n in range(1, ceiling + 1))
        pred = candidates(history, game, "Challenger", genome, 1)[0]
        misses += not set(pred["dan2"]).issubset(actual["front"])
    return statistics.mean(errors) + .005 * misses / validation


def cell_division(rows, game, seed=2026, generations=2, validation=6,
                  previous_champion=None):
    """Documented evolutionary search: selection -> crossover -> mutation.

    Previous champion may be supplied from a prior immutable run to enable
    cross-run inheritance, but no new information means no new predictive evidence.
    """
    validate_history(rows, game)
    if (game not in SPECS or len(rows) < 80 + validation
            or not 1 <= generations <= 5 or not 2 <= validation <= 24):
        raise ValueError("invalid evolution bounds")
    rng = random.Random(seed_from(seed, game, rows[-1]["issue"], "mitosis"))
    initial = [
        parameters({"half_life": 15, "mix": .35, "prior": 30,
                    "pair_weight": .08, "geo_weight": .1}),
        parameters({"half_life": 30, "mix": .5, "prior": 60,
                    "pair_weight": .12, "geo_weight": .2}),
        parameters({"half_life": 60, "mix": .65, "prior": 120,
                    "pair_weight": .2, "geo_weight": .3}),
    ]
    if previous_champion is not None:
        initial.append(parameters(previous_champion))
    population = []
    for p in initial:
        population.append({"id": _identity(p), "parent_ids": [],
                           "genes": p, "origin": "seed"})
    mutations = {"window": (10, 15, 180), "half_life": (10, 2, 180),
                 "prior": (20, 0, 300), "mix": (.1, 0, 1),
                 "pair_weight": (.04, 0, 1), "geo_weight": (.08, 0, 1)}
    lineage, evaluations = [], {}
    for generation in range(generations):
        for cell in population:
            key = cell["id"]
            if key not in evaluations:
                evaluations[key] = _fitness(rows, game, cell["genes"], validation)
            cell["fitness"] = evaluations[key]
        ranked = sorted(population, key=lambda x: (x["fitness"], x["id"]))
        survivors = ranked[:2]
        lineage.append({"generation": generation,
                        "evaluated": [{"id": c["id"], "parents": c["parent_ids"],
                                       "objective": c["fitness"], "origin": c["origin"]}
                                      for c in ranked],
                        "survivor_ids": [s["id"] for s in survivors]})
        # Carry the two elites forward; produce four genetically distinct children.
        next_population = [dict(s) for s in survivors]
        existing = {s["id"] for s in next_population}
        for _ in range(4):
            a, b = rng.sample(survivors, 2)
            child_genes = {key: rng.choice((a["genes"][key], b["genes"][key]))
                           for key in GENES}
            for _attempt in range(16):
                changed = dict(child_genes)
                gene = rng.choice(GENES)
                step, low, high = mutations[gene]
                changed[gene] = max(low, min(high, changed[gene]
                                          + rng.choice((-1, 1)) * step))
                changed = parameters(changed)
                uid = _identity(changed)
                if uid not in existing:
                    break
            else:
                continue
            existing.add(uid)
            next_population.append({"id": uid, "parent_ids": [a["id"], b["id"]],
                                    "genes": changed, "origin": "crossover_mutation"})
        population = next_population
    for cell in population:
        if cell["id"] not in evaluations:
            evaluations[cell["id"]] = _fitness(rows, game, cell["genes"], validation)
        cell["fitness"] = evaluations[cell["id"]]
    champion = min(population, key=lambda x: (x["fitness"], x["id"]))
    lineage.append({"generation": generations, "final_id": champion["id"],
                    "final_objective": champion["fitness"]})
    return {"champion_id": champion["id"], "champion": champion["genes"],
            "validation_objective": champion["fitness"],
            "validation_first_issue": rows[-validation]["issue"],
            "trained_through_issue": rows[-1]["issue"],
            "parent_from_prior_run": previous_champion is not None,
            "generations": generations, "lineage": lineage,
            "uses_future_draws": False}


def _historical_validation(rows, game, seed, holdout=3):
    if len(rows) < 90 + holdout or not 2 <= holdout <= 30:
        raise ValueError("need chronology-safe holdout")
    prefix = rows[:-holdout]
    frozen_training = cell_division(prefix, game, seed=seed, validation=5,
                                    generations=1)
    events = {m: [] for m in (*FAMILIES, "RANDOM_NULL")}
    calibrations = {m: [] for m in FAMILIES}
    for i in range(len(prefix), len(rows)):
        history, actual = rows[:i], rows[i]
        for model in (*FAMILIES, "RANDOM_NULL"):
            genes = frozen_training["champion"] if model == "Challenger" else None
            ticket = candidates(history, game, model, genes, 1, seed)[0]
            events[model].append(int(set(ticket["dan2"]).issubset(actual["front"])))
            if model != "RANDOM_NULL":
                for area, (ceiling, _) in (
                        ("front", SPECS[game][:2]), ("back", SPECS[game][2:])):
                    probs = inclusion_probabilities(history, game, area, model, genes)
                    observed = set(actual[area])
                    calibrations[model].extend((probs[n], int(n in observed))
                                               for n in range(1, ceiling + 1))
    return {
        "holdout_issues": [str(x["issue"]) for x in rows[-holdout:]],
        "champion_selected_through": str(prefix[-1]["issue"]),
        "strictly_past_only": True, "random_null_d2_hits": sum(events["RANDOM_NULL"]),
        "models": {name: {
            "d2_hits": sum(events[name]), "trials": holdout,
            "m2": m2_refutation(events[name], events["RANDOM_NULL"]),
            "m3": m3_calibration(calibrations[name]),
        } for name in FAMILIES},
    }


def _ranking(rows, game, champion, physics_ticket, top_n=3):
    """Combinatorial ensemble: all five families + pair/geometry/physics traces."""
    fm, fp, bm, bp = SPECS[game]
    probs = {}
    for area in ("front", "back"):
        probs[area] = [0.0] * ((fm if area == "front" else bm) + 1)
        for family, weight in ENSEMBLE.items():
            genes = champion if family == "Challenger" else None
            p = inclusion_probabilities(rows, game, area, family, genes)
            for num in range(1, len(p)):
                probs[area][num] += weight * p[num]
    pairs = pair_residuals(rows, game)
    transition, fair = geometry_transition(rows, game)
    mean_span = geometry_state(rows, game)["mean_span"]
    phys_f, phys_b = set(physics_ticket["front"]), set(physics_ticket["back"])
    pool_front = sorted(range(1, fm + 1),
                        key=lambda n: (-probs["front"][n], n))[:13]
    pool_back = sorted(range(1, bm + 1),
                       key=lambda n: (-probs["back"][n], n))[:7]
    def logodds(p):
        p = min(1 - 1e-9, max(1e-9, p))
        return math.log(p / (1 - p))
    def fscore(combo):
        state = zone_state({"front": combo}, game)
        freq = sum(logodds(probs["front"][n]) for n in combo)
        pair = champion["pair_weight"] * sum(pairs[ab]
                  for ab in itertools.combinations(combo, 2))
        geo = champion["geo_weight"] * (
            math.log(max(1e-12, transition[state] / fair[state]))
            - abs(combo[-1] - combo[0] - mean_span) / fm)
        phys = .01 * len(phys_f.intersection(combo))  # toy heuristic only
        return freq + pair + geo + phys
    front = sorted(((fscore(c), c)
                    for c in itertools.combinations(sorted(pool_front), fp)),
                   key=lambda x: (-x[0], x[1]))[:max(10, top_n)]
    back = sorted(((sum(logodds(probs["back"][n]) for n in b)
                    + .01 * len(phys_b.intersection(b)), b)
                   for b in itertools.combinations(sorted(pool_back), bp)),
                  key=lambda x: (-x[0], x[1]))[:max(10, top_n)]
    joint = sorted(((fs + bs, f, b) for fs, f in front for bs, b in back),
                   key=lambda x: (-x[0], x[1], x[2]))
    result = []
    used = set()
    for score, f, b in joint:
        if (f, b) in used:
            continue
        used.add((f, b))
        ticket = {"front": list(f), "back": list(b),
                  "dan2": sorted(sorted(f, key=lambda n: (-probs["front"][n], n))[:2]),
                  "heuristic_score": round(score, 8), "formal_prediction": False}
        validate_ticket(ticket, game)
        result.append(ticket)
        if len(result) >= top_n:
            break
    return result, {"front": probs["front"][1:], "back": probs["back"][1:],
                    "model_weights": ENSEMBLE, "front_pool": pool_front,
                    "back_pool": pool_back, "physical_bonus_weight": .01}


def run_all(rows, game, target_issue, *, seed=2026, generations=2,
            validation=6, holdout=3, mc_trials=300,
            physics_steps=30, previous_champion=None):
    """One function must execute EVERY numbered requirement.

    Explicit target_issue is mandatory; never assume a stale historical
    snapshot tells us the latest upcoming real issue.
    """
    if game not in SPECS or not str(target_issue).strip():
        raise ValueError("explicit game and target_issue required")
    validate_history(rows, game)
    if len(rows) < 120 + holdout:
        raise ValueError("insufficient historical data")
    fingerprint = hashlib.sha256(canonical(rows)).hexdigest()
    # Freeze model selection before inspecting the chronological evaluation tail.
    validation_report = _historical_validation(rows, game, seed, holdout=holdout)
    division = cell_division(rows, game, seed, generations, validation,
                             previous_champion=previous_champion)
    families = {}
    for family in FAMILIES:
        opts = division["champion"] if family == "Challenger" else None
        families[family] = candidates(rows, game, family, opts, 2, seed)
    hot_count, exposure = weighted_counts(rows, "front", SPECS[game][0],
                                          "HOT60", parameters())
    p_shrink = shrink(hot_count, exposure, SPECS[game][0], SPECS[game][1], 60)
    top_pairs = sorted(pair_residuals(rows, game).items(),
                       key=lambda pair: (-pair[1], pair[0]))[:10]
    physical = physics_toy(game, seed, steps=physics_steps)
    geo_transition, fair_state = geometry_transition(rows, game)
    tickets, ensemble_trace = _ranking(
        rows, game, division["champion"], physical["toy_ticket"])
    for ticket in tickets:
        ticket["after_issue"] = str(rows[-1]["issue"])
    m1 = [m1_math(rows, game, t) for t in tickets]
    mc = monte_carlo(game, mc_trials, seed)
    # All eleven modules have real, individually inspectable output.
    return {
        "schema": "SSQDLT_V47_UNIFIED_11_V1",
        "game": game, "target_issue": str(target_issue),
        "history_last_issue": str(rows[-1]["issue"]),
        "history_last_date": str(rows[-1]["draw_date"]),
        "history_sha256": fingerprint,
        "history_status": "HISTORICAL_INPUT_NOT_LIVE_VERIFIED",
        "seed": seed, "requirement_modules": list(REQUIREMENTS),
        "model_family_tickets": families,
        "statistics": {"recent_front_weighted_exposures": exposure,
                       "top_front_counts": sorted(((n, hot_count[n])
                           for n in range(1, len(hot_count))),
                           key=lambda x: (-x[1], x[0]))[:10],
                       "top_front_shrink": sorted(((n, p_shrink[n])
                           for n in range(1, len(p_shrink))),
                           key=lambda x: (-x[1], x[0]))[:10],
                       "top_pair_residuals": [[list(ab), score]
                                              for ab, score in top_pairs],
                       "decay_half_life": division["champion"]["half_life"]},
        "evolution": division,
        "geometry": {"features": geometry_state(rows, game),
                     "transition_states": len(geo_transition),
                     "transition_probability_mass": sum(geo_transition.values()),
                     "fair_state_probability_mass": sum(fair_state.values())},
        "simulation": {"uniform_monte_carlo": mc,
                       "retrospective_validation": validation_report},
        "physics": physical,
        "ensemble": ensemble_trace,
        "proposed_tickets": tickets,
        "validation": {"M1": m1,
                       "M2": {k: v["m2"] for k,v in validation_report["models"].items()},
                       "M3": {k: v["m3"] for k,v in validation_report["models"].items()}},
        "forecast_frozen": False,
        "formal_prediction": False, "edge": "NO_EDGE",
    }


def freeze_result(path, report):
    """Create-only research freeze. A hash is NOT a trusted predraw timestamp."""
    if (report.get("schema") != "SSQDLT_V47_UNIFIED_11_V1"
            or report.get("edge") != "NO_EDGE"
            or len(report.get("requirement_modules", [])) != 11
            or not report.get("proposed_tickets")
            or report.get("formal_prediction") is not False):
        raise ValueError("not an acceptable 11-module research report")
    doc = {"schema": "SSQDLT_V47_UNIFIED_FROZEN_V1",
           "created_utc": datetime.now(timezone.utc).isoformat(),
           "source": report, "formal_prediction": False,
           "source_of_draw": "UNVERIFIED_RESEARCH_INPUT"}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(doc)
    with path.open("xb") as f:
        f.write(data)
    return {"file": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "target_issue": report["target_issue"]}


def score_result(path, sha256, actual):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("frozen report hash mismatch")
    doc = json.loads(raw)
    source = doc["source"]
    if str(actual.get("issue")) != source["target_issue"]:
        raise ValueError("target issue mismatch")
    validate_ticket(actual, source["game"])
    scores = []
    for ticket in source["proposed_tickets"]:
        scores.append({"ticket": ticket, "front_hits": len(set(ticket["front"])
                       .intersection(actual["front"])),
                       "back_hits": len(set(ticket["back"]).intersection(actual["back"])),
                       "d2_hit": set(ticket["dan2"]).issubset(actual["front"]),
                       "full_hit": ticket["front"] == actual["front"]
                                   and ticket["back"] == actual["back"]})
    return {"status": "UNVERIFIED_DRAW_INPUT", "game": source["game"],
            "target_issue": source["target_issue"],
            "tickets": scores, "edge": "NO_EDGE"}
