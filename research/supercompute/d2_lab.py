"""Bounded research-only D2 exact coverage + past-only paired score analysis.

This is not a new Harness; it uses existing supercompute.engine models and
repository historical fixtures. No live official feed, pre-draw seal, source
authentication, ticket purchase, model promotion, or V4.7 ledger mutation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path

from .engine import SPECS, MODELS, check_balls, chance, snapshot, ticket, wilson

# Freeze the fixed exploratory comparison roster before evaluating any rows.
# This is *not* proof of preregistration before the historical outcomes.
RESEARCH_MODELS = ("HOT60", "EWMA30")
FIXED_CONTROL = "RANDOM_NULL"
COMPARISON_ROSTER = tuple(
    (game, model) for game in ("ssq", "dlt")
    for model in RESEARCH_MODELS
)
MAX_PAIR_GROUPS = 4


def _choose(n, k):
    return math.comb(n, k) if 0 <= k <= n else 0


def _validated_edges(pool, pick, pairs):
    if (type(pool) is not int or type(pick) is not int
            or not 2 <= pick <= pool <= 35):
        raise ValueError("invalid front game rules")
    if not isinstance(pairs, (list, tuple)) or not 1 <= len(pairs) <= MAX_PAIR_GROUPS:
        raise ValueError("1..4 D2 pairs are required")
    normalized = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("pair must have two numbers")
        a, b = pair
        if (type(a) is not int or type(b) is not int
                or not 1 <= a < b <= pool):
            raise ValueError("pair is not canonical legal front D2")
        normalized.append((a, b))
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate D2 candidate would overstate portfolio size")
    return tuple(normalized)


def coverage_count(pool, pick, pairs):
    """Exact draw count for >=1 pair by inclusion-exclusion; no simulation.

    For a non-empty subset of m D2 pairs, the intersection event contains
    all distinct balls in those pairs, hence C(pool - |union|, pick - |union|).
    """
    edges = _validated_edges(pool, pick, pairs)
    hit_count = 0
    for count in range(1, len(edges) + 1):
        sign = 1 if count % 2 else -1
        for subset in combinations(edges, count):
            required = set().union(*(set(edge) for edge in subset))
            hit_count += sign * _choose(pool - len(required),
                                       pick - len(required))
    full_space = math.comb(pool, pick)
    if not 0 <= hit_count <= full_space:
        raise AssertionError("invalid exact coverage identity")
    return hit_count


def greedy_coverage(pool, pick, number_pairs):
    """Deterministic myopic maximum marginal coverage; NOT global optimality.

    Candidate set spans ALL C(pool,2) D2 pairs. Exact coverage is recomputed
    with combinatorial inclusion-exclusion; no random draw or future leakage.
    """
    if type(number_pairs) is not int or not 1 <= number_pairs <= MAX_PAIR_GROUPS:
        raise ValueError("number_pairs must be 1..4")
    if type(pool) is not int or type(pick) is not int or not 2 <= pick <= pool <= 35:
        raise ValueError("invalid front game rules")
    chosen = []
    all_pairs = list(combinations(range(1, pool + 1), 2))
    progress = []
    for _ in range(number_pairs):
        best_pair = None
        best_score = -1
        for candidate in all_pairs:
            if candidate in chosen:
                continue
            score = coverage_count(pool, pick, chosen + [candidate])
            if score > best_score:
                best_pair, best_score = candidate, score
        assert best_pair is not None
        chosen.append(best_pair)
        progress.append(best_score)
    # The deliberately overlapping star is a fixed, unoptimized comparator,
    # not official RANDOM_NULL (the latter is the paired historical control).
    baseline = [(1, i) for i in range(2, 2 + number_pairs)]
    baseline_count = coverage_count(pool, pick, baseline)
    space = math.comb(pool, pick)
    if progress != sorted(progress):
        raise AssertionError("adding a distinct D2 pair decreased coverage")
    return {
        "pair_count": number_pairs,
        "greedy_pairs": [list(p) for p in chosen],
        "greedy_not_global_optimum_certified": True,
        "greedy_coverage_by_step": progress,
        "coverage_count": progress[-1],
        "coverage_denominator": space,
        "coverage_probability": progress[-1] / space,
        "baseline_kind": "FIXED_OVERLAPPING_STAR_NOT_RANDOM_NULL",
        "baseline_pairs": [list(p) for p in baseline],
        "baseline_coverage_count": baseline_count,
        "baseline_coverage_probability": baseline_count / space,
        "fair_single_pair_probability": pick * (pick - 1) / (pool * (pool - 1)),
        "full_ticket_probability_unchanged_per_one_ticket": True,
        "caveat": (
            "A set of m distinct D2 pairs covers more potential front draws "
            "than a single pair; this is not a per-ticket edge, not a winner "
            "prediction and not an optimal payout or betting strategy."
        ),
    }


def paired_two_sided(model_only, control_only):
    """Exact two-sided McNemar/binomial test for paired binary outcomes.

    Only discordant observations contribute. No asymptotic chi-square; no
    assumed independence between two model successes on the SAME draw.
    """
    if (type(model_only) is not int or type(control_only) is not int
            or min(model_only, control_only) < 0):
        raise ValueError("nonnegative integer discordant counts required")
    n = model_only + control_only
    if not n:
        return 1.0
    extreme = min(model_only, control_only)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(extreme + 1)) / 2 ** n)


def holm_adjust(pvalues):
    if not pvalues or any(
            not isinstance(p, (int, float)) or not math.isfinite(p)
            or not 0 <= p <= 1 for p in pvalues):
        raise ValueError("one or more invalid exact p-values")
    ranked = sorted(enumerate(pvalues), key=lambda row: (row[1], row[0]))
    adjusted = [None] * len(ranked)
    prior = 0.0
    total = len(ranked)
    for index, (original, pvalue) in enumerate(ranked):
        prior = min(1.0, max(prior, (total - index) * pvalue))
        adjusted[original] = prior
    return adjusted


def evaluate_history(rows, game, periods, seed):
    """Complete original-order historical heldout roster; target never in input.

    It is an *exploratory* retrospective experiment. Each ticket uses only
    prior rows and all fixed models share the same score target and control.
    """
    if game not in SPECS:
        raise ValueError("unknown lottery")
    if type(periods) is not int or type(seed) is not int or not 1 <= periods <= 500:
        raise ValueError("invalid research periods or seed")
    if not isinstance(rows, list) or len(rows) < periods + 120:
        raise ValueError("insufficient full 120-draw historical warmup")
    front_max, front_pick, back_max, back_pick = SPECS[game]
    issues, dates = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid draw object")
        issue = str(row.get("issue", ""))
        day = str(row.get("draw_date", ""))
        if not issue.isdecimal():
            raise ValueError("invalid or missing issue")
        datetime.fromisoformat(day + "T00:00:00")
        check_balls(row.get("front"), front_pick, front_max)
        check_balls(row.get("back"), back_pick, back_max)
        issues.append(int(issue))
        dates.append(day)
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("draw dates missing, reordered or duplicated")
    # Lottery issue numbers increment within a year. Annual numbering restarts
    # at ...001; permit only a plausible old-year terminal issue (140..165),
    # and never silently accept a skipped issue in the middle of the year.
    for previous, current in zip(issues, issues[1:]):
        if current == previous + 1:
            continue
        rollover = (current // 1000 == previous // 1000 + 1
                    and current % 1000 == 1
                    and 140 <= previous % 1000 <= 165)
        if not rollover:
            raise ValueError("missing, duplicate, or ambiguous draw issue")
    start = len(rows) - periods
    if start < 120:
        raise ValueError("insufficient past-only warmup; never truncate cohort")
    records = []
    for index in range(start, len(rows)):
        prior = rows[:index]
        actual = rows[index]
        arms = {}
        for model in (FIXED_CONTROL,) + RESEARCH_MODELS:
            selection = ticket(prior, game, model, seed)
            d2_hit = int(set(selection["dan2"]).issubset(actual["front"]))
            front_hits = len(set(selection["front"]) & set(actual["front"]))
            back_hits = len(set(selection["back"]) & set(actual["back"]))
            full_hit = int(selection["front"] == actual["front"]
                           and selection["back"] == actual["back"])
            arms[model] = {
                "ticket": {
                    "front": selection["front"],
                    "back": selection["back"], "d2": selection["dan2"],
                },
                "d2_hit": d2_hit,
                "front_hits": front_hits,
                "back_hits": back_hits,
                "full_hit": full_hit,
            }
        records.append({
            "issue": str(actual["issue"]),
            "draw_date_from_historical_snapshot": str(actual["draw_date"]),
            "asof_issue": str(prior[-1]["issue"]),
            "arms": arms,
        })
    if len(records) != periods or len({r["issue"] for r in records}) != periods:
        raise RuntimeError("selected history cohort incomplete")
    summaries = {}
    for model in (FIXED_CONTROL,) + RESEARCH_MODELS:
        d2_hits = sum(rec["arms"][model]["d2_hit"] for rec in records)
        summaries[model] = {
            "evaluated": periods,
            "d2_hits": d2_hits,
            "d2_rate": d2_hits / periods,
            "d2_wilson95": wilson(d2_hits, periods),
            "full_hits": sum(rec["arms"][model]["full_hit"] for rec in records),
            "sum_front_ball_hits": sum(
                rec["arms"][model]["front_hits"] for rec in records),
            "sum_back_ball_hits": sum(
                rec["arms"][model]["back_hits"] for rec in records),
        }
    return {
        "game": game,
        "evaluated": periods,
        "first_evaluated_issue": records[0]["issue"],
        "last_evaluated_issue": records[-1]["issue"],
        "models": summaries,
        "rows": records,
        "strictly_past_only": True,
        "same_issue_paired_null": True,
        "sample_type": "HISTORICAL_RETROSPECTIVE_EXPLORATORY_NOT_REGISTERED",
        "no_dropped_losses": True,
        "full_roster_sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode()).hexdigest(),
    }


def build_report(*, periods=200, max_pairs=4, seed=2026):
    if type(seed) is not int or type(periods) is not int:
        raise ValueError("periods and seed must be integers")
    if type(max_pairs) is not int:
        raise ValueError("max_pairs must be integer")
    games = {}
    comparisons = []
    for game in ("ssq", "dlt"):
        draws, source = snapshot(game)
        history = evaluate_history(draws, game, periods, seed)
        front_max, front_pick, _, _ = SPECS[game]
        portfolio = greedy_coverage(front_max, front_pick, max_pairs)
        games[game] = {
            "source": source,
            "historical_study": history,
            "exact_d2_portfolio": portfolio,
            "fair_baseline": chance(game),
        }
        for model in RESEARCH_MODELS:
            pairs = [(row["arms"][model]["d2_hit"],
                      row["arms"][FIXED_CONTROL]["d2_hit"])
                     for row in history["rows"]]
            model_only = sum(a == 1 and b == 0 for a, b in pairs)
            null_only = sum(a == 0 and b == 1 for a, b in pairs)
            both_hit = sum(a == b == 1 for a, b in pairs)
            both_miss = sum(a == b == 0 for a, b in pairs)
            if model_only + null_only + both_hit + both_miss != periods:
                raise RuntimeError("paired comparison incomplete")
            comparisons.append({
                "game": game, "model": model, "control": FIXED_CONTROL,
                "evaluated": periods,
                "model_d2_hits": model_only + both_hit,
                "null_d2_hits": null_only + both_hit,
                "model_only": model_only, "null_only": null_only,
                "both_hit": both_hit, "both_miss": both_miss,
                "net_hits_over_same_issue_null": model_only - null_only,
                "p_raw": paired_two_sided(model_only, null_only),
                "method": "TWO_SIDED_EXACT_MCNEMAR_CONDITIONAL_BINOMIAL",
            })
    if [(x["game"], x["model"]) for x in comparisons] != list(COMPARISON_ROSTER):
        raise RuntimeError("fixed comparison family changed")
    adj = holm_adjust([row["p_raw"] for row in comparisons])
    for row, p in zip(comparisons, adj):
        row["p_holm"] = p
        row["family_size"] = len(comparisons)
        row["edge_confirmation"] = "NO_NOT_FUTURE_PREREGISTERED"
    return {
        "schema": "SSQDLT_D2_COVERAGE_PAIRED_EXPLORATORY_V1",
        "created_utc_observed_untrusted": datetime.now(timezone.utc).isoformat(),
        "github_source_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNVERIFIED"),
        "research_control_seed": seed,
        "games": games,
        "model_comparisons": comparisons,
        "comparison_family": [{"game": g, "model": m}
                              for g, m in COMPARISON_ROSTER],
        "holms_registration": "POST_HOC_RESEARCH_ONLY_NO_PRE_REGISTRATION_PROOF",
        "data_warning": "Checked-in historical snapshots, NOT latest official draws",
        "prospective_sample_size": 0,
        "official_source_authenticated": False,
        "trusted_predraw_tsa_verified": False,
        "postdraw_authentic_outcome_scored": False,
        "two_actual_schedule_triggers_verified": False,
        "live_v47_closed_loop": "BLOCKED_UNVERIFIED",
        "p0_blockers": [
            "Official live latest-issue independent source identity and draw-date semantics not authenticated",
            "True next issue and authoritative earliest sales cutoff not independently authenticated",
            "No approved RFC3161 predraw timestamp verification against cutoff",
            "No eligible matched future scored cohort or independently witnessed Windows cold boot",
        ],
        "engineering_pass": "NOT_YET",
        "research_valid": "NOT_YET",
        "d2_edge_confirmed": "NO",
        "formal_A": 0, "edge": "NO_EDGE",
        "paid_api_calls": 0,
        "no_purchase_or_ticket_execution": True,
    }


def render_summary(report):
    lines = [
        "# SSQ＋DLT D2 研究验证与组合覆盖报告",
        "",
        "**仅探索性历史回测；不是最新一期预测，不代表单注中奖率提高。**",
        "",
        "本次正式工程验收：ENGINEERING_PASS=NOT_YET；RESEARCH_VALID=NOT_YET；formal_A=0；NO_EDGE。",
        "",
        "## 同期开奖的固定 RANDOM_NULL 逐期配对比较（双侧精确检验）",
        "",
        "| 彩种 | 模型 | 研究样本 | D2模型命中 | 同期NULL命中 | 净增 | 原始p | Holm校正p |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["model_comparisons"]:
        lines.append(
            f"| {row['game'].upper()} | {row['model']} | {row['evaluated']} "
            f"| {row['model_d2_hits']} | {row['null_d2_hits']} "
            f"| {row['net_hits_over_same_issue_null']:+d} "
            f"| {row['p_raw']:.6g} | {row['p_holm']:.6g} |"
        )
    lines += [
        "",
        "说明：这些模型和比较项目并非在历史开奖号码出现前预注册。即使显著，也不能宣称发现前瞻预测优势。",
        "",
        "## 固定数量 D2 组合的精确理论覆盖（公平开奖假设）",
        "",
        "| 彩种 | D2组数 | 贪心组 | 组合覆盖/全部前区组合 | 重叠基线覆盖 |",
        "|---|---:|---|---:|---:|",
    ]
    for game, payload in report["games"].items():
        item = payload["exact_d2_portfolio"]
        lines.append(
            f"| {game.upper()} | {item['pair_count']} "
            f"| {item['greedy_pairs']} "
            f"| {item['coverage_count']}/{item['coverage_denominator']} "
            f"| {item['baseline_coverage_count']}/{item['coverage_denominator']} |"
        )
    lines += [
        "",
        "注意：增加D2组数本身会增加覆盖事件，但需要更多独立选号。任何一注完整号码的头奖理论概率并未改变。",
        "",
        "## P0 阻断与证据边界",
        "",
        "目前使用仓库历史快照，无独立认证的最新官方数据、可信事前封存或真实合格前瞻评分；所有新未来样本数=0。",
        "",
        "| 彩种 | 历史截止期 | 历史源 SHA256 |",
        "|---|---|---|",
    ]
    for game, payload in report["games"].items():
        src = payload["source"]
        lines.append(
            f"| {game.upper()} | {src['asof_issue']} ({src['asof_date']}) "
            f"| `{src['sha256']}` |"
        )
    lines += [
        "",
        "完整每期原始模型命中/未命中、同一期开奖结果的NULL评分、配对检验、全部对照组及文件校验详见 report.json、report.sha256。",
        "",
    ]
    return "\n".join(lines)


def write_report(report, output):
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True,
                      indent=2, allow_nan=False) + "\n").encode("utf-8")
    with (target / "report.json").open("xb") as fp:
        fp.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with (target / "report.sha256").open("x", encoding="ascii") as fp:
        fp.write(sha + "  report.json\n")
    with (target / "summary.md").open("x", encoding="utf-8") as fp:
        fp.write(render_summary(report))
    return sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=int, default=200)
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path,
                        default=Path("d2-research-report"))
    args = parser.parse_args(argv)
    report = build_report(periods=args.periods,
                          max_pairs=args.pairs, seed=args.seed)
    sha = write_report(report, args.out)
    print(json.dumps({
        "status": "RESEARCH_ONLY_NOT_V47",
        "historical_cohorts": {
            game: payload["historical_study"]["evaluated"]
            for game, payload in report["games"].items()
        },
        "comparisons": len(report["model_comparisons"]),
        "report_sha256": sha, "edge": report["edge"],
        "formal_A": report["formal_A"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
