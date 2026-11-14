"""Experimental SSQ/DLT research models; NEVER a verified predraw forecast.

Independent module: it neither changes official V4.7 selectors nor writes to
the formal freeze/NULL ledgers. All hyperparameter selection precedes test data.
Standard library only; supports Python 3.11+.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, date
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

SPECS = {"ssq": (33, 6, 16, 1), "dlt": (35, 5, 12, 2)}
MODELS = ("HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger")
DEFAULT = {"window": 60, "half_life": 30.0, "prior": 60.0, "mix": 0.5,
           "pair_weight": 0.12, "geo_weight": 0.0}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def seed_from(*values):
    return int.from_bytes(hashlib.sha256(canonical(values)).digest()[:8], "big")


def parameters(overrides=None):
    p = dict(DEFAULT, **(overrides or {}))
    if (type(p["window"]) is not int or not 1 <= p["window"] <= 2000
            or not 1 <= p["half_life"] <= 1000 or not 0 <= p["prior"] <= 10000
            or not 0 <= p["mix"] <= 1 or not 0 <= p["pair_weight"] <= 2
            or not 0 <= p["geo_weight"] <= 2
            or any(not math.isfinite(float(v)) for v in p.values())):
        raise ValueError("invalid model parameters")
    return p


def validate_ticket(value, game):
    if game not in SPECS or not isinstance(value, dict):
        raise ValueError("invalid game/ticket")
    fm, fp, bm, bp = SPECS[game]
    for area, count, maximum in (("front", fp, fm), ("back", bp, bm)):
        balls = value.get(area)
        if (not isinstance(balls, list) or len(balls) != count
                or any(type(x) is not int for x in balls)
                or balls != sorted(set(balls))
                or any(x < 1 or x > maximum for x in balls)):
            raise ValueError("invalid " + area)
    return True


def validate_history(rows, game):
    if not isinstance(rows, list):
        raise ValueError("history must be list")
    seen, last, last_issue = set(), None, None
    for row in rows:
        validate_ticket(row, game)
        issue = str(row["issue"])
        day = date.fromisoformat(str(row["draw_date"]))
        if (not issue.isdigit() or issue in seen
                or (last is not None and day <= last)
                or (last_issue is not None and int(issue) <= last_issue)):
            raise ValueError("history unordered/duplicate")
        seen.add(issue)
        last = day
        last_issue = int(issue)
    return True


def weighted_counts(rows, area, maximum, family, p):
    if family == "HOT60":
        weighted = ((row, 1.0) for row in rows[-p["window"]:])
    else:
        recent = rows[-720:]
        weighted = ((row, 2 ** (-age / p["half_life"]))
                    for age, row in enumerate(reversed(recent)))
    counts, exposure = [0.0] * (maximum + 1), 0.0
    for row, w in weighted:
        exposure += w
        for x in row[area]:
            counts[x] += w
    return counts, exposure


def shrink(counts, exposure, maximum, picked, prior):
    fair = picked / maximum
    if exposure + prior == 0:
        return [0.0] + [fair] * maximum
    return [0.0] + [(counts[x] + prior * fair) / (exposure + prior)
                    for x in range(1, maximum + 1)]


def inclusion_probabilities(rows, game, area, model, opts=None):
    """Marginal inclusion P(ball appears), not independent joint ticket odds."""
    if game not in SPECS or area not in ("front", "back") or model not in MODELS:
        raise ValueError("unknown game/area/model")
    p = parameters(opts)
    maximum, picked = SPECS[game][:2] if area == "front" else SPECS[game][2:]
    a, na = weighted_counts(rows, area, maximum, "HOT60", p)
    b, nb = weighted_counts(rows, area, maximum, "EWMA", p)
    if model == "HOT60":
        probs = shrink(a, na, maximum, picked, 0)
    elif model == "EWMA":
        probs = shrink(b, nb, maximum, picked, 0)
    else:
        # Empirical long-history prior, itself smoothed by one fair exposure.
        long_counts = Counter(n for row in rows for n in row[area])
        baseline = [0.0] + [(long_counts[i] + picked / maximum) / (len(rows)+1)
                            for i in range(1, maximum+1)]
        x = [0.0] + [(a[i]+p['prior']*baseline[i]) / (na+p['prior'])
                    if na+p['prior'] else picked/maximum for i in range(1,maximum+1)]
        y = [0.0] + [(b[i]+p['prior']*baseline[i]) / (nb+p['prior'])
                    if nb+p['prior'] else picked/maximum for i in range(1,maximum+1)]
        probs = [0.0] + [p["mix"] * x[i] + (1 - p["mix"]) * y[i]
                         for i in range(1, maximum + 1)]
    if not (all(0 <= x <= 1 for x in probs)
            and math.isclose(sum(probs), picked, abs_tol=1e-8)):
        raise ValueError("probability normalization failed")
    return probs


def pair_residuals(rows, game, area="front", window=120):
    maximum, picked = SPECS[game][:2] if area == "front" else SPECS[game][2:]
    sample = rows[-window:]
    expected = len(sample) * picked * (picked - 1) / (maximum * (maximum - 1))
    observed = Counter(pair for row in sample
                       for pair in itertools.combinations(row[area], 2))
    return {pair: (observed[pair] - expected) / math.sqrt(max(1.0, expected))
            for pair in itertools.combinations(range(1, maximum + 1), 2)}


def geometry(draw):
    nums = draw["front"]
    gaps = [b - a for a, b in zip(nums, nums[1:])]
    return {"span": nums[-1] - nums[0], "gaps": gaps,
            "centroid": statistics.mean(nums), "mean_gap": statistics.mean(gaps),
            "even": sum(x % 2 == 0 for x in nums)}


def zone_state(draw, game):
    maximum = SPECS[game][0]
    return tuple(sum((n - 1) * 3 // maximum == z for n in draw["front"])
                 for z in range(3))


def geometry_state(rows, game, window=60):
    recent = rows[-window:]
    if not recent:
        return {"samples": 0, "transitions": {}}
    states = [zone_state(row, game) for row in recent]
    pairs = Counter((a, b) for a, b in zip(states, states[1:]))
    return {"samples": len(recent),
            "mean_span": statistics.mean(geometry(row)["span"] for row in recent),
            "mean_gap": statistics.mean(geometry(row)["mean_gap"] for row in recent),
            "latest_state": states[-1],
            "transitions": {str(k): v for k, v in pairs.items()}}


def geometry_transition(rows, game, prior=25.0):
    """Past-only transition estimate smoothed by exact fair-draw state mass."""
    maximum, picked, _, _ = SPECS[game]
    capacities = [sum((n - 1) * 3 // maximum == z
                      for n in range(1, maximum + 1)) for z in range(3)]
    base = {}
    for a in range(picked + 1):
        for b in range(picked - a + 1):
            c = picked - a - b
            if all(k <= v for k, v in zip((a, b, c), capacities)):
                base[(a, b, c)] = math.prod(math.comb(v, k)
                                           for v, k in zip(capacities, (a, b, c))) / math.comb(maximum, picked)
    if not rows:
        return base, base
    current = zone_state(rows[-1], game)
    recent = rows[-181:]
    counts = Counter(zone_state(nxt, game)
                     for prev, nxt in zip(recent, recent[1:])
                     if zone_state(prev, game) == current)
    total = sum(counts.values())
    posterior = {k: (counts[k] + prior * v) / (total + prior)
                 for k, v in base.items()}
    return posterior, base


def random_ticket(game, seed):
    fm, fp, bm, bp = SPECS[game]
    r = random.Random(seed)
    return {"front": sorted(r.sample(range(1, fm + 1), fp)),
            "back": sorted(r.sample(range(1, bm + 1), bp))}


def candidates(rows, game, model, opts=None, limit=3, seed=2026):
    if not rows or model not in MODELS or not 1 <= limit <= 100:
        raise ValueError("invalid candidate request")
    p = parameters(opts)
    fm, fp, bm, bp = SPECS[game]
    front = inclusion_probabilities(rows, game, "front", model, p)
    back = inclusion_probabilities(rows, game, "back", model, p)
    front_pool = sorted(range(1, fm + 1), key=lambda x: (-front[x], x))[:max(11, fp + 3)]
    back_pool = sorted(range(1, bm + 1), key=lambda x: (-back[x], x))[:max(6, bp + 3)]
    pair = (pair_residuals(rows, game) if model in ("Pairwise-D2", "Challenger") else {})
    transition, fair = geometry_transition(rows, game)
    span = geometry_state(rows, game)["mean_span"]
    def logit(prob):
        x = max(1e-9, min(1 - 1e-9, prob))
        return math.log(x / (1 - x))
    ranked_front = []
    for combination in itertools.combinations(sorted(front_pool), fp):
        score = sum(logit(front[x]) for x in combination)
        if pair:
            score += p["pair_weight"] * sum(pair[ab] for ab in itertools.combinations(combination, 2))
        if p["geo_weight"]:
            state = zone_state({"front": combination}, game)
            score += p["geo_weight"] * (math.log(transition[state] / fair[state])
                                       - abs(combination[-1] - combination[0] - span) / fm)
        ranked_front.append((score, combination))
    ranked_back = [(sum(logit(back[x]) for x in combo), combo)
                   for combo in itertools.combinations(sorted(back_pool), bp)]
    ranked_front.sort(key=lambda v: (-v[0], v[1]))
    ranked_back.sort(key=lambda v: (-v[0], v[1]))
    joined = sorted(((fs + bs, f, b) for fs, f in ranked_front[:limit]
                     for bs, b in ranked_back[:limit]),
                    key=lambda v: (-v[0], v[1], v[2]))[:limit]
    result = []
    for score, f, b in joined:
        dan2 = sorted(sorted(f, key=lambda x: (-front[x], x))[:2])
        ticket = {"front": list(f), "back": list(b), "dan2": dan2,
                  "score": round(score, 8), "after_issue": str(rows[-1]["issue"]),
                  "formal_prediction": False}
        validate_ticket(ticket, game)
        result.append(ticket)
    return result


def physics_toy(game, seed=2026, steps=100, airflow=(.08, .18), damping=.995,
                *, mass=1., radius=.025, dt=.05, restitution=.85, friction=.04):
    """Assumed-parameter numerical mechanics, never measured draw equipment."""
    from research.supercompute.v47_physics import simulate_area
    if game not in SPECS or not 0 < damping <= 1:
        raise ValueError("invalid physics parameters")
    areas = {}
    fm, fp, bm, bp = SPECS[game]
    for area, maximum, picked in (("front",fm,fp),("back",bm,bp)):
        areas[area] = simulate_area(maximum,picked,seed_from(seed,game,"physics",area),
            steps, airflow=airflow, mass=mass,radius=radius,dt=dt,
            restitution=restitution,friction=friction,drag=-math.log(damping)/dt)
    return {"status":"UNCALIBRATED_PHYSICS_SIMULATION",
            "toy_ticket":{area:value["ticket"] for area,value in areas.items()},
            "steps":steps, "airflow":list(airflow), "areas":areas,
            "wall_collisions":True, "pair_collisions":True,
            "machine_calibrated":False, "predictive_claim":False,
            "parameter_source":"ASSUMED_ARBITRARY_SIMULATION_UNITS",
            "limitations":["2D", "no spin", "finite time-step contact approximation"]}


def monte_carlo(game, trials=10000, seed=2026):
    if game not in SPECS or not 1 <= trials <= 2_000_000:
        raise ValueError("invalid simulations")
    maximum, picked, _, _ = SPECS[game]
    r = random.Random(seed_from(seed, game, "mc"))
    hits = sum({1, 2}.issubset(random_ticket(game, r.getrandbits(64))["front"])
               for _ in range(trials))
    return {"trials": trials, "d2_hits": hits, "observed": hits / trials,
            "fair_d2": picked * (picked - 1) / (maximum * (maximum - 1)),
            "seed": seed, "assumption": "independent_uniform_draws"}


def m1_math(rows, game, prediction):
    validate_history(rows, game)
    validate_ticket(prediction, game)
    if (len(prediction["dan2"]) != 2 or len(set(prediction["dan2"])) != 2
            or not set(prediction["dan2"]).issubset(prediction["front"])):
        raise ValueError("invalid D2")
    fm, fp, bm, bp = SPECS[game]
    for area, picked in (("front", fp), ("back", bp)):
        for model in MODELS:
            marginals = inclusion_probabilities(rows, game, area, model)
            if not math.isclose(sum(marginals), picked, abs_tol=1e-8):
                raise ValueError("bad probability mass")
    return {"status": "PASS", "ticket_space": math.comb(fm, fp) * math.comb(bm, bp),
            "fair_d2": math.comb(fm - 2, fp - 2) / math.comb(fm, fp)}


def m2_refutation(model_events, fair_d2_probability):
    """Independent exact binomial D2 test against combinatorial fair chance.

    The theoretical reference is a mathematical hypothesis, not an additional
    prediction model. Retrospective exploratory p-values are not adjusted for
    multiple comparisons and must not be interpreted as prospective evidence.
    """
    if (not model_events or any(type(e) is not int or e not in (0, 1)
                                for e in model_events)
            or not isinstance(fair_d2_probability, (int, float))
            or not math.isfinite(fair_d2_probability)
            or not 0 < fair_d2_probability < 1):
        raise ValueError("binary model outcomes and valid fair probability required")
    n = len(model_events)
    hits = sum(model_events)
    p0 = fair_d2_probability
    tail = sum(math.comb(n, k) * p0 ** k * (1 - p0) ** (n - k)
               for k in range(hits, n + 1))
    return {"status": "PASS", "test": "exact_binomial_fair_d2",
            "hits": hits, "trials": n, "fair_probability": p0,
            "hit_rate": hits / n,
            "expected_hits": n * p0,
            "standardized_statistic": (hits-n*p0)/math.sqrt(n*p0*(1-p0)),
            "hit_rate_wilson95": _wilson(hits, n),
            "exploratory_one_sided_p": min(1.0, tail),
            "multiple_tests_adjusted": False}


def _wilson(hits, trials):
    z = 1.959963984540054
    rate = hits/trials
    denominator = 1+z*z/trials
    centre = (rate+z*z/(2*trials))/denominator
    half = z*math.sqrt(rate*(1-rate)/trials+z*z/(4*trials*trials))/denominator
    return [max(0.,centre-half),min(1.,centre+half)]


def m3_calibration(records, bins=10):
    if not records or not 2 <= bins <= 20:
        raise ValueError("calibration requires records")
    grouped = [[] for _ in range(bins)]
    for p, y in records:
        if not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1 or y not in (0, 1):
            raise ValueError("invalid prediction or observation")
        grouped[min(bins - 1, int(p * bins))].append((p, y))
    n = len(records)
    return {"status": "PASS", "samples": n,
            "brier": sum((p - y) ** 2 for p, y in records) / n,
            "ece": sum(len(g) / n * abs(statistics.mean(p for p, _ in g)
                       - statistics.mean(y for _, y in g)) for g in grouped if g),
            "bins": [{"count": len(g),
                      "predicted": statistics.mean(p for p, _ in g),
                      "observed": statistics.mean(y for _, y in g)}
                     for g in grouped if g]}


def evolve(rows, game, seed=2026, generations=2, validation=24):
    """Parent -> mutated children -> competition, all on a PAST validation tail."""
    validate_history(rows, game)
    if len(rows) < 80 + validation or not 1 <= generations <= 8 or validation < 2:
        raise ValueError("history/validation/generations invalid")
    rng = random.Random(seed_from(seed, game, "evolve", rows[-1]["issue"]))
    population = [parameters({"mix": mix, "half_life": life, "prior": prior})
                  for mix, life, prior in ((.5, 30, 60), (.2, 15, 30), (.8, 60, 120))]
    start = len(rows) - validation
    def objective(p):
        values = []
        for i in range(start, len(rows)):
            actual, history = rows[i], rows[:i]
            errors = []
            for area, (maximum, _) in (("front", SPECS[game][:2]),
                                        ("back", SPECS[game][2:])):
                probabilities = inclusion_probabilities(history, game, area, "Challenger", p)
                observed = set(actual[area])
                errors.extend((probabilities[x] - (x in observed)) ** 2
                              for x in range(1, maximum + 1))
            prediction = candidates(history, game, "Challenger", p, 1)[0]
            missed_d2 = not set(prediction["dan2"]).issubset(actual["front"])
            values.append(statistics.mean(errors) + 0.005 * missed_d2)
        return statistics.mean(values)
    genealogy = []
    for generation in range(generations):
        ranked = sorted(((objective(p), p) for p in population),
                        key=lambda item: (item[0], canonical(item[1])))
        parents = [item[1] for item in ranked[:2]]
        genealogy.append({"generation": generation, "tested": len(population),
                          "best_validation_objective": ranked[0][0]})
        population = parents[:]
        for parent in parents:
            for _ in range(2):
                child = parent.copy()
                key = rng.choice(("mix", "half_life", "prior", "pair_weight", "geo_weight"))
                step, lo, hi = {"mix": (.1, 0, 1), "half_life": (10, 1, 1000),
                                "prior": (15, 0, 10000), "pair_weight": (.04, 0, 2),
                                "geo_weight": (.1, 0, 2)}[key]
                child[key] = max(lo, min(hi, child[key] + rng.choice((-1, 1)) * step))
                population.append(child)
    best = min(((objective(p), p) for p in population),
               key=lambda item: (item[0], canonical(item[1])))
    return {"parameters": best[1], "validation_objective": best[0],
            "genealogy": genealogy, "trained_through": str(rows[-1]["issue"]),
            "future_holdout_used": False}


def backtest(rows, game, periods=30, seed=2026):
    """Choose Challenger before the test tail; never tune it on test outcomes."""
    validate_history(rows, game)
    if not 1 <= periods <= 500 or len(rows) < 120 + periods:
        raise ValueError("requires 120 training rows plus test tail")
    start = len(rows) - periods
    champion = evolve(rows[:start], game, seed)
    data = {name: {"d2": [], "full_hits": 0, "records": []} for name in MODELS}
    for i in range(start, len(rows)):
        history, actual = rows[:i], rows[i]
        for name in MODELS:
            opts = champion["parameters"] if name == "Challenger" else None
            prediction = candidates(history, game, name, opts, 1, seed)[0]
            item = data[name]
            item["d2"].append(int(set(prediction["dan2"]).issubset(actual["front"])))
            item["full_hits"] += int(prediction["front"] == actual["front"]
                                     and prediction["back"] == actual["back"])
            for area, (maximum, _) in (("front", SPECS[game][:2]),
                                        ("back", SPECS[game][2:])):
                probabilities = inclusion_probabilities(history, game, area, name, opts)
                observed = set(actual[area])
                item["records"].extend((probabilities[x], int(x in observed))
                                       for x in range(1, maximum + 1))
    fm, fp, _, _ = SPECS[game]
    fair_d2 = fp * (fp - 1) / (fm * (fm - 1))
    result = {}
    for name, item in data.items():
        result[name] = {"n": periods, "d2_hits": sum(item["d2"]),
                        "d2_rate": sum(item["d2"]) / periods,
                        "full_hits": item["full_hits"],
                        "m2": m2_refutation(item["d2"], fair_d2),
                        "m3": m3_calibration(item["records"])}
    return {"game": game, "first_issue": str(rows[start]["issue"]),
            "last_issue": str(rows[-1]["issue"]),
            "strictly_past_only": True, "independent_test_tail": True,
            "challenger_selected_before_test": champion,
            "models": result, "edge": "NO_EDGE", "formal_prediction": False,
            "warning": "retrospective and multiple comparisons; NO PROVEN EDGE"}


def freeze(path, rows, game, model, target_issue, opts=None, seed=2026):
    """Research-only create-once SHA receipt; not independently time sealed."""
    validate_history(rows, game)
    if not rows or model not in MODELS or not str(target_issue):
        raise ValueError("invalid freeze input")
    output = Path(path)
    pred = candidates(rows, game, model, opts, 1, seed)[0]
    payload = {"schema": "SSQDLT_V47_LAB_RESEARCH_1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "game": game, "model": model, "parameters": parameters(opts),
               "target_issue": str(target_issue),
               "history_last_issue": str(rows[-1]["issue"]),
               "history_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
               "ticket": pred, "formal_prediction": False,
               "source_status": "NOT_LIVE_OFFICIAL", "edge": "NO_EDGE"}
    raw = canonical(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as f:
        f.write(raw)
    return {"path": str(output), "sha256": hashlib.sha256(raw).hexdigest()}


def score_frozen(path, actual, expected_sha256):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("receipt tampered")
    receipt = json.loads(raw)
    if str(actual["issue"]) != receipt["target_issue"]:
        raise ValueError("issue mismatch")
    validate_ticket(actual, receipt["game"])
    ticket = receipt["ticket"]
    return {"status": "UNVERIFIED_RESULT",
            "d2_hit": set(ticket["dan2"]).issubset(actual["front"]),
            "full_hit": ticket["front"] == actual["front"]
                        and ticket["back"] == actual["back"],
            "edge": "NO_EDGE"}
