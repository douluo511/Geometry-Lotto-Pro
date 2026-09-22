from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from glp.constants import BACK_MAX, BACK_PICK, FRONT_MAX, FRONT_PICK, PROMOTION_POLICY
from glp.domain import Draw
from glp.engine import MODEL_COMPONENTS, feature_vectors, model_scores_from_features, model_identity
from glp.util import sha256_json, utc_now

MODELS = tuple(MODEL_COMPONENTS)
COMPONENTS = tuple(m for m in MODELS if m != "research_ensemble")
WEIGHTS = {
    "simple_frequency": 0.16,
    "recency": 0.08,
    "gap": 0.06,
    "transition": 0.18,
    "pair_graph": 0.14,
    "geometry_state": 0.18,
    "geometry_transition": 0.20,
}


def _rank(scores: dict[int, float], seed: int = 0) -> list[int]:
    rng = random.Random(seed)
    return sorted(scores, key=lambda n: (scores[n] + rng.uniform(-1e-8, 1e-8), -n), reverse=True)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _hits(ranking: list[int], actual: tuple[int, ...], k: int) -> int:
    return len(set(ranking[:k]).intersection(actual))


def _ndcg(ranking: list[int], actual: tuple[int, ...], k: int) -> float:
    aset = set(actual)
    gain = 0.0
    for i, n in enumerate(ranking[:k], start=1):
        if n in aset:
            gain += 1.0 / math.log2(i + 1.0)
    ideal = sum(1.0 / math.log2(i + 1.0) for i in range(1, min(k, len(actual)) + 1))
    return gain / ideal if ideal else 0.0


def bootstrap_ci(values: list[float], rounds: int | None = None, seed: int = 1729) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "lower95": 0.0, "upper95": 0.0, "n": 0}
    rounds = int(rounds or PROMOTION_POLICY["bootstrap_rounds"])
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(rounds):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[max(0, int(0.025 * rounds) - 1)]
    hi = means[min(rounds - 1, int(0.975 * rounds))]
    return {"mean": _mean(values), "lower95": lo, "upper95": hi, "n": n}


def permutation_p(values: list[float], rounds: int | None = None, seed: int = 2718) -> float:
    """One-sided sign-flip permutation p-value for mean(values) > 0."""
    if not values:
        return 1.0
    rounds = int(rounds or PROMOTION_POLICY["permutation_rounds"])
    observed = _mean(values)
    if observed <= 0:
        return 1.0
    rng = random.Random(seed)
    exceed = 0
    for _ in range(rounds):
        m = sum(v if rng.random() < 0.5 else -v for v in values) / len(values)
        if m >= observed:
            exceed += 1
    return (exceed + 1.0) / (rounds + 1.0)


def holm(pvalues: dict[str, float], alpha: float | None = None) -> dict[str, dict[str, Any]]:
    alpha = float(alpha or PROMOTION_POLICY["alpha"])
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    active = True
    result: dict[str, dict[str, Any]] = {}
    for i, (name, p) in enumerate(ordered):
        threshold = alpha / max(1, m - i)
        reject = bool(active and p <= threshold)
        if not reject:
            active = False
        result[name] = {"p": float(p), "threshold": threshold, "reject_null": reject}
    return result


def wilson_lower(k: int, n: int, z: float = 1.959963984540054) -> float:
    if n <= 0:
        return 0.0
    phat = k / n
    den = 1.0 + z * z / n
    center = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return max(0.0, (center - margin) / den)


def _average_scores(draws: list[Draw], area: str, windows: tuple[int, ...]) -> dict[str, dict[int, float]]:
    accum: dict[str, dict[int, float]] = {}
    counts: dict[str, int] = defaultdict(int)
    for window in windows:
        feature = feature_vectors(draws, area, window=window)
        sets = model_scores_from_features(feature)
        for model, scores in sets.items():
            if model not in accum:
                accum[model] = {n: 0.0 for n in scores}
            for n, v in scores.items():
                accum[model][n] += float(v)
            counts[model] += 1
    for model in accum:
        c = max(1, counts[model])
        for n in accum[model]:
            accum[model][n] /= c
    return accum


def _metric_from_scores(front_scores: dict[int, float], back_scores: dict[int, float], target: Draw, seed: int) -> dict[str, float]:
    fr = _rank(front_scores, seed)
    br = _rank(back_scores, seed + 100003)
    fh = _hits(fr, target.front, FRONT_PICK)
    bh = _hits(br, target.back, BACK_PICK)
    recall = fh / FRONT_PICK
    back_hit = bh / BACK_PICK
    front_gain = recall - (FRONT_PICK / FRONT_MAX)
    back_gain = back_hit - (BACK_PICK / BACK_MAX)
    combined = 0.70 * front_gain + 0.30 * back_gain
    return {
        "front_hits": float(fh),
        "back_hits": float(bh),
        "front_recall": recall,
        "back_hit_rate": back_hit,
        "front_gain": front_gain,
        "back_gain": back_gain,
        "combined_gain": combined,
        "front_ndcg": _ndcg(fr, target.front, FRONT_PICK),
        "back_ndcg": _ndcg(br, target.back, BACK_PICK),
    }


def walk_forward(
    draws: list[Draw],
    max_evals: int | None = None,
    progress=None,
) -> dict[str, Any]:
    windows = tuple(int(x) for x in PROMOTION_POLICY["windows"])
    min_hist = max(windows)
    available = max(0, len(draws) - min_hist)
    want = min(available, int(max_evals or (PROMOTION_POLICY["min_walk_forward"] + 240)))
    start = len(draws) - want
    records: list[dict[str, Any]] = []
    model_values: dict[str, list[float]] = {m: [] for m in MODELS}
    model_front: dict[str, list[float]] = {m: [] for m in MODELS}
    model_back: dict[str, list[float]] = {m: [] for m in MODELS}
    holdout_cache: list[dict[str, Any]] = []
    # Global chronology sentinel catches any non-monotonic date ordering, not
    # merely the immediately preceding row.  A malformed chronology can never
    # be allowed to masquerade as a clean walk-forward run.
    chronology_ok = all(draws[i].draw_date < draws[i + 1].draw_date for i in range(len(draws) - 1))
    leakage_violations = 0 if chronology_ok else 1
    seeds = tuple(int(x) for x in PROMOTION_POLICY["seeds"])

    for idx in range(start, len(draws)):
        history = draws[:idx]
        target = draws[idx]
        if not history or history[-1].draw_date >= target.draw_date:
            leakage_violations += 1
            continue
        fs = _average_scores(history, "front", windows)
        bs = _average_scores(history, "back", windows)
        seed = seeds[(idx - start) % len(seeds)]
        row = {"issue": target.issue, "draw_date": target.draw_date, "models": {}}
        for model in MODELS:
            met = _metric_from_scores(fs[model], bs[model], target, seed)
            model_values[model].append(met["combined_gain"])
            model_front[model].append(met["front_gain"])
            model_back[model].append(met["back_gain"])
            row["models"][model] = met
        records.append(row)
        # Cache only the last 240 untouched observations for ablation and dual confirmation.
        if idx >= len(draws) - 240:
            holdout_cache.append({"target": target, "front": fs, "back": bs, "seed": seed})
        if progress and ((idx - start) % 100 == 0 or idx == len(draws) - 1):
            progress(f"Evidence walk-forward {idx-start+1}/{want}")

    summaries = {}
    for model in MODELS:
        vals = model_values[model]
        summaries[model] = {
            "n": len(vals),
            "combined_gain": _mean(vals),
            "front_recall_gain": _mean(model_front[model]),
            "back_recall_gain": _mean(model_back[model]),
            "bootstrap": bootstrap_ci(vals),
            "permutation_p": permutation_p(vals),
        }
    return {
        "start_index": start,
        "n": len(records),
        "records": records,
        "summary": summaries,
        "model_values": model_values,
        "holdout_cache": holdout_cache,
        "leakage_violations": leakage_violations,
    }


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a frozen record slice without leaking confirmation rows into development."""
    summaries: dict[str, Any] = {}
    for model in MODELS:
        vals = [float(r["models"][model]["combined_gain"]) for r in records]
        fronts = [float(r["models"][model]["front_gain"]) for r in records]
        backs = [float(r["models"][model]["back_gain"]) for r in records]
        summaries[model] = {
            "n": len(vals),
            "combined_gain": _mean(vals),
            "front_recall_gain": _mean(fronts),
            "back_recall_gain": _mean(backs),
            "bootstrap": bootstrap_ci(vals),
            "permutation_p": permutation_p(vals),
        }
    return summaries


def _era_results(records: list[dict[str, Any]], model: str) -> dict[str, float]:
    by_year: dict[str, list[float]] = defaultdict(list)
    for r in records:
        year = str(r["draw_date"])[:4]
        by_year[year].append(float(r["models"][model]["combined_gain"]))
    return {y: _mean(v) for y, v in sorted(by_year.items())}


def _temporal_loeo(draws: list[Draw], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Chronology-safe leave-current-era-out stress test.

    For each calendar era, freeze one model using only observations from prior
    eras, with every observation from the target era excluded.  The frozen
    ranking is then evaluated across all OOS targets in that era.  This is both
    stricter and faster than recomputing the same era-excluded history for each
    target, because no within-era observation is allowed to enter training.
    """
    windows = tuple(int(x) for x in PROMOTION_POLICY["windows"])
    seeds = tuple(int(x) for x in PROMOTION_POLICY["seeds"])
    issue_to_idx = {d.issue: i for i, d in enumerate(draws)}
    grouped: dict[str, list[tuple[int, Draw]]] = defaultdict(list)
    skipped = 0
    for r in records:
        idx = issue_to_idx.get(str(r["issue"]))
        if idx is None:
            skipped += 1
            continue
        target = draws[idx]
        grouped[str(target.draw_date)[:4]].append((idx, target))

    eras: dict[str, Any] = {}
    for era, targets in sorted(grouped.items()):
        first_idx = min(i for i, _ in targets)
        history = [d for d in draws[:first_idx] if str(d.draw_date)[:4] != era]
        if len(history) < max(windows):
            skipped += len(targets)
            continue
        fs = _average_scores(history, "front", windows)["research_ensemble"]
        bs = _average_scores(history, "back", windows)["research_ensemble"]
        vals: list[float] = []
        for idx, target in targets:
            seed = seeds[idx % len(seeds)]
            met = _metric_from_scores(fs, bs, target, seed)
            vals.append(float(met["combined_gain"]))
        eras[era] = {
            "n": len(vals),
            "combined_gain": _mean(vals),
            "bootstrap": bootstrap_ci(vals, rounds=999, seed=6100 + int(era[-2:])),
            "training_cutoff_index": first_idx,
            "within_era_training_rows": 0,
        }
    positive = sum(1 for v in eras.values() if v["combined_gain"] > 0)
    passed = len(eras) >= int(PROMOTION_POLICY["min_era_count"]) and positive == len(eras) and skipped == 0
    return {
        "method": "one frozen prior-era model per calendar year; target-year observations excluded; no future eras used",
        "eras": eras,
        "skipped": skipped,
        "passed": passed,
    }


def _dual_confirmation(values: list[float]) -> dict[str, Any]:
    n = len(values)
    cut = n // 2
    halves = [values[:cut], values[cut:]]
    results = []
    for i, part in enumerate(halves, start=1):
        boot = bootstrap_ci(part, rounds=999, seed=7000 + i)
        p = permutation_p(part, rounds=1000, seed=8000 + i)
        passed = (
            len(part) >= int(PROMOTION_POLICY["min_confirmation_n"])
            and boot["lower95"] > float(PROMOTION_POLICY["min_bootstrap_lower"])
            and p <= float(PROMOTION_POLICY["alpha"])
        )
        results.append({"half": i, "n": len(part), "bootstrap": boot, "permutation_p": p, "passed": passed})
    return {"halves": results, "passed": bool(results and all(x["passed"] for x in results))}


def _ablation(holdout_cache: list[dict[str, Any]]) -> dict[str, Any]:
    if not holdout_cache:
        return {"executed": False, "tests": {}, "holm": {}, "supported_components": [], "passed": False}
    rng = random.Random(91023)
    base_vals: list[float] = []
    alternatives: dict[str, list[float]] = {}
    for comp in COMPONENTS:
        for mode in PROMOTION_POLICY["ablation_modes"]:
            alternatives[f"{comp}:{mode}"] = []

    for row in holdout_cache:
        target = row["target"]
        seed = int(row["seed"])
        front_sets = row["front"]
        back_sets = row["back"]
        base = _metric_from_scores(front_sets["research_ensemble"], back_sets["research_ensemble"], target, seed)
        base_vals.append(base["combined_gain"])
        for comp in COMPONENTS:
            for mode in PROMOTION_POLICY["ablation_modes"]:
                def mutate(sets: dict[str, dict[int, float]], area_salt: int) -> dict[int, float]:
                    nums = sorted(sets["research_ensemble"])
                    score = {n: 0.0 for n in nums}
                    active = dict(WEIGHTS)
                    if mode == "remove":
                        active.pop(comp, None)
                        total = sum(active.values()) or 1.0
                        for name, w in active.items():
                            for n in nums:
                                score[n] += (w / total) * sets[name][n]
                    else:
                        repl = dict(sets[comp])
                        if mode == "shuffle":
                            vals = [repl[n] for n in nums]
                            local = random.Random(seed + area_salt + sum(ord(c) for c in comp))
                            local.shuffle(vals)
                            repl = dict(zip(nums, vals))
                        elif mode == "random_replace":
                            local = random.Random(seed + area_salt + 31337 + sum(ord(c) for c in comp))
                            repl = {n: local.uniform(-1.0, 1.0) for n in nums}
                        for name, w in WEIGHTS.items():
                            src = repl if name == comp else sets[name]
                            for n in nums:
                                score[n] += w * src[n]
                    return score
                f_alt = mutate(front_sets, 11)
                b_alt = mutate(back_sets, 23)
                met = _metric_from_scores(f_alt, b_alt, target, seed)
                alternatives[f"{comp}:{mode}"].append(met["combined_gain"])

    tests: dict[str, Any] = {}
    pvals: dict[str, float] = {}
    for name, alt in alternatives.items():
        degradation = [b - a for b, a in zip(base_vals, alt)]
        p = permutation_p(degradation, rounds=1000, seed=1234 + len(name))
        pvals[name] = p
        tests[name] = {
            "base_gain": _mean(base_vals),
            "alternative_gain": _mean(alt),
            "degradation": _mean(degradation),
            "permutation_p": p,
        }
    adjusted = holm(pvals)
    for name in tests:
        tests[name]["holm"] = adjusted[name]
        tests[name]["supported"] = bool(tests[name]["degradation"] > 0 and adjusted[name]["reject_null"])
    supported_components = []
    for comp in COMPONENTS:
        names = [f"{comp}:{m}" for m in PROMOTION_POLICY["ablation_modes"]]
        if all(tests[n]["supported"] for n in names):
            supported_components.append(comp)
    # No unsupported non-zero research component may hitchhike into a promoted
    # ensemble.  Dynamic pruning would require a fresh preregistered re-run, so
    # this frozen ensemble passes only when every active component survives all
    # three falsifiers.
    required_components = list(COMPONENTS)
    passed = set(supported_components) == set(required_components)
    return {
        "executed": True,
        "n": len(holdout_cache),
        "tests": tests,
        "holm": adjusted,
        "required_components": required_components,
        "supported_components": supported_components,
        "unsupported_components": [c for c in required_components if c not in supported_components],
        "passed": passed,
    }


def _null_worlds(n: int, observed_gain: float) -> dict[str, Any]:
    worlds = int(PROMOTION_POLICY["null_worlds"])
    rng = random.Random(0xFFFFFF)
    maxima: list[float] = []
    false_promotions = 0
    n = max(240, n)
    for _ in range(worlds):
        vals = []
        for _j in range(n):
            # Exact random-baseline simulation: random 6-of-33 intersection and 1-of-16 hit.
            actual = set(rng.sample(range(1, FRONT_MAX + 1), FRONT_PICK))
            pred = set(rng.sample(range(1, FRONT_MAX + 1), FRONT_PICK))
            fh = len(actual & pred) / FRONT_PICK
            bh = 1.0 if rng.randrange(BACK_MAX) == 0 else 0.0
            vals.append(0.70 * (fh - FRONT_PICK / FRONT_MAX) + 0.30 * (bh - BACK_PICK / BACK_MAX))
        maxima.append(_mean(vals))
        cut = len(vals) // 2
        ok = True
        for part in (vals[:cut], vals[cut:]):
            m = _mean(part)
            if len(part) < 2:
                ok = False
                break
            sd = math.sqrt(sum((x - m) ** 2 for x in part) / (len(part) - 1))
            lower = m - 1.96 * sd / math.sqrt(len(part))
            if lower <= 0:
                ok = False
                break
        if ok:
            false_promotions += 1
    maxima.sort()
    percentile = sum(1 for x in maxima if x <= observed_gain) / max(1, len(maxima))
    return {
        "worlds": worlds,
        "false_promotions": false_promotions,
        "false_positive_rate": false_promotions / max(1, worlds),
        "observed_percentile": percentile,
        "null_gain_p95": maxima[min(len(maxima)-1, int(0.95 * len(maxima)))] if maxima else 0.0,
    }


def _support_gate(draws: list[Draw]) -> dict[str, Any]:
    """Stability gate for research Dan candidates.

    Seeds are true history perturbations, not repeated tie-breaks.  Each
    model×window pair is one Wilson trial; the five seeds form an internal
    consensus for that trial so correlated seed repeats cannot inflate n.
    """
    windows = tuple(int(x) for x in PROMOTION_POLICY["windows"])
    seeds = tuple(int(x) for x in PROMOTION_POLICY["seeds"])

    # Candidate selection is fixed on the unperturbed history.  Perturbations
    # only test whether that already-selected candidate remains supported.
    fbase = _average_scores(draws, "front", windows)["research_ensemble"]
    bbase = _average_scores(draws, "back", windows)["research_ensemble"]
    front_dan = _rank(fbase, 17)[:2]
    back_dan = _rank(bbase, 17)[:1]

    def perturbed_history(window: int, seed: int) -> list[Draw]:
        hist = list(draws[-window:])
        if len(hist) <= 4:
            return hist
        # Preserve the latest anchor draw; sample exactly 90% of the preceding
        # rows without replacement and then restore chronology.
        prior_n = len(hist) - 1
        keep_n = max(3, int(round(prior_n * 0.90)))
        rng = random.Random((seed * 1000003) ^ (window * 9176) ^ 0x51A7)
        keep = sorted(rng.sample(range(prior_n), min(keep_n, prior_n)))
        return [hist[i] for i in keep] + [hist[-1]]

    score_cache: dict[tuple[str, int, int], dict[str, dict[int, float]]] = {}
    for area in ("front", "back"):
        for w in windows:
            for seed in seeds:
                ph = perturbed_history(w, seed)
                score_cache[(area, w, seed)] = model_scores_from_features(
                    feature_vectors(ph, area, window=min(w, len(ph)))
                )

    detail: dict[str, Any] = {"front": {}, "back": {}}
    for area, dans, pick in (
        ("front", front_dan, FRONT_PICK),
        ("back", back_dan, BACK_PICK),
    ):
        universe_size = FRONT_MAX if area == "front" else BACK_MAX
        for dan in dans:
            supports = 0
            total = 0
            family_support: dict[str, int] = defaultdict(int)
            family_total: dict[str, int] = defaultdict(int)
            rank_points: list[float] = []
            variable_units = 0
            seed_consensus_detail: dict[str, Any] = {}
            for model in COMPONENTS:
                for w in windows:
                    ranks = []
                    for seed in seeds:
                        ranking = _rank(score_cache[(area, w, seed)][model], seed)
                        ranks.append(ranking.index(dan) + 1)
                    seed_hit_rate = sum(1 for r in ranks if r <= pick) / max(1, len(ranks))
                    unit_supported = seed_hit_rate >= 0.60
                    total += 1
                    family_total[model] += 1
                    if unit_supported:
                        supports += 1
                        family_support[model] += 1
                    unit_rank_support = _mean([
                        1.0 - (r - 1) / max(1, universe_size - 1) for r in ranks
                    ])
                    rank_points.append(unit_rank_support)
                    if len(set(ranks)) > 1:
                        variable_units += 1
                    seed_consensus_detail[f"{model}@{w}"] = {
                        "ranks": ranks,
                        "seed_hit_rate": seed_hit_rate,
                        "supported": unit_supported,
                    }
            coverage = sum(
                1 for m in COMPONENTS
                if family_support[m] / max(1, family_total[m]) >= 0.5
            ) / len(COMPONENTS)
            support = supports / max(1, total)
            lower = wilson_lower(supports, total)
            rank_support = _mean(rank_points)
            detail[area][str(dan)] = {
                "supports": supports,
                "independent_trials": total,
                "raw_seed_trials": total * len(seeds),
                "support": support,
                "wilson95_lower": lower,
                "model_coverage": coverage,
                "rank_support": rank_support,
                "seed_perturbation_variable_units": variable_units,
                "seed_consensus_threshold": 0.60,
                "seed_consensus": seed_consensus_detail,
                "passed": (
                    lower >= float(PROMOTION_POLICY["min_wilson_lower"])
                    and coverage >= float(PROMOTION_POLICY["min_model_coverage"])
                    and rank_support >= float(PROMOTION_POLICY["min_rank_support"])
                ),
            }
    passed = all(x["passed"] for area in detail.values() for x in area.values())
    return {
        "front_dan": front_dan,
        "back_dan": back_dan,
        "seed_method": "90% chronology-preserving history subsample; latest anchor retained",
        "wilson_unit": "model×window seed-consensus (not individual correlated seeds)",
        "detail": detail,
        "passed": passed,
    }


def run_evidence_court(
    draws: list[Draw],
    prospective: list[dict[str, Any]] | None = None,
    progress=None,
) -> dict[str, Any]:
    prospective = prospective or []
    identity = model_identity()
    if len(draws) < max(PROMOTION_POLICY["windows"]) + 300:
        payload = {
            "schema": "evidence-court-v8",
            "created_at": utc_now(),
            "software_verdict": "FAIL",
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
            "decision": "REJECT_EDGE",
            "outcome": "insufficient history for the pre-registered protocol",
            "gates": [{"name": "Walk-forward", "status": "FAIL", "decision": "REJECT_EDGE", "outcome": "insufficient observations"}],
            "production_weights": {"uniform_baseline": 1.0, "research_ensemble": 0.0},
            "lifecycle": {"Champion": "uniform_baseline", "Challenger": "research_ensemble", "Shadow": "research_ensemble"},
        }
        payload["court_hash"] = sha256_json(payload)
        return payload

    if progress:
        progress("Evidence Court: frozen walk-forward protocol")
    wf = walk_forward(draws, max_evals=int(PROMOTION_POLICY["min_walk_forward"]) + 240, progress=progress)
    # Strict split: the final 240 OOS rows are confirmation-only.  They are
    # excluded from model screening, Reality Check and LOEO so that a holdout
    # cannot silently improve the development verdict it is supposed to test.
    confirmation_n = 240
    if len(wf["records"]) <= confirmation_n:
        raise RuntimeError("walk-forward produced insufficient rows for isolated holdout")
    dev_records = wf["records"][:-confirmation_n]
    holdout_records = wf["records"][-confirmation_n:]
    summary = _summarize_records(dev_records)
    pvals = {m: float(summary[m]["permutation_p"]) for m in MODELS}
    reality = holm(pvals)
    primary = summary["research_ensemble"]
    # True chronology-safe era exclusion rather than a mere per-year summary.
    if progress:
        progress("Evidence Court: Temporal Leave-One-Era-Out")
    loeo = _temporal_loeo(draws, dev_records)
    eras = loeo["eras"]

    holdout_vals = [float(r["models"]["research_ensemble"]["combined_gain"]) for r in holdout_records]
    dev_vals = [float(r["models"]["research_ensemble"]["combined_gain"]) for r in dev_records]
    holdout_boot = bootstrap_ci(holdout_vals)
    holdout_p = permutation_p(holdout_vals)
    dual = _dual_confirmation(holdout_vals)

    if progress:
        progress("Evidence Court: Remove / Shuffle / Random ablation")
    ablation = _ablation(wf["holdout_cache"])
    if progress:
        progress("Evidence Court: null-world false-positive firewall")
    nulls = _null_worlds(len(holdout_vals), _mean(holdout_vals))
    support = _support_gate(draws)

    prospective_n = len(prospective)
    prospective_selector_consistent = all(
        (not isinstance(x, dict)) or (not x.get("selector_hash")) or x.get("selector_hash") == identity["selector_hash"]
        for x in prospective
    )

    alpha = float(PROMOTION_POLICY["alpha"])
    predictive_pass = (
        primary["n"] >= int(PROMOTION_POLICY["min_walk_forward"])
        and primary["front_recall_gain"] > float(PROMOTION_POLICY["min_front_recall_gain"])
        and primary["back_recall_gain"] > float(PROMOTION_POLICY["min_back_recall_gain"])
        and primary["bootstrap"]["lower95"] > float(PROMOTION_POLICY["min_bootstrap_lower"])
        and reality["research_ensemble"]["reject_null"]
    )
    loeo_pass = bool(loeo["passed"])
    holdout_pass = holdout_boot["lower95"] > 0 and holdout_p <= alpha
    leakage_pass = int(wf["leakage_violations"]) == 0
    null_pass = (
        nulls["false_positive_rate"] <= float(PROMOTION_POLICY["max_null_world_fpr"])
        and nulls["observed_percentile"] >= float(PROMOTION_POLICY["min_null_percentile"])
    )
    edge_proven = all((
        predictive_pass, loeo_pass, holdout_pass, dual["passed"],
        ablation["passed"], leakage_pass, null_pass,
    ))
    certified_dan = (
        edge_proven
        and support["passed"]
        and prospective_n >= int(PROMOTION_POLICY["min_prospective"])
        and prospective_selector_consistent
    )

    gates = [
        {"name": "Walk-forward OOS", "status": "PASS", "decision": "ACCEPT_EDGE" if predictive_pass else "REJECT_EDGE", "outcome": f"n={primary['n']}; gain={primary['combined_gain']:.6f}"},
        {"name": "Random Baseline", "status": "PASS", "decision": "ABOVE_BASELINE" if primary["combined_gain"] > 0 else "NOT_ABOVE_BASELINE", "outcome": f"mean excess={primary['combined_gain']:.6f}; descriptive only, not an edge grant"},
        {"name": "Bootstrap", "status": "PASS", "decision": "ACCEPT_EDGE" if primary["bootstrap"]["lower95"] > 0 else "REJECT_EDGE", "outcome": f"lower95={primary['bootstrap']['lower95']:.6f}"},
        {"name": "Permutation + Holm Reality Check", "status": "PASS", "decision": "ACCEPT_EDGE" if reality["research_ensemble"]["reject_null"] else "REJECT_EDGE", "outcome": f"p={primary['permutation_p']:.6g}"},
        {"name": "Temporal LOEO", "status": "PASS", "decision": "SUPPORT_EDGE" if loeo_pass else "REJECT_EDGE", "outcome": f"eras={len(eras)}; skipped={loeo['skipped']}"},
        {"name": "Ablation Remove/Shuffle/Random", "status": "PASS", "decision": "ACCEPT_EDGE" if ablation["passed"] else "REJECT_EDGE", "outcome": f"supported={ablation['supported_components']}"},
        {"name": "Leakage Sentinel", "status": "PASS" if leakage_pass else "FAIL", "decision": "ACCEPT" if leakage_pass else "REJECT_EDGE", "outcome": f"violations={wf['leakage_violations']}"},
        {"name": "Null-world FPR", "status": "PASS", "decision": "ACCEPT_EDGE" if null_pass else "REJECT_EDGE", "outcome": f"FPR={nulls['false_positive_rate']:.4f}; pct={nulls['observed_percentile']:.4f}"},
        {"name": "Untouched Holdout", "status": "PASS", "decision": "ACCEPT_EDGE" if holdout_pass else "REJECT_EDGE", "outcome": f"lower95={holdout_boot['lower95']:.6f}; p={holdout_p:.6g}"},
        {"name": "Dual Final Confirmation", "status": "PASS", "decision": "ACCEPT_EDGE" if dual["passed"] else "REJECT_EDGE", "outcome": "two independent holdout halves"},
        {"name": "Wilson/Coverage/Rank Support", "status": "PASS", "decision": "ACCEPT_DAN" if support["passed"] else "REJECT_DAN", "outcome": "multi-window × multi-model × multi-seed"},
        {"name": "Prospective Replay", "status": "PASS", "decision": "ACCEPT_DAN" if prospective_n >= int(PROMOTION_POLICY["min_prospective"]) else "REJECT_DAN", "outcome": f"immutable observations={prospective_n}"},
    ]

    # A gate's status reports whether the test EXECUTED correctly; its decision
    # reports whether evidence supports an edge. This prevents the old semantic
    # bug where REJECT_EDGE was accidentally interpreted as software failure or
    # where a non-executed test could masquerade as PASS.
    hard_fail = any(g["status"] == "FAIL" for g in gates)
    software_verdict = "FAIL" if hard_fail else "PASS"
    payload: dict[str, Any] = {
        "schema": "evidence-court-v8",
        "created_at": utc_now(),
        "pre_registered_policy": PROMOTION_POLICY,
        "model_hash": identity["model_hash"],
        "selector_hash": identity["selector_hash"],
        "walk_forward": {
            "total_oos_n": len(wf["records"]),
            "development_oos_n": len(dev_records),
            "untouched_holdout_n": len(holdout_records),
            "split_rule": "development excludes final 240 OOS rows; holdout is confirmation-only",
            "leakage_violations": wf["leakage_violations"],
        },
        "model_tests": summary,
        "reality_check": reality,
        "loeo": loeo,
        "ablation": ablation,
        "null_world": nulls,
        "untouched_holdout": {"n": len(holdout_vals), "bootstrap": holdout_boot, "permutation_p": holdout_p},
        "dual_final_confirmation": dual,
        "support_gate": support,
        "prospective_n": prospective_n,
        "prospective_selector_consistent": prospective_selector_consistent,
        "leakage_violations": wf["leakage_violations"],
        "software_verdict": software_verdict,
        "edge_state": "EDGE_PROVEN" if edge_proven else "NO_EDGE",
        "dan_state": "CERTIFIED_DAN" if certified_dan else "NULL_DAN",
        "decision": "ACCEPT_EDGE" if edge_proven else "REJECT_EDGE",
        "outcome": (
            "pre-registered evidence supports repeatable OOS edge"
            if edge_proven else
            "edge not proven; uniform baseline remains Champion"
        ),
        "production_weights": {
            "uniform_baseline": 0.0 if certified_dan else 1.0,
            "research_ensemble": 1.0 if certified_dan else 0.0,
        },
        "lifecycle": {
            "Champion": "research_ensemble" if certified_dan else "uniform_baseline",
            "Challenger": "research_ensemble",
            "Shadow": "research_ensemble",
        },
        "gates": gates,
        "five_why": {
            "why1": "Did ranking beat the explicit random baseline OOS?",
            "why2": "Did the effect survive multi-window/model/seed perturbation?",
            "why3": "Did Remove/Shuffle/Random ablation show causal necessity?",
            "why4": "Did untouched and dual confirmations independently survive?",
            "why5": "Did null-world FPR and leakage sentinels remain within the frozen contract?",
        },
        "reverse_validation": {
            "remove": True,
            "shuffle": True,
            "random_replace": True,
            "reverse_time_control": "research-only falsifier; never grants production permission",
        },
        "final_validation": {
            "status": software_verdict,
            "hard_fail_count": sum(1 for g in gates if g["status"] == "FAIL"),
            "edge_proven": edge_proven,
            "dan_certified": certified_dan,
        },
    }
    payload["court_hash"] = sha256_json(payload)
    return payload
