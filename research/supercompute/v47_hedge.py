"""Twenty-two subset/disjoint research models per lottery.

M01+..M11+ include pair A: A subset of actual winning front area.
M01-..M11- exclude pair E: E disjoint from actual winning front area.
A negative event succeeds only when EVERY excluded number is absent.
Twenty-two correlated model signals jointly filter the remaining ticket space.
No demonstrated jackpot edge is assumed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

from research.supercompute.v47_models import (
    SPECS, canonical, inclusion_probabilities, m2_refutation, m3_calibration,
    pair_residuals, seed_from, validate_history, validate_ticket,
)
from research.supercompute.v47_registry import REGISTRY, execute_eleven
from research.supercompute.v47_joint_filter import construct_joint_search, score_joint_search
from research.supercompute.v47_interval_search import (
    calibrate_profiles, construct_interval_search, score_interval_search,
)


def fair_pair(game):
    maximum, picked = SPECS[game][:2]
    included = math.comb(picked, 2) / math.comb(maximum, 2)
    return {"subset": included, "not_subset": 1 - included,
            "disjoint": math.comb(maximum - picked, 2) / math.comb(maximum, 2)}


def _hash(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()[:16]


def _historical_presence(rows, game, area, window, half_life=None):
    maximum, picked = SPECS[game][:2] if area == "front" else SPECS[game][2:]
    sample = rows[-window:]
    counts = [0.0] * (maximum + 1)
    norm = 0.0
    for age, row in enumerate(reversed(sample)):
        weight = 1.0 if half_life is None else 2 ** (-age / half_life)
        norm += weight
        for value in row[area]:
            counts[value] += weight
    return [0.0] + [counts[n] / norm for n in range(1, maximum + 1)]


def evolve_exclusion(rows, game, name, *, seed, generations=2, previous=None):
    """Two-generation actual parent -> crossover -> mutation parameter search.

    Fitness is joint zero-excluded-hits Brier on strictly past-only folds.
    Positive/negative event targets are distinct and cannot share scores.
    """
    if not 1 <= generations <= 5:
        raise ValueError("bad negative-model generations")
    rng = random.Random(seed_from(seed, game, name, rows[-1]["issue"], "anti-cells"))
    seeds = [{"blend": .25, "recent_weight": .3, "pair_weight": .10},
             {"blend": .50, "recent_weight": .5, "pair_weight": .20},
             {"blend": .75, "recent_weight": .7, "pair_weight": .35}]
    if previous is not None:
        if set(previous) != {"blend", "recent_weight", "pair_weight"}:
            raise ValueError("bad previous negative genome")
        seeds.append(dict(previous))
    sample_start = max(60, len(rows) - 7)
    def fitness(g):
        errors = []
        nmax, picked = SPECS[game][:2]
        baseline = fair_pair(game)["disjoint"]
        for i in range(sample_start, len(rows)):
            past, actual = rows[:i], set(rows[i]["front"])
            recent = _historical_presence(past, game, "front", 60)
            aged = _historical_presence(past, game, "front", 120, half_life=30)
            smoothed = [0.0] + [
                (1 - g["recent_weight"]) * picked / nmax
                + g["recent_weight"] * (
                    (1 - g["blend"]) * recent[n] + g["blend"] * aged[n])
                for n in range(1, nmax + 1)]
            sample = past[-60:]
            absent_counts = Counter(
                pair for row in sample for pair in itertools.combinations(
                    sorted(set(range(1, nmax + 1)) - set(row["front"])), 2))
            best = None
            for a, b in itertools.combinations(range(1, nmax + 1), 2):
                historic = ((absent_counts[(a, b)] + 12 * baseline)
                            / (len(sample) + 12))
                marginal_proxy = (1 - smoothed[a]) * (1 - smoothed[b])
                pred = max(1e-5, min(1 - 1e-5,
                    (1 - g["pair_weight"]) * historic
                    + g["pair_weight"] * marginal_proxy))
                candidate = (pred, -a, -b)
                if best is None or candidate > best[0]:
                    best = (candidate, (a, b), pred)
            pair = set(best[1])
            observed = int(pair.isdisjoint(actual))
            errors.append((best[2] - observed) ** 2)
        return statistics.mean(errors)
    lineage = []
    population = [{"genes": g, "origin": "inherited" if previous is not None
                   and i == len(seeds) - 1 else "seed", "parent_ids": []}
                  for i, g in enumerate(seeds)]
    for generation in range(generations):
        scored = []
        for individual in population:
            g = individual["genes"]
            scored.append({**individual, "id": _hash(g), "fitness": fitness(g)})
        scored.sort(key=lambda e: (e["fitness"], e["id"]))
        lineage.append({"generation": generation + 1, "evaluated": scored})
        if generation + 1 == generations:
            break
        parents = scored[:2]
        children = []
        for j in range(4):
            a, b = parents[j % 2], parents[(j + 1) % 2]
            g = {}
            for key in ("blend", "recent_weight", "pair_weight"):
                center = .5 * (a["genes"][key] + b["genes"][key])
                g[key] = round(min(.95, max(.02, center + rng.uniform(-.12, .12))), 6)
            children.append({"genes": g, "origin": "crossover_mutation",
                             "parent_ids": [a["id"], b["id"]]})
        population = [{"genes": x["genes"], "origin": "elite",
                       "parent_ids": [x["id"]]} for x in parents] + children
    winner = min(lineage[-1]["evaluated"], key=lambda e: (e["fitness"], e["id"]))
    return {"champion": winner["genes"], "champion_id": winner["id"],
            "champion_fitness": winner["fitness"], "lineage": lineage,
            "previous_inherited": previous is not None,
            "parent_in_generation_one": any(
                x["origin"] == "inherited" for x in lineage[0]["evaluated"]),
            "uses_future_draws": False}


class NegativeBase:
    """Each subclass supplies its own historical inference weights and method."""
    number, label, method = 0, "", ""

    def _fit(self, history, game, context, *, recent_weight, decay_weight,
             residual_weight, prior, geometry_weight=0., sim_weight=0.):
        validate_history(history, game)
        self.game = game
        self.positive = context["positive"][self.label]["prediction"]
        self.evolution = evolve_exclusion(
            history, game, self.label, seed=context["seed"],
            generations=context["generations"],
            previous=context.get("previous_hedge", {}).get(self.label))
        genome = self.evolution["champion"]
        maximum, picked, backmax, backpick = SPECS[game]
        base = self.positive["marginals"]
        recent = _historical_presence(history, game, "front", 60)
        aged = _historical_presence(history, game, "front", 120, 30)
        back_recent = _historical_presence(history, game, "back", 60)
        residual = pair_residuals(history, game, window=120)
        zone_counts = Counter((n - 1) * 3 // maximum
                              for row in history[-60:] for n in row["front"])
        fair_zone = 60 * picked / 3
        self.anti = [0.0]
        self.candidate = [0.0]
        for n in range(1, maximum + 1):
            recent_p = recent_weight * recent[n] + decay_weight * aged[n]
            recent_p /= max(1e-8, recent_weight + decay_weight)
            prior_p = (len(history[-60:]) * recent_p + prior * picked / maximum) / (len(history[-60:]) + prior)
            pair = sum(residual.get((min(n, j), max(n, j)), 0.0)
                       for j in range(1, maximum + 1) if n != j) / (maximum - 1)
            zone = (n - 1) * 3 // maximum
            density = (zone_counts[zone] - fair_zone) / max(1, fair_zone)
            p = ((1 - genome["blend"]) * base["front"][n]
                 + genome["blend"] * prior_p
                 + residual_weight * pair / maximum
                 + geometry_weight * density / maximum)
            p = max(1e-5, min(1 - 1e-5, p))
            anti = max(1e-5, min(1 - 1e-5, 1 - p))
            self.anti.append(anti)
            self.candidate.append(max(1e-5, min(1 - 1e-5,
                p * (1 - .04 * genome["pair_weight"] * density))))
        self.back = [0.] + [
            max(1e-5, min(1 - 1e-5, .75 * base["back"][n] + .25 * back_recent[n]))
            for n in range(1, backmax + 1)]
        self.residual = residual
        self.params = {"recent_weight": recent_weight, "decay_weight": decay_weight,
                       "residual_weight": residual_weight, "prior": prior,
                       "geometry_weight": geometry_weight,
                       "sim_weight": sim_weight,
                       "strategy": self.method,
                       "anti_champion": genome}
        return {"method": self.method, "params": self.params,
                "cell_evolution": self.evolution,
                "source_positive_model": self.label,
                "trained_anti_probability": self.anti,
                "trained_candidate_probability": self.candidate,
                "historical_window": min(120, len(history)),
                "physical_calibrated": False if self.label == "Physics" else None}

    def predict(self, history, game, context):
        if game != self.game:
            raise ValueError("negative model used without its fit")
        maximum, picked, backmax, backpick = SPECS[game]
        sample = history[-120:]
        prior = 12
        fair = fair_pair(game)
        # Count both absent in each historical draw; not merely one absent.
        absent_counts = Counter(
            pair for row in sample
            for pair in itertools.combinations(
                sorted(set(range(1, maximum + 1)) - set(row["front"])), 2))
        contenders = []
        blend = self.evolution["champion"]["pair_weight"]
        for a, b in itertools.combinations(range(1, maximum + 1), 2):
            observed_joint = (absent_counts[(a, b)] +
                              prior * fair["disjoint"]) / (len(sample) + prior)
            proxy = self.anti[a] * self.anti[b]
            mass = max(1e-5, min(1 - 1e-5,
                (1 - blend) * observed_joint + blend * proxy))
            contenders.append((mass, a, b))
        contenders.sort(key=lambda x: (-x[0], x[1], x[2]))
        disjoint_mass, a, b = contenders[0]
        self.excluded_pair = [a, b]
        # Hard exclusion constrains the candidate ticket, not the actual draw.
        front_pool = sorted((n for n in range(1, maximum + 1)
                             if n not in self.excluded_pair),
                            key=lambda n: (-self.candidate[n], n))[:max(11, picked + 5)]
        back_pool = sorted(range(1, backmax + 1),
                           key=lambda n: (-self.back[n], n))[:max(6, backpick + 3)]
        positive_front = set(self.positive["ticket"]["front"])
        ranked = []
        for combo in itertools.combinations(sorted(front_pool), picked):
            # The negative branch is an actual contrasting position, not
            # merely a second label attached to the positive combination.
            if not set(combo).difference(positive_front):
                continue
            weighted = sum(math.log(max(1e-7, self.candidate[n])) for n in combo)
            pair_bonus = .04 * self.evolution["champion"]["pair_weight"] * sum(
                self.residual[(i, j)] for i, j in itertools.combinations(combo, 2))
            contrast = .035 * len(set(combo).difference(positive_front))
            ranked.append((weighted + pair_bonus + contrast, combo))
        if not ranked:
            raise ValueError("no legal hedge candidate with positive-branch contrast")
        score, front = max(ranked, key=lambda v: (v[0], tuple(-n for n in v[1])))
        back = sorted(sorted(back_pool, key=lambda n: (-self.back[n], n))[:backpick])
        front = sorted(front)
        dan2 = sorted(sorted(front, key=lambda n: (-self.candidate[n], n))[:2])
        ticket = {"front": front, "back": back, "dan2": dan2,
                  "heuristic_score": round(score, 9), "formal_prediction": False}
        validate_ticket(ticket, game)
        if not set(self.excluded_pair).isdisjoint(ticket["front"]):
            raise ValueError("negative exclusion constraint violated")
        return {"ticket": ticket, "excluded_pair": self.excluded_pair,
                "estimated_disjoint_probability": disjoint_mass,
                "anti_marginals": self.anti,
                "candidate_marginals": {"front": self.candidate, "back": self.back},
                "fair_baseline": fair,
                "logical_event": "EXCLUDED_PAIR_DISJOINT_FROM_DRAW",
                "success_requires_zero_excluded_hits": True,
                "candidate_uses_hard_exclusion": True,
                "method": self.method,
                "source_positive_name": self.label,
                "own_cell_champion": self.evolution["champion_id"]}

    def score(self, prediction, actual, game):
        validate_ticket(actual, game)
        ticket = prediction["ticket"]
        validate_ticket(ticket, game)
        excluded = prediction["excluded_pair"]
        if len(excluded) != 2 or len(set(excluded)) != 2:
            raise ValueError("invalid excluded pair")
        included = set(ticket["dan2"]).issubset(actual["front"])
        excluded_hits = len(set(excluded) & set(actual["front"]))
        return {"negative_event_disjoint": excluded_hits == 0,
                "excluded_hits": excluded_hits,
                "partial_exclusion_is_not_success": True,
                "front_hits": len(set(ticket["front"]) & set(actual["front"])),
                "back_hits": len(set(ticket["back"]) & set(actual["back"])),
                "candidate_d2_hit": included,
                "fair_probabilities": fair_pair(game)}


class NegativeHOT60(NegativeBase):
    number, label, method = 1, "HOT60", "anti_frequency_60"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=1., decay_weight=.05,
                         residual_weight=0., prior=3)


class NegativeEWMA(NegativeBase):
    number, label, method = 2, "EWMA", "anti_exponential_decay"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.1, decay_weight=1.,
                         residual_weight=0., prior=5)


class NegativeShrinkMix(NegativeBase):
    number, label, method = 3, "ShrinkMix", "anti_bayesian_prior"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.5, decay_weight=.5,
                         residual_weight=0., prior=90)


class NegativePairwise(NegativeBase):
    number, label, method = 4, "Pairwise-D2", "anti_pair_joint_residual"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.5, decay_weight=.5,
                         residual_weight=-.80, prior=35)


class NegativeChallenger(NegativeBase):
    number, label, method = 5, "Challenger", "evolved_anti_challenger"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.45, decay_weight=.55,
                         residual_weight=-.45, prior=25)


class NegativeStatistics(NegativeBase):
    number, label, method = 6, "Statistics", "anti_joint_statistics"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.35, decay_weight=.65,
                         residual_weight=-.55, prior=60)


class NegativeForecastSearch(NegativeBase):
    number, label, method = 7, "ForecastSearch", "contrastive_anti_search"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.3, decay_weight=.7,
                         residual_weight=-.25, prior=45)


class NegativeGeometry(NegativeBase):
    number, label, method = 8, "Geometry", "anti_zone_geometry"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.55, decay_weight=.45,
                         residual_weight=-.2, prior=30, geometry_weight=-.8)


class NegativeSimulation(NegativeBase):
    number, label, method = 9, "ProbabilitySimulation", "simulation_antitail"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.4, decay_weight=.6,
                         residual_weight=-.35, prior=100, sim_weight=.35)


class NegativePhysics(NegativeBase):
    number, label, method = 10, "Physics", "uncalibrated_physics_nonselection"
    def fit(self, history, game, context):
        if context["positive"]["Physics"]["prediction"].get("calibrated_to_draw_machine") is not False:
            raise ValueError("physics proxy not clearly marked uncalibrated")
        return self._fit(history, game, context, recent_weight=.6, decay_weight=.4,
                         residual_weight=0., prior=100, geometry_weight=.2)


class NegativeValidation(NegativeBase):
    number, label, method = 11, "M1_M2_M3_Validation", "anti_m1_m2_m3_ensemble"
    def fit(self, history, game, context):
        return self._fit(history, game, context, recent_weight=.3, decay_weight=.7,
                         residual_weight=-.18, prior=75)


NEGATIVE_REGISTRY = (
    NegativeHOT60, NegativeEWMA, NegativeShrinkMix, NegativePairwise,
    NegativeChallenger, NegativeStatistics, NegativeForecastSearch,
    NegativeGeometry, NegativeSimulation, NegativePhysics, NegativeValidation,
)
REGISTRY_22 = tuple((f"M{i:02d}{sign}", cls)
    for i, (pos, neg) in enumerate(zip(REGISTRY, NEGATIVE_REGISTRY), 1)
    for sign, cls in (("+", pos), ("-", neg)))


def score_one(record, actual, game):
    if record["direction"] == "subset":
        ticket = record["prediction"]["ticket"]
        return {"subset_event": set(ticket["dan2"]).issubset(actual["front"]),
                "fair_subset": fair_pair(game)["subset"],
                "front_hits": len(set(ticket["front"]) & set(actual["front"])),
                "back_hits": len(set(ticket["back"]) & set(actual["back"]))}
    if record["direction"] == "disjoint":
        return NegativeBase.score(NegativeBase(), record["prediction"], actual, game)
    raise ValueError("unknown hedge direction")


def _run_22_core(rows, game, *, seed, generations, validation, holdout,
                 mc_trials, physics_steps, previous=None):
    prior_base = previous.get("base_champion") if previous else None
    prior_hedges = previous.get("negative_champions", {}) if previous else {}
    base = execute_eleven(
        rows, game, seed=seed, generations=generations,
        validation=validation, holdout=holdout, mc_trials=mc_trials,
        physics_steps=physics_steps, previous_champion=prior_base,
        full_audit=False)
    ctx = {"seed": seed, "generations": generations, "positive": base["models"],
           "previous_hedge": prior_hedges}
    records = []
    for index, (positive_cls, negative_cls) in enumerate(
            zip(REGISTRY, NEGATIVE_REGISTRY), 1):
        original = base["models"][positive_cls.label]
        plus = {"model_id": f"M{index:02d}+", "base_name": positive_cls.label,
                "direction": "subset", "fit": original["fit"],
                "prediction": original["prediction"], "status": "EXECUTED",
                "class": positive_cls.__name__}
        records.append(plus)
        negative = negative_cls()
        fitted = negative.fit(rows, game, ctx)
        prediction = negative.predict(rows, game, ctx)
        validate_ticket(prediction["ticket"], game)
        records.append({"model_id": f"M{index:02d}-",
                        "base_name": negative.label,
                        "direction": "disjoint", "fit": fitted,
                        "prediction": prediction, "status": "EXECUTED",
                        "class": type(negative).__name__})
    if len(records) != 22 or [x["model_id"] for x in records] != [x[0] for x in REGISTRY_22]:
        raise ValueError("missing genuine 22 model branches")
    return base, records


def historical_audit(rows, game, *, seed, holdout, validation, mc_trials,
                     physics_steps):
    """22 separate model events on trailing past-only draws; no forecast leakage."""
    if holdout < 3:
        raise ValueError("need two calibration folds and one independent test fold")
    fair = fair_pair(game)
    series = {name: [] for name, _ in REGISTRY_22}
    fold_issues = []
    joint_folds = []
    interval_folds = []
    for idx in range(len(rows) - holdout, len(rows)):
        past, actual = rows[:idx], rows[idx]
        _, predictions = _run_22_core(
            past, game, seed=seed, generations=1,
            validation=min(validation, 4), holdout=2,
            mc_trials=min(mc_trials, 40), physics_steps=min(physics_steps, 5))
        fold_issues.append({"train_last": str(past[-1]["issue"]),
                            "test_issue": str(actual["issue"]),
                            "test_ignored_during_fit": True})
        interval_folds.append({"records": predictions, "actual": actual})
        joint_prediction = construct_joint_search(predictions, game, limit=8)
        joint_result = score_joint_search(joint_prediction, actual, game)
        joint_folds.append({
            "history_last_issue": str(past[-1]["issue"]),
            "actual_issue": str(actual["issue"]),
            "events": joint_result,
            "retained_front": joint_prediction["retained_front_combinations"],
            "required": joint_prediction["constraints"]["required"],
            "excluded": joint_prediction["constraints"]["excluded"]})
        for item in predictions:
            event = score_one(item, actual, game)
            is_positive = item["direction"] == "subset"
            observed = int(event["subset_event"] if is_positive
                           else event["negative_event_disjoint"])
            empirical = (fair["subset"] if is_positive else fair["disjoint"])
            if is_positive:
                selected = item["prediction"]["ticket"]["dan2"]
                sample = past[-120:]
                pair_hits = sum(set(selected).issubset(x["front"]) for x in sample)
                smoothed_joint = (pair_hits + 24 * fair["subset"]) / (len(sample) + 24)
                marg = item["prediction"]["marginals"]["front"]
                independent_proxy = marg[selected[0]] * marg[selected[1]]
                predicted = max(1e-5, min(1 - 1e-5,
                    .7 * smoothed_joint + .3 * independent_proxy))
            else:
                predicted = item["prediction"]["estimated_disjoint_probability"]
            series[item["model_id"]].append((predicted, observed, empirical))
    audits = {}
    for name, samples in series.items():
        training, test = samples[:-1], samples[-1:]
        best = min((0., .25, .5, .75, 1.), key=lambda lam: (
            statistics.mean(((1 - lam) * fairp + lam * p - y) ** 2
                            for p, y, fairp in training), lam))
        calibrated = [(fairp + best * (p - fairp), y)
                      for p, y, fairp in test]
        positive = name.endswith("+")
        fair_prob = fair["subset"] if positive else fair["disjoint"]
        audits[name] = {"M1": {"status": "PASS", "legal": True},
            "M2": m2_refutation([y for _, y, _ in samples], fair_prob),
            "M3": {"status": "PASS", "calibration": "chronological_shrink_to_fair",
                   "trained_on_past_folds": len(training),
                   "tested_on_heldout_folds": 1, "lambda": best,
                   "raw": m3_calibration([(p, y) for p, y, _ in test]),
                   "calibrated": m3_calibration(calibrated)},
            "fair_event_probability": fair_prob,
            "direction": "subset" if positive else "disjoint",
            "not_prospective_edge": True}
    interval_calibration = calibrate_profiles(interval_folds, game)
    return {"status": "PASS", "models": audits, "model_count": 22,
            "interval_calibration": interval_calibration,
            "folds": fold_issues, "joint": {
                "folds": joint_folds,
                "survived_count": sum(int(x["events"]["joint_filter_keeps_actual_front"])
                                      for x in joint_folds),
                "full_jackpot_hits": sum(x["events"]["exact_jackpot_ticket_hits"]
                                          for x in joint_folds),
                "fair_reference":
                    math.comb(SPECS[game][0] - 4, SPECS[game][1] - 2)
                    / math.comb(SPECS[game][0], SPECS[game][1]),
                "status": "EXPLORATORY_TOO_FEW_FOLDS_FOR_EDGE"},
            "multiple_tests_adjusted": False,
            "no_future_draws": True, "edge": "NO_EDGE"}


def run_hedge22(rows, game, target, *, seed=2026, generations=2,
                validation=4, holdout=3, mc_trials=100, physics_steps=8,
                previous=None):
    validate_history(rows, game)
    if str(target) == str(rows[-1]["issue"]):
        raise ValueError("cannot target latest already-known issue")
    base, records = _run_22_core(
        rows, game, seed=seed, generations=generations,
        validation=validation, holdout=holdout,
        mc_trials=mc_trials, physics_steps=physics_steps, previous=previous)
    audit = historical_audit(rows, game, seed=seed, holdout=holdout,
                             validation=validation, mc_trials=mc_trials,
                             physics_steps=physics_steps)
    joint = construct_joint_search(records, game, limit=8)
    interval_search = construct_interval_search(
        records, game, audit["interval_calibration"]["profile"], limit=8)
    interval_search["calibration"] = audit["interval_calibration"]
    tickets = []
    for record in records:
        ticket = dict(record["prediction"]["ticket"])
        ticket.update({"model_id": record["model_id"],
                       "base_name": record["base_name"],
                       "direction": record["direction"]})
        if record["direction"] == "disjoint":
            ticket["excluded_pair"] = record["prediction"]["excluded_pair"]
        tickets.append(ticket)
    return {"schema": "SSQDLT_V47_HEDGE22_GAME_V2",
            "game": game, "target_issue": str(target),
            "history_last_issue": str(rows[-1]["issue"]),
            "history_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
            "edge": "NO_EDGE", "formal_prediction": False,
            "models": {r["model_id"]: r for r in records},
            "model_count": 22, "ticket_count": 22,
            "tickets": tickets, "joint_search": joint,
            "interval_search": interval_search,
            "historical_validation": audit,
            "evolution": {
                "base_champion": base["champion_genome"],
                "negative_champions": {
                    r["base_name"]: r["fit"]["cell_evolution"]["champion"]
                    for r in records if r["direction"] == "disjoint"},
                "negative_lineages": {
                    r["model_id"]: r["fit"]["cell_evolution"]
                    for r in records if r["direction"] == "disjoint"}}}


def score_frozen(path, expected_sha256, actual):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("frozen 22-model SHA mismatch")
    doc = json.loads(raw)
    if doc.get("schema") not in ("SSQDLT_V47_HEDGE22_FROZEN_V1",
                                 "SSQDLT_V47_HEDGE22_FROZEN_V2"):
        raise ValueError("wrong frozen schema")
    payload = doc["source"]
    game = payload["game"]
    if str(actual.get("issue")) != payload["target_issue"]:
        raise ValueError("actual issue is not prediction target")
    validate_ticket(actual, game)
    if (doc["schema"] == "SSQDLT_V47_HEDGE22_FROZEN_V2"
            and "joint_search" not in payload):
        raise ValueError("strict-disjoint freeze is missing its joint search")
    strict = doc["schema"] == "SSQDLT_V47_HEDGE22_FROZEN_V2"
    if not strict:
        # Immutable old frozen forecasts must stay scoreable, but NEVER
        # rebrand their partial-exclusion target as a strict M- success.
        results = {}
        for name, record in payload["models"].items():
            if record["direction"] == "not_subset":
                ex = set(record["prediction"]["excluded_pair"])
                hits = len(ex.intersection(actual["front"]))
                results[name] = {
                    "legacy_partial_exclusion_success": hits < len(ex),
                    "reference_disjoint_success_not_original_objective": hits == 0,
                    "excluded_hits": hits,
                    "legacy_incompatible_with_strict_m_minus": True}
            else:
                results[name] = score_one(record, actual, game)
        return {"schema": "SSQDLT_V47_HEDGE22_LEGACY_SCORE_V1",
                "status": "LEGACY_PARTIAL_EXCLUSION_SCORED_UNVERIFIED",
                "game": game, "target_issue": payload["target_issue"],
                "source_sha256": expected_sha256, "edge": "NO_EDGE",
                "count": 22, "models": results, "strict_disjoint_verified": False}
    return {"schema": "SSQDLT_V47_HEDGE22_SCORE_V2",
            "status": "SCORED_WITH_SUPPLIED_DRAW_UNVERIFIED",
            "game": game, "target_issue": payload["target_issue"],
            "source_sha256": expected_sha256, "edge": "NO_EDGE",
            "count": 22, "models": {
                name: score_one(record, actual, game)
                for name, record in payload["models"].items()},
            "joint": score_joint_search(payload["joint_search"], actual, game),
            "interval": (score_interval_search(payload["interval_search"], actual, game)
                         if "interval_search" in payload else {
                             "status": "NOT_AVAILABLE_IN_OLD_V2_FREEZE"}),
            "strict_disjoint_verified": True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--game", choices=("both", "ssq", "dlt"), default="both")
    g.add_argument("--ssq-data", type=Path)
    g.add_argument("--dlt-data", type=Path)
    g.add_argument("--ssq-target")
    g.add_argument("--dlt-target")
    g.add_argument("--output", type=Path, required=True)
    g.add_argument("--freeze-dir", type=Path, required=True)
    g.add_argument("--previous", type=Path)
    g.add_argument("--seed", type=int, default=2026)
    g.add_argument("--generations", type=int, default=2)
    g.add_argument("--validation", type=int, default=4)
    g.add_argument("--holdout", type=int, default=3)
    g.add_argument("--mc-trials", type=int, default=100)
    g.add_argument("--physics-steps", type=int, default=8)
    sc = sub.add_parser("score")
    sc.add_argument("--frozen", type=Path, required=True)
    sc.add_argument("--sha256", required=True)
    sc.add_argument("--actual", type=Path, required=True)
    args = p.parse_args(argv)
    if args.command == "score":
        print(json.dumps(score_frozen(args.frozen, args.sha256,
                                     json.loads(args.actual.read_bytes())),
                         ensure_ascii=False))
        return
    selected = ("ssq", "dlt") if args.game == "both" else (args.game,)
    for game in selected:
        if getattr(args, game + "_data") is None or not getattr(args, game + "_target"):
            raise ValueError("a data path and target issue are required per selected game")
    previous = json.loads(args.previous.read_bytes()) if args.previous else None
    if previous and previous.get("schema") == "SSQDLT_V47_HEDGE22_FROZEN_V2":
        previous = {"schema": "SSQDLT_V47_HEDGE22_RUN_V2",
                    "games": {previous["source"]["game"]: previous["source"]}}
    if previous and previous.get("schema") not in (
            "SSQDLT_V47_HEDGE44_RUN_V2", "SSQDLT_V47_HEDGE22_RUN_V2"):
        raise ValueError("previous hedge run has incompatible schema")
    games = {}
    for game in selected:
        data = json.loads(getattr(args, game + "_data").read_bytes())
        rows = data["draws"]
        prior = previous["games"][game]["evolution"] if previous else None
        games[game] = run_hedge22(rows, game,
                                  getattr(args, game + "_target"),
                                  seed=args.seed, generations=args.generations,
                                  validation=args.validation, holdout=args.holdout,
                                  mc_trials=args.mc_trials,
                                  physics_steps=args.physics_steps,
                                  previous=prior)
    count = sum(v["ticket_count"] for v in games.values())
    report = {"schema": ("SSQDLT_V47_HEDGE44_RUN_V2"
                         if len(games) == 2 else "SSQDLT_V47_HEDGE22_RUN_V2"),
              "games": games, "model_count_per_game": 22,
              "ticket_count": count, "edge": "NO_EDGE",
              "formal_prediction": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as f:
        f.write(canonical(report))
    freezes = {}
    for game, source in games.items():
        doc = {"schema": "SSQDLT_V47_HEDGE22_FROZEN_V2",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "source": source, "formal_prediction": False,
               "external_predraw_seal": False}
        path = args.freeze_dir / f"{game}-{source['target_issue']}-hedge22.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as f:
            f.write(canonical(doc))
        freezes[game] = {"path": str(path),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    print(("V47_HEDGE44_RESULT=" if len(games) == 2 else "V47_HEDGE22_RESULT=")
          + json.dumps({
        "count": count, "frozen": freezes,
        "report_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "games": {game: {"target": v["target_issue"],
                        "history_asof": v["history_last_issue"],
                        "count": v["ticket_count"],
                        "m2_count": len(v["historical_validation"]["models"]),
                        "joint": {
                            "required": v["joint_search"]["constraints"]["required"],
                            "excluded": v["joint_search"]["constraints"]["excluded"],
                            "retained_front": v["joint_search"]["retained_front_combinations"],
                            "original_front": v["joint_search"]["original_front_combinations"],
                            "ranked_tickets": v["joint_search"]["tickets"]},
                        "interval": {
                            "profile": v["interval_search"]["profile"],
                            "front": v["interval_search"]["areas"]["front"],
                            "back": v["interval_search"]["areas"]["back"],
                            "retained_full": v["interval_search"]["retained_full_ticket_combinations"],
                            "original_full": v["interval_search"]["original_full_ticket_combinations"],
                            "heldout": v["historical_validation"]["interval_calibration"]["heldout_outcome"],
                            "ranked_tickets": v["interval_search"]["tickets"]},
                        "tickets": v["tickets"]}
                  for game, v in games.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
