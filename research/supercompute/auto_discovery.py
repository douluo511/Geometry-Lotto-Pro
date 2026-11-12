"""Automatic bounded mathematical-expression discovery for SSQ/DLT (research only).

A grammar enumerates new candidate formula trees and rolling calibration windows.
At every historical target, candidates are evaluated only against earlier draws.
This deliberately does NOT issue or promote formal forecasts. A fair random
lottery cannot be made predictable by searching more formulas.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random

from research.supercompute.engine import SPECS, chance, derive_seed, snapshot

SCHEMA = "SSQDLT_AUTOMATIC_FORMULA_DISCOVERY_V1"
ATOMS = ("LAG1", "LAG2", "LAG3", "ISSUE")
OPERATIONS = ("ATOM", "DOUBLE", "ADD", "SUB", "MUL")
WINDOWS = (8, 16)
VALIDATION = 10
MAX_EXPERTS = 8
MAX_PER_FAMILY = 2


def digest(obj):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def grammar():
    """Generate candidate expression trees algorithmically, not from fitted outcomes."""
    expressions = []
    for op in ("ATOM", "DOUBLE"):
        expressions.extend((op, atom, None) for atom in ATOMS)
    for op in ("ADD", "SUB", "MUL"):
        for i, left in enumerate(ATOMS):
            for j, right in enumerate(ATOMS):
                if op in ("ADD", "MUL") and j < i:
                    continue
                if (op == "SUB" or op == "ADD") and i == j:
                    continue  # x+x is already DOUBLE(x); x-x is constant
                expressions.append((op, left, right))
    result = []
    for op, left, right in expressions:
        for window in WINDOWS:
            result.append({
                "id": f"{op}:{left}:{right or 'NONE'}:W{window}",
                "family": op,
                "op": op, "left": left, "right": right, "window": window,
            })
    if len({x["id"] for x in result}) != len(result):
        raise AssertionError("duplicate formula grammar")
    return tuple(result)


GRAMMAR = grammar()


def atom_value(atom, history, index, area, pos):
    if atom == "ISSUE":
        return int(history[index - 1]["issue"]) + 1
    lag = {"LAG1": 1, "LAG2": 2, "LAG3": 3}[atom]
    return history[index - lag][area][pos] - 1


def evaluate_expr(expr, history, index, area, pos, modulus):
    if index < 3 or index > len(history):
        raise ValueError("formula requires three strictly previous draws")
    a = atom_value(expr["left"], history, index, area, pos)
    op = expr["op"]
    if op == "ATOM":
        value = a
    elif op == "DOUBLE":
        value = 2 * a
    else:
        b = atom_value(expr["right"], history, index, area, pos)
        value = {"ADD": lambda: a + b, "SUB": lambda: a - b,
                 "MUL": lambda: a * b}[op]()
    return value % modulus


def learn_offset(expr, history, index, area, pos, modulus):
    """Fit modular residual from the last W known target observations only."""
    start = max(3, index - expr["window"])
    residuals = Counter(
        (history[j][area][pos] - 1 -
         evaluate_expr(expr, history, j, area, pos, modulus)) % modulus
        for j in range(start, index)
    )
    if not residuals:
        raise ValueError("empty causal training interval")
    return min(residuals, key=lambda r: (-residuals[r], r))


def complete_balls(raw, maximum, count, *, game, asof, formula_id, area):
    """Remove duplicates and fill missing positions by deterministic SHA rank."""
    if not raw or not all(1 <= x <= maximum for x in raw):
        raise ValueError("invalid candidate balls")
    ordered = list(dict.fromkeys(raw))
    if len(ordered) < count:
        remaining = [v for v in range(1, maximum + 1) if v not in ordered]
        remaining.sort(key=lambda n: derive_seed(
            "AUTO_FORMULA_DEDUP_V1", game, asof, formula_id, area, n))
        ordered += remaining[:count - len(ordered)]
    return ordered[:count]


def candidate(history, game, expr):
    if game not in SPECS or len(history) < 40:
        raise ValueError("invalid game or insufficient historical prefix")
    fm, fp, bm, bp = SPECS[game]
    index = len(history)
    asof = str(history[-1]["issue"])
    raw = {}
    for area, maximum, count in (("front", fm, fp), ("back", bm, bp)):
        raw[area] = [
            1 + (evaluate_expr(expr, history, index, area, pos, maximum)
                 + learn_offset(expr, history, index, area, pos, maximum)) % maximum
            for pos in range(count)
        ]
    front = complete_balls(raw["front"], fm, fp, game=game, asof=asof,
                           formula_id=expr["id"], area="front")
    back = complete_balls(raw["back"], bm, bp, game=game, asof=asof,
                          formula_id=expr["id"], area="back")
    return {"front": sorted(front), "back": sorted(back),
            "d2_pair": sorted(front[:2])}


def hit_counts(pred, actual):
    return {
        "d2": int(set(pred["d2_pair"]).issubset(actual["front"])),
        "front_hits": len(set(pred["front"]).intersection(actual["front"])),
        "back_hits": len(set(pred["back"]).intersection(actual["back"])),
        "exact": int(pred["front"] == actual["front"] and
                     pred["back"] == actual["back"]),
    }


def research_null(game, target_issue):
    """Unchanging same-issue random control; separate from official V4.7 NULL."""
    fm, fp, bm, bp = SPECS[game]
    rng = random.Random(derive_seed("AUTO_DISCOVERY_RESEARCH_NULL_V1",
                                    game, str(target_issue)))
    d2 = rng.sample(range(1, fm + 1), 2)
    remaining = [x for x in range(1, fm + 1) if x not in d2]
    front = sorted(d2 + rng.sample(remaining, fp - 2))
    back = sorted(rng.sample(range(1, bm + 1), bp))
    return {"front": front, "back": back, "d2_pair": sorted(d2)}


def vote(history, game, chosen):
    fm, fp, bm, bp = SPECS[game]
    votes = {"front": defaultdict(float), "back": defaultdict(float)}
    predictions = []
    for item in chosen:
        pick = candidate(history, game, item["expr"])
        predictions.append({"formula_id": item["expr"]["id"], "ticket": pick})
        for area in ("front", "back"):
            for ball in pick[area]:
                votes[area][ball] += item["weight"]
    asof = str(history[-1]["issue"])
    ranks = {}
    for area, maximum in (("front", fm), ("back", bm)):
        ranks[area] = sorted(
            range(1, maximum + 1),
            key=lambda n: (-votes[area][n],
                           derive_seed("AUTO_VOTE_TIE_V1", game, asof, area, n)),
        )
    front = sorted(ranks["front"][:fp])
    back = sorted(ranks["back"][:bp])
    d2 = sorted(ranks["front"][:2])
    if not set(d2).issubset(front):
        raise AssertionError("D2 not subset of front")
    return {"front": front, "back": back, "d2_pair": d2}, predictions


def discover(history, game, *, validation=VALIDATION):
    """Nested chronological search. Target outcome is never an argument."""
    if game not in SPECS or len(history) < 120:
        raise ValueError("minimum 120 observed training rows required")
    if not 4 <= validation <= 20 or validation >= len(history) - 40:
        raise ValueError("invalid validation window")
    fm, fp, bm, bp = SPECS[game]
    p_d2 = chance(game)["dan2_probability"]
    scored = []
    for expr in GRAMMAR:
        counts = {"d2": 0, "front_hits": 0, "back_hits": 0}
        # Every validation prediction fits only the prefix before its date.
        for idx in range(len(history) - validation, len(history)):
            predicted = candidate(history[:idx], game, expr)
            actual = history[idx]
            observed = hit_counts(predicted, actual)
            for key in counts:
                counts[key] += observed[key]
        # Nonprobabilistic ranking metric, penalized by chance expectations.
        gain = (
            2.0 * (counts["d2"] - validation * p_d2)
            + (counts["front_hits"] - validation * fp * fp / fm) / fp
            + 0.5 * (counts["back_hits"] - validation * bp * bp / bm) / bp
        ) / validation
        scored.append({"expr": expr, "counts": counts,
                       "gain": round(gain, 8)})
    scored.sort(key=lambda x: (-x["gain"], -x["counts"]["d2"],
                               -x["counts"]["front_hits"], x["expr"]["id"]))
    chosen = []
    family_count = Counter()
    for item in scored:
        family = item["expr"]["family"]
        if family_count[family] >= MAX_PER_FAMILY:
            continue
        family_count[family] += 1
        chosen.append({"expr": item["expr"], "gain": item["gain"],
                       "validation_counts": item["counts"],
                       "weight": round(max(0.5, min(2.0,
                                                    1 + item["gain"] / 2)), 4)})
        if len(chosen) == MAX_EXPERTS:
            break
    if len(chosen) != MAX_EXPERTS:
        raise AssertionError("incomplete expert roster")
    prediction, expert_tickets = vote(history, game, chosen)
    audit = {
        "game": game, "asof_issue": str(history[-1]["issue"]),
        "formula_grammar_sha256": digest(GRAMMAR),
        "candidates_evaluated": len(GRAMMAR),
        "validation_periods": validation,
        "last_validation_observed_issue": str(history[-1]["issue"]),
        "selected": [{
            "formula_id": x["expr"]["id"], "expression": x["expr"],
            "past_validation_hits": x["validation_counts"],
            "past_validation_gain": x["gain"], "weight": x["weight"]
        } for x in chosen],
        "expert_tickets": expert_tickets,
        "prediction": prediction,
        "type": "UNAUTHENTICATED_OFFLINE_RESEARCH_CANDIDATE",
    }
    audit["decision_sha256"] = digest(audit)
    return audit


def exact_paired_p(model_only, null_only):
    """Two-sided exact paired discordance test; exploratory, not preregistered."""
    n = model_only + null_only
    return min(1.0, 2 * sum(math.comb(n, k)
                           for k in range(min(model_only, null_only) + 1))
               / 2 ** n) if n else 1.0


def run_game(game, periods=40):
    if game not in SPECS or not 1 <= periods <= 80:
        raise ValueError("invalid game or historical evaluation size")
    rows, meta = snapshot(game)
    if len(rows) - periods < 120:
        raise ValueError("insufficient strictly earlier draw history")
    evidence = []
    for i in range(len(rows) - periods, len(rows)):
        past = rows[:i]
        decision = discover(past, game)
        actual = rows[i]  # Never passed to discover().
        null = research_null(game, actual["issue"])
        model_score = hit_counts(decision["prediction"], actual)
        null_score = hit_counts(null, actual)
        evidence.append({
            "target_issue": str(actual["issue"]),
            "observed_asof_issue": str(past[-1]["issue"]),
            "decision_sha256": decision["decision_sha256"],
            "candidate": decision["prediction"],
            "null_ticket": null,
            "model_hits": model_score, "null_hits": null_score,
            "formula_ids": [x["formula_id"] for x in decision["selected"]],
            "selected_weights": [x["weight"] for x in decision["selected"]],
            "source": "checked_in_historical_snapshot_only",
        })
    model_hits = sum(r["model_hits"]["d2"] for r in evidence)
    null_hits = sum(r["null_hits"]["d2"] for r in evidence)
    model_only = sum(r["model_hits"]["d2"] == 1 and r["null_hits"]["d2"] == 0
                     for r in evidence)
    null_only = sum(r["model_hits"]["d2"] == 0 and r["null_hits"]["d2"] == 1
                    for r in evidence)
    both = sum(r["model_hits"]["d2"] == 1 and r["null_hits"]["d2"] == 1
               for r in evidence)
    if model_hits != model_only + both or null_hits != null_only + both:
        raise AssertionError("paired controls inconsistent")
    offline_next = discover(rows, game)
    return {
        "data": meta,
        "cohort_size": periods,
        "evidence": evidence,
        "paired_same_issue": {
            "model_d2_hits": model_hits, "null_d2_hits": null_hits,
            "model_only": model_only, "null_only": null_only,
            "both": both, "neither": periods - model_only - null_only - both,
            "p_two_sided_exploratory": exact_paired_p(model_only, null_only),
            "theoretical_chance_d2": chance(game)["dan2_probability"],
            "no_multiple_search_inference": True,
        },
        "offline_next_after_stale_snapshot": {
            "asof_issue": meta["asof_issue"],
            "decision": offline_next,
            "not_live": True,
            "not_formal": True,
        },
    }


def build_report(periods=40):
    games = {g: run_game(g, periods) for g in ("ssq", "dlt")}
    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "code_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNVERIFIED"),
        "source_type": "STALE_CHECKED_IN_SNAPSHOT_NOT_OFFICIAL_LIVE",
        "algorithm": "ENUMERATED_EXPRESSION_GRAMMAR_NESTED_PAST_ONLY_ROLLING_SELECTION",
        "formula_candidates_per_decision": len(GRAMMAR),
        "formal_prediction": False, "formal_A": 0,
        "prospective_scored": 0,
        "pre_draw_independent_seal_verified": False,
        "official_source_authenticated": False,
        "official_sales_cutoff_verified": False,
        "edge": "NO_EDGE",
        "engineering_pass": "NOT_YET",
        "research_valid": "NOT_YET",
        "statistical_significance": "NOT_CLAIMED_POSTHOC_DISCOVERY",
        "original_v47_and_official_null_unchanged": True,
        "paid_api_calls": 0,
        "games": games,
    }


def write_once(report, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, indent=2) + "\n").encode("utf-8")
    with (folder / "report.json").open("xb") as f:
        f.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with (folder / "report.sha256").open("x", encoding="ascii") as f:
        f.write(sha + "  report.json\n")
    summary = [
        "# 自动数学公式发现：时间顺序探索研究",
        "",
        "不是正式预测，不具备已证明的预测优势。所有来源仅为旧历史快照。",
        "",
        "| Game | 历史回测 | 公式候选/期 | 自动筛选专家/期 | D2模型 | 同期随机NULL | 精确配对探索p |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for game, rec in report["games"].items():
        c = rec["paired_same_issue"]
        summary.append(
            f"| {game.upper()} | {rec['cohort_size']} | {len(GRAMMAR)} "
            f"| {MAX_EXPERTS} | {c['model_d2_hits']} | {c['null_d2_hits']} "
            f"| {c['p_two_sided_exploratory']:.6f} |"
        )
    summary += [
        "",
        "公式语法、候选选择规则、训练窗口和随机对照全部在代码中预先固定；",
        "回测是模型研究后的历史探索，而不是独立开奖前预测验证。",
        "升级为正式预测之前，必须独立验证官方来源、销售截止、封存时间、",
        "前瞻性真实开奖评分、复核和统计证据。",
        "formal_A=0; edge=NO_EDGE; prospective_scored=0.",
        "",
    ]
    with (folder / "summary.md").open("x", encoding="utf-8") as f:
        f.write("\n".join(summary))
    return sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=int, default=40)
    parser.add_argument("--out", type=Path, default=Path("auto-formula-output"))
    opt = parser.parse_args(argv)
    report = build_report(periods=opt.periods)
    sha = write_once(report, opt.out)
    print(json.dumps({
        "status": "AUTOMATIC_DISCOVERY_HISTORICAL_ONLY",
        "report_sha256": sha,
        "grammar_candidates": len(GRAMMAR),
        "evaluated": {g: v["cohort_size"] for g, v in report["games"].items()},
        "d2": {g: v["paired_same_issue"] for g, v in report["games"].items()},
        "edge": "NO_EDGE", "formal_A": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
