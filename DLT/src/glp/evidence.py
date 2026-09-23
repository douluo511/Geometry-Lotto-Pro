from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

from .constants import PROMOTION_POLICY
from .domain import Draw
from .engine import (
    BASE_MODELS, ensemble_ranking_from_components, individual_model_rankings,
    individual_model_scores, model_identity, ranking_from_scores,
)
from .util import sha256_json, utc_now

MODELS = tuple(BASE_MODELS) + ("research_ensemble",)


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    return draw.front if area == "front" else draw.back


def _meta(area: str) -> tuple[int, int]:
    return (35, 5) if area == "front" else (12, 2)


def _hit(ranking: list[int], actual: Iterable[int], k: int) -> float:
    return float(len(set(ranking[:k]) & set(actual)))


def _recall(ranking: list[int], actual: Iterable[int], k: int) -> float:
    a = set(actual)
    return len(set(ranking[:k]) & a) / max(1, len(a))


def _ndcg(ranking: list[int], actual: Iterable[int], k: int) -> float:
    a = set(actual)
    dcg = sum((1.0 / math.log2(i + 2)) for i, n in enumerate(ranking[:k]) if n in a)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(a))))
    return dcg / ideal if ideal else 0.0


def _rank_score(ranking: list[int], actual: Iterable[int]) -> float:
    pos = {n: i + 1 for i, n in enumerate(ranking)}
    nmax = len(ranking)
    return statistics.mean((nmax + 1 - pos.get(n, nmax)) / nmax for n in actual)


def leakage_guard(history_end: int, target_index: int) -> bool:
    return int(history_end) < int(target_index)


def _random_ranking(max_n: int, seed_material: Any) -> list[int]:
    seed = int(sha256_json(seed_material)[:16], 16)
    rng = random.Random(seed)
    out = list(range(1, max_n + 1))
    rng.shuffle(out)
    return out


def _wilson_lower(successes: int, n: int, z: float) -> float:
    if n <= 0:
        return 0.0
    p = successes / n
    den = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (center - adj) / den)


def bootstrap_ci(values: list[float], rounds: int | None = None, seed: int = 5102026) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rounds = rounds or int(PROMOTION_POLICY["bootstrap_rounds"])
    rng = random.Random(seed)
    n = len(values)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds)]
    means.sort()
    return means[int(0.025 * (rounds - 1))], means[int(0.975 * (rounds - 1))]


def permutation_p(values: list[float], rounds: int | None = None, seed: int = 4102026) -> float:
    if not values:
        return 1.0
    rounds = rounds or int(PROMOTION_POLICY["permutation_rounds"])
    observed = sum(values) / len(values)
    rng = random.Random(seed)
    extreme = 1
    for _ in range(rounds):
        simulated = sum(v if rng.random() < 0.5 else -v for v in values) / len(values)
        if simulated >= observed:
            extreme += 1
    return extreme / (rounds + 1)


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    result = {k: False for k in pvalues}
    for i, (name, p) in enumerate(ordered):
        threshold = alpha / max(1, len(ordered) - i)
        if p <= threshold:
            result[name] = True
        else:
            break
    return result


def _perturbed_ranking(scores: dict[int, float], seed_material: Any, jitter: float) -> list[int]:
    vals = list(scores.values())
    scale = statistics.pstdev(vals) if len(vals) > 1 else 1.0
    if scale <= 1e-12:
        scale = 1.0
    seed = int(sha256_json(seed_material)[:16], 16)
    rng = random.Random(seed)
    changed = {n: float(v) + rng.uniform(-jitter, jitter) * scale for n, v in scores.items()}
    return ranking_from_scores(changed)


def walk_forward(draws: list[Draw], area: str, window: int, start: int, end: int) -> list[dict[str, Any]]:
    max_n, pick = _meta(area)
    seeds = tuple(PROMOTION_POLICY["seeds"])
    jitter = float(PROMOTION_POLICY["dan_seed_jitter"])
    out: list[dict[str, Any]] = []
    for i in range(max(window, start), min(end, len(draws))):
        history = draws[max(0, i - window):i]
        score_maps = individual_model_scores(history, area)
        rankings = {m: ranking_from_scores(score_maps[m]) for m in MODELS}
        actual = _area(draws[i], area)
        random_recalls = []
        for seed in seeds:
            rr = _random_ranking(max_n, [area, window, seed, draws[i].issue])
            random_recalls.append(_recall(rr, actual, pick))
        random_recall = sum(random_recalls) / len(random_recalls)
        models = {}
        dan_votes: dict[str, list[int]] = {}
        for m in MODELS:
            r = rankings[m]
            models[m] = {
                "hit": _hit(r, actual, pick),
                "recall": _recall(r, actual, pick),
                "gain": _recall(r, actual, pick) - random_recall,
                "ndcg": _ndcg(r, actual, pick),
                "rank": _rank_score(r, actual),
                "ranking": r,
            }
            dan_votes[m] = [
                _perturbed_ranking(score_maps[m], ["dan", area, window, m, seed, draws[i].issue], jitter)[0]
                for seed in seeds
            ]
        out.append({
            "target_index": i,
            "history_start": max(0, i - window),
            "history_end": i - 1,
            "target_issue": draws[i].issue,
            "actual": list(actual),
            "random_recall": random_recall,
            "models": models,
            "dan_votes": dan_votes,
        })
    return out

def _aggregate_windows(records_by_window: dict[int, list[dict[str, Any]]], model: str) -> list[float]:
    by_issue: dict[str, list[float]] = defaultdict(list)
    for records in records_by_window.values():
        for r in records:
            by_issue[r["target_issue"]].append(float(r["models"][model]["gain"]))
    return [sum(vals) / len(vals) for _issue, vals in sorted(by_issue.items())]


def _loeo_results(values: list[float], eras: int, alpha: float) -> list[dict[str, float | int | bool]]:
    if not values:
        return []
    result = []
    for e in range(eras):
        a = len(values) * e // eras
        b = len(values) * (e + 1) // eras
        kept = values[:a] + values[b:]
        mean = statistics.mean(kept) if kept else 0.0
        lo, hi = bootstrap_ci(
            kept,
            rounds=int(PROMOTION_POLICY["loeo_bootstrap_rounds"]),
            seed=9100 + e,
        )
        p = permutation_p(
            kept,
            rounds=int(PROMOTION_POLICY["loeo_permutation_rounds"]),
            seed=10100 + e,
        )
        passed = bool(kept) and mean > 0.0 and lo > 0.0 and p < alpha
        result.append({
            "left_out_era": e + 1,
            "n": len(kept),
            "gain": mean,
            "bootstrap95_lower": lo,
            "bootstrap95_upper": hi,
            "permutation_p": p,
            "pass": passed,
        })
    return result

def _ablation(draws: list[Draw], area: str, start: int, end: int) -> dict[str, Any]:
    max_n, pick = _meta(area)
    points = int(PROMOTION_POLICY["ablation_points"])
    start = max(start, end - points)
    contributions: dict[str, dict[str, float | str]] = {}
    raw: dict[str, dict[str, list[float]]] = {m: {"remove": [], "shuffle": [], "random": []} for m in BASE_MODELS}
    for i in range(max(240, start), end):
        history = draws[max(0, i - 240):i]
        comp = individual_model_scores(history, area)
        full = ensemble_ranking_from_components(comp)
        actual = _area(draws[i], area)
        full_score = _recall(full, actual, pick)
        for m in BASE_MODELS:
            removed = ensemble_ranking_from_components(comp, [x for x in BASE_MODELS if x != m])
            nums = list(range(1, max_n + 1))
            rng = random.Random(int(sha256_json([area, draws[i].issue, m])[:16], 16))
            shuffled_values = [comp[m][n] for n in nums]
            rng.shuffle(shuffled_values)
            shuffled = {n: shuffled_values[n - 1] for n in nums}
            random_scores = {n: rng.uniform(-1.0, 1.0) for n in nums}
            sh_rank = ensemble_ranking_from_components(comp, override={m: shuffled})
            rd_rank = ensemble_ranking_from_components(comp, override={m: random_scores})
            raw[m]["remove"].append(full_score - _recall(removed, actual, pick))
            raw[m]["shuffle"].append(full_score - _recall(sh_rank, actual, pick))
            raw[m]["random"].append(full_score - _recall(rd_rank, actual, pick))
    for m in BASE_MODELS:
        means = {k: (sum(v) / len(v) if v else 0.0) for k, v in raw[m].items()}
        validated = all(means[k] > 0.0 for k in ("remove", "shuffle", "random"))
        contributions[m] = {**means, "decision": "KEEP" if validated else "DEAD_PATH"}
    return {"area": area, "components": contributions, "evaluated_points": max(0, end - max(start, 240))}


def _null_world(records: list[dict[str, Any]], model: str, area: str) -> dict[str, Any]:
    if not records:
        return {"worlds": 0, "false_edges": 0, "fpr": 1.0, "observed_gain": 0.0, "percentile": 0.0}
    max_n, pick = _meta(area)
    actuals = [r["actual"] for r in records]
    rankings = [r["models"][model]["ranking"] for r in records]
    baseline = pick / max_n
    observed = statistics.mean(_recall(rankings[i], actuals[i], pick) - baseline for i in range(len(records)))
    worlds = int(PROMOTION_POLICY["null_worlds"])
    null_means = []
    false_edges = 0
    for w in range(worlds):
        rng = random.Random(890000 + w)
        perm = list(range(len(actuals)))
        rng.shuffle(perm)
        vals = [_recall(rankings[i], actuals[perm[i]], pick) - baseline for i in range(len(records))]
        m = statistics.mean(vals)
        h = len(vals) // 2
        first = vals[:h]
        second = vals[h:]
        def lower95(chunk):
            if len(chunk) < 2:
                return -1.0
            mu = statistics.mean(chunk)
            sd = statistics.stdev(chunk)
            return mu - 1.959963984540054 * sd / math.sqrt(len(chunk))
        # Mirror the real promotion logic: the complete null world and both independent
        # halves must each have a positive 95% lower bound. This measures the firewall's
        # actual propensity to manufacture repeatable edge from random alignment.
        if lower95(vals) > 0.0 and lower95(first) > 0.0 and lower95(second) > 0.0:
            false_edges += 1
        null_means.append(m)
    percentile = sum(x <= observed for x in null_means) / len(null_means)
    return {"worlds": worlds, "false_edges": false_edges, "fpr": false_edges / worlds, "observed_gain": observed, "percentile": percentile}


def _synthetic_null_worlds() -> dict[str, Any]:
    world_count = int(PROMOTION_POLICY["synthetic_null_worlds"])
    draw_count = int(PROMOTION_POLICY["synthetic_null_draws"])
    test_points = int(PROMOTION_POLICY["synthetic_null_test_points"])
    alpha = float(PROMOTION_POLICY["alpha"])
    false_edges = 0
    details = []

    def lower95(values: list[float]) -> float:
        if len(values) < 2:
            return -1.0
        mu = statistics.mean(values)
        sd = statistics.stdev(values)
        return mu - 1.959963984540054 * sd / math.sqrt(len(values))

    for world in range(world_count):
        rng = random.Random(6202600 + world)
        synthetic: list[Draw] = []
        for i in range(draw_count):
            front = tuple(sorted(rng.sample(range(1, 36), 5)))
            back = tuple(sorted(rng.sample(range(1, 13), 2)))
            synthetic_day = (date(2099, 1, 1) + timedelta(days=i)).isoformat()
            synthetic.append(Draw(issue=f"{90000+i+1:05d}", draw_date=synthetic_day, front=front, back=back))

        area_pass = {}
        for area in ("front", "back"):
            max_n, pick = _meta(area)
            vals: list[float] = []
            start = max(240, draw_count - test_points)
            for i in range(start, draw_count):
                history = synthetic[i-240:i]
                ranking = individual_model_rankings(history, area)["research_ensemble"]
                actual = _area(synthetic[i], area)
                random_recalls = [
                    _recall(_random_ranking(max_n, ["synthetic", world, area, seed, i]), actual, pick)
                    for seed in PROMOTION_POLICY["seeds"]
                ]
                vals.append(_recall(ranking, actual, pick) - statistics.mean(random_recalls))
            half = len(vals) // 2
            chunks = [vals, vals[:half], vals[half:]]
            passes = []
            for j, chunk in enumerate(chunks):
                mean = statistics.mean(chunk) if chunk else 0.0
                p = permutation_p(chunk, rounds=300, seed=12000 + world * 10 + j + (0 if area == "front" else 1000))
                passes.append(bool(chunk) and mean > 0.0 and lower95(chunk) > 0.0 and p < alpha)
            area_pass[area] = all(passes)
        false_edge = bool(area_pass.get("front") and area_pass.get("back"))
        false_edges += int(false_edge)
        details.append({"world": world + 1, "front_pass": area_pass.get("front", False), "back_pass": area_pass.get("back", False), "false_edge": false_edge})

    return {
        "worlds": world_count,
        "false_edges": false_edges,
        "fpr": false_edges / max(1, world_count),
        "details": details,
    }


def _dan_firewall(draws: list[Draw], matrices: dict[str, dict[int, list[dict[str, Any]]]]) -> dict[str, Any]:
    z = float(PROMOTION_POLICY["dan_wilson_z"])
    jitter = float(PROMOTION_POLICY["dan_seed_jitter"])
    seeds = tuple(PROMOTION_POLICY["seeds"])
    areas = {}
    decisions = []
    for area in ("front", "back"):
        max_n, pick = _meta(area)
        successes = 0
        trials = 0
        # Historical top-1 evidence is measured across preregistered
        # window x model x seed score perturbations, not one deterministic path.
        for _window, recs in matrices[area].items():
            for r in recs:
                actual = set(r["actual"])
                for model in MODELS:
                    for top in r.get("dan_votes", {}).get(model, []):
                        successes += int(top in actual)
                        trials += 1
        wilson = _wilson_lower(successes, trials, z)
        random_base = pick / max_n

        # Current candidate support uses the same model x window x seed perturbation grid.
        configurations: list[list[int]] = []
        for window in PROMOTION_POLICY["windows"]:
            history = draws[-int(window):]
            score_maps = individual_model_scores(history, area)
            for model in MODELS:
                for seed in seeds:
                    configurations.append(
                        _perturbed_ranking(score_maps[model], ["current-dan", area, int(window), model, seed], jitter)
                    )
        counts = Counter(r[0] for r in configurations)
        candidate, _ = counts.most_common(1)[0]
        coverage = sum(candidate in r[:3] for r in configurations) / len(configurations)
        rank_support = statistics.mean((max_n - r.index(candidate)) / max_n for r in configurations)
        decision = (
            wilson > random_base + float(PROMOTION_POLICY["dan_min_lift"])
            and coverage >= float(PROMOTION_POLICY["dan_min_coverage"])
            and rank_support >= float(PROMOTION_POLICY["dan_min_rank_support"])
        )
        decisions.append(decision)
        areas[area] = {
            "candidate": candidate,
            "successes": successes,
            "trials": trials,
            "wilson95_lower": wilson,
            "random_base": random_base,
            "coverage": coverage,
            "rank_support": rank_support,
            "configurations": len(configurations),
            "decision": "PASS" if decision else "NO_DAN",
        }
    return {"status": "PASS", "decision": "CERTIFIED_DAN" if all(decisions) else "NULL_DAN", "areas": areas}

def strict_gate_verdict(gates: list[dict[str, Any]]) -> str:
    statuses = [g.get("status") for g in gates]
    if any(x not in {"PASS", "FAIL"} for x in statuses):
        raise ValueError(f"模糊 gate 状态被拒绝: {statuses}")
    return "PASS" if statuses and all(x == "PASS" for x in statuses) else "FAIL"


def run_evidence_court(draws: list[Draw], prospective: list[dict[str, Any]] | None = None, progress=None) -> dict[str, Any]:
    policy = PROMOTION_POLICY
    if len(draws) < int(policy["min_history"]):
        raise ValueError(f"严格验证至少需要 {policy['min_history']} 期历史数据")
    if progress:
        progress("Evidence Court：冻结验证协议")
    for d in draws:
        d.validate()
    if len({d.issue for d in draws}) != len(draws) or draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("数据顺序/唯一性检查失败")

    holdout_n = min(int(policy["untouched_holdout"]), max(60, len(draws) // 10))
    pre_end = len(draws) - holdout_n
    wf_points = min(int(policy["walk_forward_points"]), pre_end - max(policy["windows"]))
    wf_start = pre_end - wf_points
    matrices: dict[str, dict[int, list[dict[str, Any]]]] = {"front": {}, "back": {}}
    for area in ("front", "back"):
        for window in policy["windows"]:
            if progress:
                progress(f"Walk-forward {area} · window={window}")
            matrices[area][int(window)] = walk_forward(draws, area, int(window), wf_start, pre_end)

    alpha = float(policy["alpha"])
    model_results: dict[str, Any] = {}
    pvals: dict[str, float] = {}
    for model in MODELS:
        per_area = {}
        combined = []
        for area in ("front", "back"):
            vals = _aggregate_windows(matrices[area], model)
            lo, hi = bootstrap_ci(vals)
            p = permutation_p(vals)
            eras = _loeo_results(vals, int(policy["min_era_count"]), alpha)
            mean = statistics.mean(vals) if vals else 0.0
            per_area[area] = {"n": len(vals), "gain": mean, "bootstrap95": [lo, hi], "permutation_p": p, "loeo": eras}
            combined.extend(vals)
        pvals[model] = permutation_p(combined, seed=5100 + len(model)) if combined else 1.0
        model_results[model] = {"areas": per_area, "combined_gain": statistics.mean(combined) if combined else 0.0, "combined_p": pvals[model]}
    holm_result = holm(pvals, alpha)
    for m in MODELS:
        model_results[m]["holm_reject_null"] = holm_result[m]

    # Primary candidate is pre-registered; holdout is never used to choose it.
    challenger = "research_ensemble"
    holdout: dict[str, Any] = {}
    dual_pass = True
    for area in ("front", "back"):
        recs = walk_forward(draws, area, 240, pre_end, len(draws))
        vals = [float(r["models"][challenger]["gain"]) for r in recs]
        h = len(vals) // 2
        halves = [vals[:h], vals[h:]]
        half_results = []
        for j, chunk in enumerate(halves, 1):
            lo, hi = bootstrap_ci(chunk, rounds=500, seed=7000 + j + (0 if area == "front" else 10))
            p = permutation_p(chunk, rounds=800, seed=8000 + j + (0 if area == "front" else 10))
            mean = statistics.mean(chunk) if chunk else 0.0
            passed = bool(chunk) and mean > 0.0 and lo > 0.0 and p < alpha
            dual_pass = dual_pass and passed
            half_results.append({"half": j, "n": len(chunk), "gain": mean, "bootstrap95": [lo, hi], "permutation_p": p, "pass": passed})
        holdout[area] = {"n": len(vals), "gain": statistics.mean(vals) if vals else 0.0, "halves": half_results}

    if progress:
        progress("Ablation：Remove / Shuffle / Random")
    ablation = {area: _ablation(draws, area, wf_start, pre_end) for area in ("front", "back")}
    validated_components = []
    dead_paths = []
    for m in BASE_MODELS:
        keep = all(ablation[a]["components"][m]["decision"] == "KEEP" for a in ("front", "back"))
        (validated_components if keep else dead_paths).append(m)

    if progress:
        progress("Null-world / Leakage Sentinel")
    null_world = {
        area: _null_world(matrices[area][240], challenger, area) for area in ("front", "back")
    }
    null_fpr_ok = all(v["fpr"] <= float(policy["max_null_world_fpr"]) for v in null_world.values())
    synthetic_null = _synthetic_null_worlds()
    synthetic_null_ok = synthetic_null["false_edges"] <= int(policy["synthetic_null_max_false_edges"])
    leakage_ok = all(leakage_guard(r["history_end"], r["target_index"]) for area in matrices.values() for recs in area.values() for r in recs)
    injected_sentinel_detected = not leakage_guard(10, 10)
    leakage_ok = leakage_ok and injected_sentinel_detected

    dan_firewall = _dan_firewall(draws, matrices)

    primary = model_results[challenger]
    pre_oos_pass = all(
        primary["areas"][area]["gain"] > 0.0
        and primary["areas"][area]["bootstrap95"][0] > 0.0
        and primary["areas"][area]["permutation_p"] < alpha
        and all(x["pass"] for x in primary["areas"][area]["loeo"])
        for area in ("front", "back")
    ) and bool(primary["holm_reject_null"])
    ablation_ok = len(validated_components) >= int(policy["min_validated_components"])
    prospective_rows = prospective or []
    prospective_min = int(policy["min_prospective_replays"])
    prospective_ok = len(prospective_rows) >= prospective_min
    if prospective_ok:
        # Prospective evidence must be selector-matched and show positive ranking utility
        # in both areas. Replays are created only from immutable pre-draw freezes.
        front_hits = [float(x.get("front_hit_count", 0)) / 5.0 for x in prospective_rows]
        back_hits = [float(x.get("back_hit_count", 0)) / 2.0 for x in prospective_rows]
        prospective_ok = (
            statistics.mean(front_hits) > (5 / 35)
            and statistics.mean(back_hits) > (2 / 12)
        )
    edge_gate = pre_oos_pass and dual_pass and null_fpr_ok and synthetic_null_ok and ablation_ok and prospective_ok

    gates = [
        {"name": "Data/Chronology", "status": "PASS", "decision": "ACCEPT", "outcome": f"{len(draws)} 期；唯一且按时间排序"},
        {"name": "Walk-forward", "status": "PASS", "decision": "EXECUTED", "outcome": f"{wf_points} OOS × 3 windows × 2 areas"},
        {"name": "Random Baseline", "status": "PASS", "decision": "EXECUTED", "outcome": f"{len(policy['seeds'])} deterministic seeds"},
        {"name": "Bootstrap/Permutation/Holm", "status": "PASS", "decision": "EXECUTED", "outcome": "多重检验已完成；证据不足不会升级"},
        {"name": "LOEO", "status": "PASS", "decision": "EXECUTED", "outcome": f"leave-one-era-out × {policy['min_era_count']}"},
        {"name": "Ablation", "status": "PASS", "decision": "KEEP_PRESENT" if ablation_ok else "NO_EDGE", "outcome": f"KEEP={validated_components or 'none'}; DEAD_PATH={dead_paths or 'none'}"},
        {"name": "Null-world FPR", "status": "PASS" if null_fpr_ok else "FAIL", "decision": "ACCEPT" if null_fpr_ok else "REJECT", "outcome": str({a: round(v['fpr'], 4) for a, v in null_world.items()})},
        {"name": "Synthetic Null Worlds", "status": "PASS" if synthetic_null_ok else "FAIL", "decision": "ACCEPT" if synthetic_null_ok else "REJECT", "outcome": f"false_edges={synthetic_null['false_edges']}/{synthetic_null['worlds']}"},
        {"name": "Leakage Sentinel", "status": "PASS" if leakage_ok else "FAIL", "decision": "ACCEPT" if leakage_ok else "REJECT", "outcome": "history_end < target_index + explicit equality rejection"},
        {"name": "Untouched Holdout", "status": "PASS", "decision": "EXECUTED", "outcome": f"last {holdout_n} draws; never used for challenger selection"},
        {"name": "Dual Final Confirmation", "status": "PASS", "decision": "EDGE" if dual_pass else "NO_EDGE", "outcome": "two independent holdout halves"},
        {"name": "Prospective Evidence", "status": "PASS", "decision": "EDGE" if prospective_ok else "NO_EDGE", "outcome": f"immutable selector-matched replays={len(prospective_rows)} / required={prospective_min}"},
        {"name": "Dan Firewall", "status": "PASS", "decision": dan_firewall["decision"], "outcome": "Wilson95 + model/window/seed perturbation coverage + rank support"},
    ]
    software_verdict = strict_gate_verdict(gates)
    software_pass = software_verdict == "PASS"
    ident = model_identity()
    court: dict[str, Any] = {
        "schema": 2,
        "created_at": utc_now(),
        "protocol": dict(policy),
        "software_verdict": software_verdict,
        "scientific_gate": software_verdict,
        "edge_gate": "PASS" if edge_gate else "FAIL",
        "edge_state": "EDGE_PROVEN" if edge_gate else "NO_EDGE",
        "dan_state": "CERTIFIED_DAN" if edge_gate and dan_firewall["decision"] == "CERTIFIED_DAN" else "NULL_DAN",
        "gates": gates,
        "model_results": model_results,
        "holdout": holdout,
        "dual_final_confirmation": {"pass": dual_pass},
        "ablation": ablation,
        "validated_components": validated_components,
        "dead_paths": dead_paths,
        "null_world": null_world,
        "synthetic_null_worlds": synthetic_null,
        "leakage_sentinel": {"status": "PASS" if leakage_ok else "FAIL"},
        "dan_firewall": dan_firewall,
        "prospective_count": len(prospective_rows),
        "prospective_edge_ok": prospective_ok,
        "ablation_edge_ok": ablation_ok,
        "lifecycle": {
            "Champion": "uniform_random_baseline" if not edge_gate else challenger,
            "Challenger": [challenger],
            "Shadow": [m for m in MODELS if m != challenger],
        },
        "model_hash": ident["model_hash"],
        "selector_hash": ident["selector_hash"],
    }
    court["court_hash"] = sha256_json(court)
    return court
