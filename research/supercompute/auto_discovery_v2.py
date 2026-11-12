"""V2 falsification-first research: freeze automatically discovered formulas before holdout.

A validation-only search selects a fixed expression roster, independent of every
test outcome. During holdout, residual parameters may update from previous
observations, but formula IDs, weights and selection policy never change.
Does not produce or authorize any formal lottery forecast.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path

from research.supercompute import auto_discovery as v1
from research.supercompute import engine

SCHEMA = "SSQDLT_FORMULA_DISCOVERY_V2_FROZEN_HOLDOUT"
DEFAULT_VALIDATION = 60
DEFAULT_HOLDOUT = 120
MIN_TRAIN = 180
EXPERTS = 8
MAX_PER_FAMILY = 2
CONTROL_IDS = ("FROZEN_RESEARCH_NULL", "HOT60", "EWMA30")


def frozen_selection(rows, game, validation_start, test_start):
    """Choose formula IDs from development outcomes, never final test outcomes."""
    if game not in engine.SPECS:
        raise ValueError("unsupported lottery")
    if type(validation_start) is not int or type(test_start) is not int:
        raise ValueError("invalid split types")
    if validation_start < MIN_TRAIN or not validation_start + 20 <= test_start <= len(rows):
        raise ValueError("must have at least 180 training and 20 validation draws")
    fm, fp, bm, bp = engine.SPECS[game]
    n = test_start - validation_start
    objective_spec = "FRONT_AND_BACK_COVERAGE_ONLY_NO_D2_TUNING"
    all_candidates = []
    for expr in v1.GRAMMAR:
        front_hits = back_hits = 0
        ticket_hashes = []
        for i in range(validation_start, test_start):
            # Historical actual i is deliberately not passed into formula fitting.
            pred = v1.candidate(rows[:i], game, expr)
            score = v1.hit_counts(pred, rows[i])
            front_hits += score["front_hits"]
            back_hits += score["back_hits"]
            ticket_hashes.append(v1.digest(pred))
        # Expected overlap under uniform draws, not assumed proof of randomness.
        expected_front = n * fp * fp / fm
        expected_back = n * bp * bp / bm
        relative_gain = (
            (front_hits - expected_front) / (n * fp)
            + (back_hits - expected_back) / (n * bp)
        )
        all_candidates.append({
            "expr": expr,
            "score": round(relative_gain, 10),
            "validation_front_hits": front_hits,
            "validation_back_hits": back_hits,
            "validation_prediction_digest": v1.digest(ticket_hashes),
        })
    all_candidates.sort(key=lambda item: (
        -item["score"], item["expr"]["id"]))
    selected = []
    family_counts = Counter()
    used_behaviors = set()
    for item in all_candidates:
        family = item["expr"]["family"]
        if (family_counts[family] >= MAX_PER_FAMILY
                or item["validation_prediction_digest"] in used_behaviors):
            continue
        family_counts[family] += 1
        used_behaviors.add(item["validation_prediction_digest"])
        selected.append({
            "expr": item["expr"], "weight": 1.0,
            "score_validation_only": item["score"],
            "validation_front_hits": item["validation_front_hits"],
            "validation_back_hits": item["validation_back_hits"],
            "validation_prediction_digest": item["validation_prediction_digest"],
        })
        if len(selected) == EXPERTS:
            break
    if len(selected) != EXPERTS:
        raise RuntimeError("not enough behaviorally distinct formulas")
    record = {
        "game": game,
        "training_last_issue": str(rows[validation_start - 1]["issue"]),
        "validation_first_issue": str(rows[validation_start]["issue"]),
        "validation_last_issue": str(rows[test_start - 1]["issue"]),
        "validation_issues": n,
        "formula_grammar_sha256": v1.digest(v1.GRAMMAR),
        "candidate_count": len(all_candidates),
        "selection_objective": objective_spec,
        "weights": "FROZEN_EQUAL",
        "max_experts": EXPERTS,
        "max_per_family": MAX_PER_FAMILY,
        "expressions": selected,
        "holdout_accessed": False,
        "historical_research_only": True,
    }
    record["selection_sha256"] = v1.digest(record)
    return record


def predict_frozen(history, game, frozen):
    if (frozen["game"] != game or frozen["holdout_accessed"] is not False
            or v1.digest({k: v for k, v in frozen.items()
                          if k != "selection_sha256"}) != frozen["selection_sha256"]):
        raise ValueError("invalid frozen selection or edited hash")
    if int(history[-1]["issue"]) < int(frozen["validation_last_issue"]):
        raise ValueError("forecast made before model frozen")
    if len(frozen["expressions"]) != EXPERTS:
        raise ValueError("incomplete expert set")
    selected = [{"expr": item["expr"], "weight": 1.0}
                for item in frozen["expressions"]]
    p, raw = v1.vote(history, game, selected)
    decision = {
        "asof_issue": str(history[-1]["issue"]),
        "frozen_selection_sha256": frozen["selection_sha256"],
        "candidate": p,
        "selected_formula_ids": [item["formula_id"] for item in raw],
        "type": "RETROSPECTIVE_RESEARCH_NOT_LIVE_FORECAST",
    }
    decision["decision_sha256"] = v1.digest(decision)
    return decision


def controls(history, game, next_issue):
    null = v1.research_null(game, str(next_issue))
    result = {"FROZEN_RESEARCH_NULL": null}
    for name in ("HOT60", "EWMA30"):
        p = engine.ticket(history, game, name)
        result[name] = {
            "front": p["front"], "back": p["back"], "d2_pair": p["dan2"],
        }
    return result


def holm_bonferroni(pvalues):
    if not pvalues or any(
            not isinstance(x, (int, float)) or not math.isfinite(x)
            or x < 0 or x > 1 for x in pvalues):
        raise ValueError("invalid pvalue sequence")
    order = sorted(range(len(pvalues)), key=lambda i: (pvalues[i], i))
    adjusted = [0.0] * len(order)
    maximum = 0.0
    for rank, index in enumerate(order):
        maximum = max(maximum, min(1.0, (len(order) - rank) * pvalues[index]))
        adjusted[index] = maximum
    return adjusted


def compare(rows, control):
    model_only = sum(r["scores"]["FROZEN_FORMULA"]["d2"] == 1
                     and r["scores"][control]["d2"] == 0 for r in rows)
    control_only = sum(r["scores"]["FROZEN_FORMULA"]["d2"] == 0
                       and r["scores"][control]["d2"] == 1 for r in rows)
    both = sum(r["scores"]["FROZEN_FORMULA"]["d2"] == 1
               and r["scores"][control]["d2"] == 1 for r in rows)
    neither = len(rows) - model_only - control_only - both
    if neither < 0:
        raise AssertionError("paired cohort inconsistent")
    return {
        "control": control, "same_issue_n": len(rows),
        "model_only": model_only, "control_only": control_only,
        "both_hit": both, "both_miss": neither,
        "p_exploratory_raw": v1.exact_paired_p(model_only, control_only),
        "scope": "RETROSPECTIVE_NOT_PROSPECTIVE",
    }


def run_game(game, holdout=DEFAULT_HOLDOUT, validation=DEFAULT_VALIDATION):
    if game not in engine.SPECS:
        raise ValueError("unsupported lottery")
    if (type(holdout) is not int or type(validation) is not int
            or not 40 <= holdout <= 300 or not 20 <= validation <= 150):
        raise ValueError("predeclared finite holdout and validation required")
    draws, source = engine.snapshot(game)
    t0 = len(draws) - holdout
    v0 = t0 - validation
    if v0 < MIN_TRAIN:
        raise ValueError("not enough warmup history for independent stages")
    selection = frozen_selection(draws[:t0], game, v0, t0)
    rows = []
    for index in range(t0, len(draws)):
        past = draws[:index]
        decision = predict_frozen(past, game, selection)
        fixed_controls = controls(past, game, draws[index]["issue"])
        scores = {
            "FROZEN_FORMULA": v1.hit_counts(decision["candidate"], draws[index]),
        }
        scores.update({
            name: v1.hit_counts(ticket, draws[index])
            for name, ticket in fixed_controls.items()
        })
        rows.append({
            "issue": str(draws[index]["issue"]),
            "asof_issue": str(past[-1]["issue"]),
            "selection_sha256": selection["selection_sha256"],
            "decision_sha256": decision["decision_sha256"],
            "predicted_ticket": decision["candidate"],
            "controls": fixed_controls,
            "scores": scores,
        })
    assert len(rows) == holdout and len({row["issue"] for row in rows}) == holdout
    assert all(row["selection_sha256"] == selection["selection_sha256"]
               for row in rows)
    summaries = {
        name: {
            "d2_hits": sum(r["scores"][name]["d2"] for r in rows),
            "full_hits": sum(r["scores"][name]["exact"] for r in rows),
            "front_hits_total": sum(r["scores"][name]["front_hits"] for r in rows),
            "back_hits_total": sum(r["scores"][name]["back_hits"] for r in rows),
        } for name in ("FROZEN_FORMULA",) + CONTROL_IDS
    }
    paired = [compare(rows, name) for name in CONTROL_IDS]
    p_adj = holm_bonferroni([x["p_exploratory_raw"] for x in paired])
    for item, p in zip(paired, p_adj):
        item["p_exploratory_holm"] = p
        item["comparisons_corrected"] = len(CONTROL_IDS)
        item["not_credible_proof_of_edge"] = True
    return {
        "source": source,
        "holdout_size": holdout,
        "holdout_first_issue": rows[0]["issue"],
        "holdout_last_issue": rows[-1]["issue"],
        "selection": selection,
        "rows": rows,
        "summaries": summaries,
        "paired": paired,
        "chance": engine.chance(game),
        "separately_selected_before_holdout": True,
        "all_test_issues_included": True,
        "prospective": False,
        "live_candidate_generated": False,
    }


def build_report(holdout=DEFAULT_HOLDOUT, validation=DEFAULT_VALIDATION):
    games = {
        game: run_game(game, holdout, validation)
        for game in ("ssq", "dlt")
    }
    return {
        "schema": SCHEMA,
        "observed_utc_untrusted": datetime.now(timezone.utc).isoformat(),
        "code_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNVERIFIED"),
        "algorithm": "FROZEN_DEVELOPMENT_SELECTION_ONLINE_PAST_ONLY_CALIBRATION",
        "data_scope": "STALE_REPOSITORY_HISTORY_NOT_CURRENT_OFFICIAL",
        "search": {"grammar_candidates": len(v1.GRAMMAR),
                   "validation": validation,
                   "holdout": holdout,
                   "selection": "FROZEN_ON_DEVELOPMENT_ONLY",
                   "objective": "FRONT_AND_BACK_COVERAGE_NOT_D2",
                   "model_weights": "EQUAL"},
        "games": games,
        "formal_A": 0,
        "formal_prediction": False,
        "edge": "NO_EDGE",
        "prospective_scored": 0,
        "official_source_authenticated": False,
        "sales_cutoff_verified": False,
        "predraw_independent_timestamp_verified": False,
        "unattended_real_scheduler_verified": False,
        "engineering_pass": "NOT_YET",
        "research_valid": "NOT_YET",
        "independent_review": "NOT_VERIFIED",
        "paid_api_calls": 0,
        "official_v47_unchanged": True,
        "next_live_prediction": None,
        "automatic_formal_promotion_allowed": False,
    }


def require_formal_promotion(*args, **kwargs):
    """There is intentionally no path from research to formal prediction."""
    raise PermissionError(
        "FORMAL_BLOCKED: source/cutoff/seal/prospective scoring/review "
        "must be independently verified outside this research pipeline"
    )


def write_once(report, path):
    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True,
                      indent=2, allow_nan=False) + "\n").encode("utf-8")
    with (folder / "report.json").open("xb") as handle:
        handle.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with (folder / "report.sha256").open("x", encoding="ascii") as handle:
        handle.write(sha + "  report.json\n")
    summary = [
        "# V2 自动数学公式发现：冻结公式清单后的历史验证",
        "",
        "该研究不属于正式或当前期预测；冻结的是历史研究公式规则。",
        "",
        "| Game | 公式数 | 开发验证期 | 冻结测试期 | Model D2 | NULL D2 | HOT60 D2 | EWMA30 D2 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in report["games"].items():
        s = r["summaries"]
        summary.append(
            f"| {name.upper()} | {len(v1.GRAMMAR)} | {report['search']['validation']} "
            f"| {r['holdout_size']} | {s['FROZEN_FORMULA']['d2_hits']} "
            f"| {s['FROZEN_RESEARCH_NULL']['d2_hits']} "
            f"| {s['HOT60']['d2_hits']} | {s['EWMA30']['d2_hits']} |"
        )
    summary.extend([
        "",
        "选择过程没有读取最终测试期结果；测试期可以逐期利用之前已观测历史更新残差，",
        "但绝不按测试期结果修改入选公式或权重。",
        "",
        "所有显著性检验均为历史回顾的探索性比较，不能证明未来优势。",
        "正式预测前必须有真实官方源、销售截止、开奖前可信封存、未来逐期评分和独立审核。",
        "NO_EDGE / formal_A=0 / prospective_scored=0 / not_live.",
    ])
    with (folder / "summary.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(summary) + "\n")
    return sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", type=int, default=DEFAULT_HOLDOUT)
    parser.add_argument("--validation", type=int, default=DEFAULT_VALIDATION)
    parser.add_argument("--out", type=Path, default=Path("auto-formula-v2-output"))
    opt = parser.parse_args(argv)
    report = build_report(opt.holdout, opt.validation)
    sha = write_once(report, opt.out)
    print(json.dumps({
        "status": "FROZEN_HISTORICAL_RESEARCH_ONLY",
        "report_sha256": sha,
        "holdout": {name: g["holdout_size"] for name, g in report["games"].items()},
        "d2": {name: {k: v["d2_hits"] for k, v in g["summaries"].items()}
               for name, g in report["games"].items()},
        "formal_A": 0,
        "edge": "NO_EDGE",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
