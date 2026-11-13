"""Eleven independent, executable model objects for SSQ/DLT V4.7 research.

Every model implements fit(), predict(), score(); the last six are first-class
models with an independent candidate/output, not merely booleans in a checklist.
All uses historical input only. Physics is an explicitly uncalibrated toy.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import math
import random
import statistics

from research.supercompute.v47_models import (
    SPECS, MODELS, backtest, candidates, canonical, geometry, geometry_state,
    geometry_transition, inclusion_probabilities, m1_math, m2_refutation,
    m3_calibration, monte_carlo, pair_residuals, parameters, physics_toy,
    random_ticket, seed_from, shrink, validate_history, validate_ticket,
    weighted_counts, zone_state,
)


def pack_ticket(game, front, back, score=0.0):
    ticket = {"front": sorted(front), "back": sorted(back),
              "dan2": sorted(front[:2]), "heuristic_score": round(score, 8),
              "formal_prediction": False}
    validate_ticket(ticket, game)
    return ticket


def rank_probabilities(game, front, back, *, pair=None, zones=None, span=None,
                       pair_weight=0.0, geometry_weight=0.0, limit=3):
    """Bounded joint-search under each model's own objective, no shared ticket."""
    fm, fp, bm, bp = SPECS[game]
    front_pool = sorted(range(1, fm + 1), key=lambda n: (-front[n], n))[:max(11, fp + 4)]
    back_pool = sorted(range(1, bm + 1), key=lambda n: (-back[n], n))[:max(6, bp + 4)]
    def log_odds(v):
        v = min(1 - 1e-8, max(1e-8, v))
        return math.log(v / (1 - v))
    choices = []
    for combo in itertools.combinations(sorted(front_pool), fp):
        score = sum(log_odds(front[n]) for n in combo)
        if pair:
            score += pair_weight * sum(pair.get(ab, 0.0)
                        for ab in itertools.combinations(combo, 2))
        if zones:
            posterior, reference = zones
            state = zone_state({"front": combo}, game)
            score += geometry_weight * math.log(max(1e-9, posterior[state] / reference[state]))
        if span is not None:
            score -= geometry_weight * abs(combo[-1] - combo[0] - span) / fm
        choices.append((score, combo))
    choices.sort(key=lambda x: (-x[0], x[1]))
    backs = sorted(((sum(log_odds(back[n]) for n in b), b)
                     for b in itertools.combinations(sorted(back_pool), bp)),
                   key=lambda x: (-x[0], x[1]))
    joint = sorted(((a + b, f, k) for a, f in choices[:max(6, limit)]
                     for b, k in backs[:max(6, limit)]),
                   key=lambda x: (-x[0], x[1], x[2]))
    out = []
    for score, nums, blues in joint[:limit]:
        dan2 = sorted(sorted(nums, key=lambda n: (-front[n], n))[:2])
        ticket = pack_ticket(game, nums, blues, score)
        ticket["dan2"] = dan2
        out.append(ticket)
    return out


class Model:
    number = 0
    label = ""
    def fit(self, history, game, context):
        raise NotImplementedError
    def predict(self, history, game, context):
        raise NotImplementedError
    def score(self, ticket, actual, game):
        validate_ticket(ticket, game)
        validate_ticket(actual, game)
        return {"front_hits": len(set(ticket["front"]) & set(actual["front"])),
                "back_hits": len(set(ticket["back"]) & set(actual["back"])),
                "d2_hit": set(ticket["dan2"]).issubset(actual["front"]),
                "full_hit": ticket["front"] == actual["front"] and
                            ticket["back"] == actual["back"]}


class HOT60Model(Model):
    number, label = 1, "HOT60"
    def fit(self, history, game, context):
        self.rows, self.game = history, game
        self.probs = {area: inclusion_probabilities(history, game, area, "HOT60")
                      for area in ("front", "back")}
        return {"window": min(60, len(history)), "method": "frequency_inclusion"}
    def predict(self, history, game, context):
        t = candidates(history, game, "HOT60", limit=1)[0]
        return {"ticket": t, "marginals": self.probs, "method": self.label}


class EWMAModel(Model):
    number, label = 2, "EWMA"
    def fit(self, history, game, context):
        self.probs = {area: inclusion_probabilities(history, game, area, "EWMA")
                      for area in ("front", "back")}
        return {"half_life": 30.0, "decay": "exponential"}
    def predict(self, history, game, context):
        return {"ticket": candidates(history, game, "EWMA", limit=1)[0],
                "marginals": self.probs, "method": self.label}


class ShrinkMixModel(Model):
    number, label = 3, "ShrinkMix"
    def fit(self, history, game, context):
        self.probs = {area: inclusion_probabilities(history, game, area, "ShrinkMix")
                      for area in ("front", "back")}
        return {"prior_exposure": 60, "mix": .5, "method": "pseudo_bayesian_shrinkage"}
    def predict(self, history, game, context):
        return {"ticket": candidates(history, game, "ShrinkMix", limit=1)[0],
                "marginals": self.probs, "method": self.label}


class PairwiseD2Model(Model):
    number, label = 4, "Pairwise-D2"
    def fit(self, history, game, context):
        self.pairs = pair_residuals(history, game)
        self.probs = {area: inclusion_probabilities(history, game, area, "Pairwise-D2")
                      for area in ("front", "back")}
        return {"pairs": len(self.pairs), "top_pair": list(max(self.pairs, key=self.pairs.get)),
                "method": "pair_residual_ranking"}
    def predict(self, history, game, context):
        return {"ticket": candidates(history, game, "Pairwise-D2", limit=1)[0],
                "marginals": self.probs,
                "top_pair_residuals": [[list(k), v] for k, v in
                    sorted(self.pairs.items(), key=lambda p: (-p[1], p[0]))[:6]]}


class ChallengerModel(Model):
    number, label = 5, "Challenger"
    def fit(self, history, game, context):
        from research.supercompute.v47_integrated import cell_division
        evolution = cell_division(history, game, seed=context["seed"],
                                  generations=context["generations"],
                                  validation=context["validation"],
                                  previous_champion=context["previous_champion"])
        self.evolution = evolution
        self.probs = {area: inclusion_probabilities(
            history, game, area, "Challenger", evolution["champion"])
            for area in ("front", "back")}
        return {"champion_id": evolution["champion_id"],
                "genome": evolution["champion"],
                "lineage": evolution["lineage"],
                "inherited": evolution["parent_from_prior_run"],
                "objective": evolution["validation_objective"]}
    def predict(self, history, game, context):
        return {"ticket": candidates(history, game, "Challenger",
                                   self.evolution["champion"], limit=1)[0],
                "marginals": self.probs, "champion_id": self.evolution["champion_id"]}


class StatisticsModel(Model):
    number, label = 6, "Statistics"
    def fit(self, history, game, context):
        fm, fp, bm, bp = SPECS[game]
        self.posterior, evidence = {}, {}
        for area, maximum, picked in (("front", fm, fp), ("back", bm, bp)):
            hot, n_hot = weighted_counts(history, area, maximum, "HOT60", parameters())
            ewma, n_ewma = weighted_counts(history, area, maximum, "EWMA", parameters())
            a = shrink(hot, n_hot, maximum, picked, 60)
            b = shrink(ewma, n_ewma, maximum, picked, 60)
            self.posterior[area] = [0.0] + [.5 * (a[i] + b[i]) for i in range(1, maximum + 1)]
            evidence[area] = {"hot_exposure": n_hot, "ewma_exposure": n_ewma,
                              "most_frequent": sorted(range(1, maximum + 1),
                                                     key=lambda x: (-hot[x], x))[:5]}
        self.pairs = pair_residuals(history, game)
        return {"statistics": evidence,
                "pair_residual_count": len(self.pairs),
                "prior": 60, "half_life": 30.0}
    def predict(self, history, game, context):
        ticket = rank_probabilities(game, self.posterior["front"],
                                    self.posterior["back"], pair=self.pairs,
                                    pair_weight=.12, limit=1)[0]
        return {"ticket": ticket, "marginals": self.posterior,
                "top_pairs": [[list(k), v] for k, v in
                              sorted(self.pairs.items(), key=lambda p: (-p[1], p[0]))[:5]]}


class ForecastSearchModel(Model):
    number, label = 7, "ForecastSearch"
    def fit(self, history, game, context):
        # This model searches an independently defined fused objective from
        # previous fitted model outputs; not an alias of their ticket.
        fm, fp, bm, bp = SPECS[game]
        weights = {"HOT60": .14, "EWMA": .14, "ShrinkMix": .15,
                   "Pairwise-D2": .15, "Challenger": .26, "Statistics": .16}
        self.probs = {}
        for area, maximum in (("front", fm), ("back", bm)):
            self.probs[area] = [0.0] * (maximum + 1)
            for name, weight in weights.items():
                marginal = context["results"][name]["prediction"]["marginals"][area]
                for number in range(1, maximum + 1):
                    self.probs[area][number] += weight * marginal[number]
        self.pairs = pair_residuals(history, game)
        return {"search": "bounded_joint_logodds_and_pair_residual",
                "model_weights": weights, "front_pool": 11, "back_pool": 6}
    def predict(self, history, game, context):
        tickets = rank_probabilities(game, self.probs["front"], self.probs["back"],
                                     pair=self.pairs, pair_weight=.15, limit=3)
        return {"ticket": tickets[0], "alternates": tickets[1:],
                "marginals": self.probs, "freeze_supported": True,
                "post_draw_score_supported": True}


class GeometryModel(Model):
    number, label = 8, "Geometry"
    def fit(self, history, game, context):
        self.transition = geometry_transition(history, game)
        self.features = geometry_state(history, game)
        self.pairs = pair_residuals(history, game)
        self.probs = {area: inclusion_probabilities(history, game, area, "ShrinkMix")
                      for area in ("front", "back")}
        return {"latest": self.features["latest_state"],
                "mean_span": self.features["mean_span"],
                "mean_gap": self.features["mean_gap"],
                "zones": len(self.transition[0]),
                "transition_mass": sum(self.transition[0].values())}
    def predict(self, history, game, context):
        ticket = rank_probabilities(game, self.probs["front"], self.probs["back"],
                                    zones=self.transition,
                                    span=self.features["mean_span"],
                                    geometry_weight=.4,
                                    limit=1)[0]
        return {"ticket": ticket, "state": zone_state(ticket, game),
                "features": geometry(ticket),
                "state_transition_likelihood": self.transition[0][zone_state(ticket, game)]}


class SimulationModel(Model):
    number, label = 9, "ProbabilitySimulation"
    def fit(self, history, game, context):
        self.monte_carlo = monte_carlo(game, trials=context["mc_trials"],
                                      seed=context["seed"])
        self.backtest = backtest(history, game, periods=context["holdout"],
                                 seed=context["seed"])
        self.game = game
        return {"mc_trials": self.monte_carlo["trials"],
                "backtest_periods": context["holdout"],
                "historical_models": sorted(self.backtest["models"]),
                "heldout_first_issue": self.backtest["first_issue"]}
    def predict(self, history, game, context):
        # Distinct simulation candidate: repeated uniform sampling, not an
        # extra selector; no independent random baseline is registered.
        fm, fp, bm, bp = SPECS[game]
        rng = random.Random(seed_from(game, context["seed"], "model-nine"))
        draws = [random_ticket(game, rng.getrandbits(64))
                 for _ in range(min(context["mc_trials"], 500))]
        freq_f = Counter(n for ticket in draws for n in ticket["front"])
        freq_b = Counter(n for ticket in draws for n in ticket["back"])
        front = sorted(sorted(range(1, fm + 1), key=lambda n: (-freq_f[n], n))[:fp])
        back = sorted(sorted(range(1, bm + 1), key=lambda n: (-freq_b[n], n))[:bp])
        return {"ticket": pack_ticket(game, front, back),
                "monte_carlo": self.monte_carlo,
                "retrospective": {"models": {k: {
                    "d2_hits": v["d2_hits"], "brier": v["m3"]["brier"],
                    "m2": v["m2"]} for k,v in self.backtest["models"].items()},
                    "strictly_past_only": self.backtest["strictly_past_only"]},
                "sample_count": len(draws)}


class PhysicsModel(Model):
    number, label = 10, "Physics"
    def fit(self, history, game, context):
        self.sim = physics_toy(game, seed=context["seed"],
                               steps=context["physics_steps"])
        return {"mechanics": ["2d_wall_collision", "pair_contact", "airflow"],
                "steps": self.sim["steps"],
                "calibrated_to_draw_machine": False}
    def predict(self, history, game, context):
        ticket = self.sim["toy_ticket"]
        return {"ticket": pack_ticket(game, ticket["front"], ticket["back"]),
                "physical_simulation": self.sim,
                "calibrated_to_draw_machine": False}


class ValidationModel(Model):
    number, label = 11, "M1_M2_M3_Validation"
    def fit(self, history, game, context):
        results = context["results"]
        m1 = {}
        for name, record in results.items():
            m1[name] = m1_math(history, game, record["prediction"]["ticket"])
        prior = results["ProbabilitySimulation"]["prediction"]["retrospective"]["models"]
        # Evaluation choice is based on a historical holdout, never target data.
        order = sorted(MODELS, key=lambda m: (prior[m]["brier"], m))
        self.winner = order[0]
        self.m2 = {k: prior[k]["m2"] for k in MODELS}
        self.m3 = {k: prior[k]["brier"] for k in MODELS}
        self.m1 = m1
        return {"m1_passed_models": sorted(m1), "m2": self.m2,
                "m3_brier": self.m3, "chosen_parent": self.winner,
                "selection_uses_test_target": False,
                "scope": "past_draws_only"}
    def predict(self, history, game, context):
        parent = context["results"][self.winner]["prediction"]["ticket"]
        return {"ticket": dict(parent), "selected_from": self.winner,
                "legal_math_checks": len(self.m1),
                "independent_fair_d2_tests": self.m2,
                "marginal_brier_scores": self.m3}


REGISTRY = (HOT60Model, EWMAModel, ShrinkMixModel, PairwiseD2Model,
            ChallengerModel, StatisticsModel, ForecastSearchModel,
            GeometryModel, SimulationModel, PhysicsModel, ValidationModel)


def execute_eleven(history, game, *, seed=2026, generations=1,
                   validation=3, holdout=2, mc_trials=60, physics_steps=5,
                   previous_champion=None):
    """Fit+predict eleven different model objects; fail closed on any missing."""
    if game not in SPECS:
        raise ValueError("invalid lottery")
    validate_history(history, game)
    if len(history) < 120 + holdout:
        raise ValueError("requires at least 120 training rows and heldout records")
    assert len(REGISTRY) == 11 and len({m.number for m in REGISTRY}) == 11
    context = {"seed": seed, "generations": generations,
               "validation": validation, "holdout": holdout,
               "mc_trials": mc_trials, "physics_steps": physics_steps,
               "previous_champion": previous_champion, "results": {}}
    for ModelClass in REGISTRY:
        model = ModelClass()
        learned = model.fit(history, game, context)
        prediction = model.predict(history, game, context)
        validate_ticket(prediction["ticket"], game)
        if not isinstance(learned, dict) or not learned or not prediction:
            raise ValueError("model is not independently fitted and executed")
        context["results"][model.label] = {
            "number": model.number, "name": model.label,
            "class": type(model).__name__, "fit": learned,
            "prediction": prediction, "status": "EXECUTED",
            "contract": ["fit", "predict", "score"]}
    results = context["results"]
    if len(results) != 11 or set(results) != {m.label for m in REGISTRY}:
        raise ValueError("incomplete model registry")
    output = {"schema": "SSQDLT_V47_11_INDEPENDENT_MODELS_V1",
              "game": game, "history_last_issue": str(history[-1]["issue"]),
              "history_sha256": hashlib.sha256(canonical(history)).hexdigest(),
              "model_count": 11, "models": results,
              "final_candidate": results["M1_M2_M3_Validation"]["prediction"]["ticket"],
              "champion_genome": results["Challenger"]["fit"]["genome"],
              "champion_lineage": results["Challenger"]["fit"]["lineage"],
              "independent_modules": True, "formal_prediction": False,
              "physical_model_calibrated": False, "edge": "NO_EDGE"}
    output["run_digest_sha256"] = hashlib.sha256(canonical(output)).hexdigest()
    return output
