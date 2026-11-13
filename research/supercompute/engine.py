"""CPU-parallel, research-only SSQ/DLT backtester. No live forecasts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"ssq": ROOT / "SSQ/SSQ/resources/official_seed.json",
           "dlt": ROOT / "DLT/src/resources/official_seed.json"}
SPECS = {"ssq": (33, 6, 16, 1), "dlt": (35, 5, 12, 2)}
MODELS = ("HOT60", "EWMA30")


def derive_seed(*parts):
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8], "big")


def check_balls(nums, pick, ceiling):
    if not isinstance(nums, list) or len(nums) != pick:
        raise ValueError("invalid ball count")
    if any(type(x) is not int or x < 1 or x > ceiling for x in nums):
        raise ValueError("out-of-range ball")
    if nums != sorted(set(nums)):
        raise ValueError("balls must be increasing and distinct")
    return nums


def snapshot(game, path=None):
    path = Path(path) if path is not None else SOURCES[game]
    raw = path.read_bytes()
    obj = json.loads(raw)
    if str(obj.get("game", "")).lower() != game:
        raise ValueError("snapshot game mismatch")
    rows = obj.get("draws")
    if not isinstance(rows, list) or len(rows) < 121:
        raise ValueError("insufficient history")
    fm, fp, bm, bp = SPECS[game]
    seen, latest = set(), ""
    for row in rows:
        issue, day = str(row["issue"]), str(row["draw_date"])
        date.fromisoformat(day)
        if not issue or issue in seen or day < latest:
            raise ValueError("duplicate issue or unordered dates")
        seen.add(issue)
        latest = day
        check_balls(row["front"], fp, fm)
        check_balls(row["back"], bp, bm)
    return rows, {
        "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(rows), "asof_issue": rows[-1]["issue"],
        "asof_date": rows[-1]["draw_date"],
        "status": "historical_snapshot_not_live_verified",
    }


def rank(history, area, ceiling, model):
    score = [0.0] * (ceiling + 1)
    if model == "HOT60":
        for row in history[-60:]:
            for x in row[area]:
                score[x] += 1
    elif model == "EWMA30":
        for age, row in enumerate(reversed(history[-240:])):
            for x in row[area]:
                score[x] += 2 ** (-age / 30)
    else:
        raise ValueError("unknown research model")
    return sorted(range(1, ceiling + 1), key=lambda x: (-score[x], x))


def ticket(history, game, model, seed=2026):
    if not history:
        raise ValueError("must have past draws")
    fm, fp, bm, bp = SPECS[game]
    front, back = rank(history, "front", fm, model)[:fp], rank(history, "back", bm, model)[:bp]
    return {"front": sorted(front), "back": sorted(back),
            "dan2": sorted(front[:2]), "after_issue": history[-1]["issue"],
            "formal_prediction": False}


def chance(game):
    fm, fp, bm, bp = SPECS[game]
    return {"dan2_probability": fp * (fp - 1) / (fm * (fm - 1)),
            "full_ticket_one_in": math.comb(fm, fp) * math.comb(bm, bp)}


def wilson(hits, trials):
    if trials < 1:
        raise ValueError("no trials")
    z = 1.959963984540054
    p = hits / trials
    den = 1 + z * z / trials
    mid = (p + z * z / (2 * trials)) / den
    spread = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / den
    return [max(0, mid - spread), min(1, mid + spread)]


def walk_forward(rows, game, periods, seed):
    if not 1 <= periods <= 2000:
        raise ValueError("backtest must be 1..2000")
    start = max(120, len(rows) - periods)
    counts = {m: {"dan2": 0, "full": 0} for m in MODELS}
    for index in range(start, len(rows)):
        actual = rows[index]
        for model in MODELS:
            prediction = ticket(rows[:index], game, model, seed)
            counts[model]["dan2"] += int(set(prediction["dan2"]).issubset(actual["front"]))
            counts[model]["full"] += int(prediction["front"] == actual["front"] and
                                         prediction["back"] == actual["back"])
    n = len(rows) - start
    for summary in counts.values():
        summary.update(evaluated=n, dan2_rate=summary["dan2"] / n,
                       dan2_wilson95=wilson(summary["dan2"], n))
    return {"first_evaluated_issue": rows[start]["issue"],
            "last_evaluated_issue": rows[-1]["issue"],
            "strictly_past_only": True, "prospective": False, "models": counts}


def mc_block(args):
    game, seed, block, n = args
    fm, fp, _, _ = SPECS[game]
    rng = random.Random(derive_seed(seed, game, "monte_carlo", block))
    found = 0
    population = range(1, fm + 1)
    for _ in range(n):
        picked = rng.sample(population, fp)
        found += int(1 in picked and 2 in picked)
    return found


def simulate(game, trials, workers, seed):
    if not 1 <= trials <= 2000000 or not 1 <= workers <= 8:
        raise ValueError("simulate: trials 1..2000000 and workers 1..8")
    block_size = 5000
    chunks = [(game, seed, i, min(block_size, trials - i * block_size))
              for i in range((trials + block_size - 1) // block_size)]
    start = time.perf_counter()
    if workers == 1:
        hits = sum(map(mc_block, chunks))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            hits = sum(pool.map(mc_block, chunks))
    return {"seed": seed, "workers": workers, "trials": trials,
            "dan2_hits": hits, "dan2_rate": hits / trials,
            "dan2_wilson95": wilson(hits, trials),
            "duration_seconds": round(time.perf_counter() - start, 3),
            "assumption": "uniform_independent_draws",
            "stable_across_worker_counts": True}


def compute(game, periods, trials, workers, seed):
    rows, meta = snapshot(game)
    return {"snapshot": meta, "baseline": chance(game),
            "historical_walk_forward": walk_forward(rows, game, periods, seed),
            "uniform_monte_carlo": simulate(game, trials, workers, seed),
            "hypothetical_post_snapshot_candidates": {
                model: ticket(rows, game, model, seed) for model in MODELS},
            "edge": "NO_EDGE", "formal_A": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=("ssq", "dlt", "both"), default="both")
    parser.add_argument("--backtest", type=int, default=200)
    parser.add_argument("--simulate", type=int, default=50000)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("supercompute-output"))
    opt = parser.parse_args(argv)
    games = ("ssq", "dlt") if opt.game == "both" else (opt.game,)
    result = {"schema": "SSQDLT_CPU_RESEARCH_V1",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "code_sha": os.getenv("GITHUB_SHA", "LOCAL_UNVERIFIED"),
              "data_warning": "Snapshot only. Not a verified real-time or future draw.",
              "paid_api_calls": 0,
              "games": {game: compute(game, opt.backtest, opt.simulate,
                                       opt.workers, opt.seed) for game in games}}
    opt.out.mkdir(parents=True, exist_ok=True)
    receipt = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with (opt.out / "report.json").open("x", encoding="utf-8") as handle:
        handle.write(receipt)
    with (opt.out / "report.sha256").open("x", encoding="ascii") as handle:
        handle.write(hashlib.sha256(receipt.encode("utf-8")).hexdigest() + "  report.json\n")
    print(json.dumps({"output": str(opt.out), "summary": {
        g: {"asof": value["snapshot"]["asof_issue"], "edge": value["edge"]}
        for g, value in result["games"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def compute_v47_research(game, periods=30, trials=10000, seed=2026):
    """Explicit opt-in research report for 11 components.

    Keeps legacy compute()/MODELS, formal predictors, frozen receipts and earlier archived receipts
    experiments untouched. Reads repository historical snapshots, NOT live
    official results. No valid claim of forecasting advantage.
    """
    from research.supercompute.v47_models import (
        MODELS as V47_LAB_MODELS, backtest as v47_backtest,
        candidates as v47_candidates, geometry_state, m1_math,
        monte_carlo as v47_mc, physics_toy,
    )
    rows, meta = snapshot(game)
    examples = {name: v47_candidates(rows, game, name, limit=1, seed=seed)[0]
                for name in V47_LAB_MODELS}
    return {"snapshot": meta, "m1": m1_math(rows, game, examples["HOT60"]),
            "historical_walk_forward": v47_backtest(rows, game, periods, seed),
            "geometry": geometry_state(rows, game),
            "uniform_monte_carlo": v47_mc(game, trials, seed),
            "uncalibrated_physics_toy": physics_toy(game, seed),
            "hypothetical_candidates": examples,
            "edge": "NO_EDGE", "formal_A": 0, "formal_prediction": False}
