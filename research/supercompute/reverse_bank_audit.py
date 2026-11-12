"""Pinned Reverse Formula Bank: causal ablations and same-issue controls.

Research-only. Uses the ORIGINAL formula_bank code checked out at an exact
immutable Git commit, without copying it to main or mutating V4.7/ledger.
Input is repo historical snapshot (not independently authenticated latest).
All retrospective tests are exploratory, never proof of lottery prediction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys

from research.supercompute.engine import snapshot, SPECS

ORIGINAL_PIN = "199cc2a2797f11b8179aaa6649f0649613c72010"
METHODS = (
    "previous_plus_offset",
    "previous_mirror_plus_offset",
    "previous_double_plus_offset",
    "two_back_plus_offset",
    "previous_two_sum_plus_offset",
    "issue_index_plus_offset",
)
ARMS = ("FULL_WEIGHTED", "FULL_EQUAL") + tuple("DROP_" + m for m in METHODS)
PLACEBO_SEEDS = tuple(range(32))
GAMES = {}
_bank = _probe = _reverse = None


def validate_dependencies(checkout: Path, expected_sha: str):
    """Refuse other versions and load pinned original modules at runtime only."""
    global _bank, _probe, _reverse, GAMES
    if expected_sha != ORIGINAL_PIN:
        raise ValueError("formula source must match predeclared original PIN")
    checkout = Path(checkout).resolve()
    if (not checkout.is_dir()
            or not (checkout / "research/inverse_formula/formula_bank.py").is_file()):
        raise ValueError("original formula source checkout absent")
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("original source Git identity unavailable") from exc
    if actual != expected_sha:
        raise ValueError("original reverse formula source SHA mismatch")
    # Python's research package is a namespace when no __init__ is supplied;
    # adding the original checkout exposes research.inverse_formula without
    # overwriting local research.supercompute.
    if str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    from research.inverse_formula import formula_bank, probe, reverse_search
    if tuple(formula_bank.METHODS) != METHODS or tuple(reverse_search.METHODS) != METHODS:
        raise ValueError("original formula family roster mismatch")
    _bank, _probe, _reverse = formula_bank, probe, reverse_search
    GAMES = {"ssq": probe.SSQ, "dlt": probe.DLT}
    return {"source_commit": actual,
            "families": list(METHODS),
            "source_contract": "PINNED_ORIGINAL_READ_ONLY"}


def _ready():
    if not GAMES or _bank is None or _probe is None or _reverse is None:
        raise RuntimeError("original formula dependencies not PIN verified")


def _sha(data):
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def prediction_ticket(original):
    p = original["prediction"]
    return {key: list(p[key]) for key in ("front", "back", "d2_pair")}


def original_prediction(prefix, game):
    _ready()
    if game not in GAMES:
        raise ValueError("unknown game")
    return _bank.predict_with_bank(prefix, GAMES[game])


def validate_roster(draws):
    """Require strictly contiguous same-year historical issues and legal balls."""
    _ready()
    if not isinstance(draws, list) or len(draws) < 16:
        raise ValueError("insufficient original draw roster")
    if any(not isinstance(x, _probe.Draw) for x in draws):
        raise ValueError("wrong draw type")
    for a, b in zip(draws, draws[1:]):
        if b.issue != a.issue + 1:
            raise ValueError("missing or out-of-order research draw issue")
        if a.issue // 1000 != b.issue // 1000:
            raise ValueError("cross-year draw slice not supported")
    if len({x.issue for x in draws}) != len(draws):
        raise ValueError("duplicated historical issue")
    # Test both versions of issue format using only valid 2026-year subsets.
    for row in draws:
        if row.issue <= 0:
            raise ValueError("invalid draw issue")
    return True


def load_game(game, *, periods=40):
    _ready()
    if game not in GAMES or type(periods) is not int or not 1 <= periods <= 50:
        raise ValueError("invalid game or research horizon")
    data, source = snapshot(game)
    wanted = ("2026" if game == "ssq" else "26")
    raw = [r for r in data if str(r["issue"]).startswith(wanted)]
    draws = [
        _probe.Draw(int(row["issue"]), tuple(row["front"]),
                    tuple(row["back"])) for row in raw
    ]
    validate_roster(draws)
    if len(draws) < periods + 30:
        raise ValueError("not enough strictly historical warmup draws")
    # Independently binding the inputs to a named, immutable JSON blob hash.
    meta = {**source, "2026_rows": len(draws),
            "2026_first_issue": draws[0].issue,
            "2026_last_issue": draws[-1].issue,
            "formula_source_commit": ORIGINAL_PIN,
            "latest_official_authenticated": False}
    return draws, meta


def _selection(prefix, game, bank, arm):
    """Re-rank known-past catalog only; never inspect target outcome."""
    if arm not in ARMS:
        raise ValueError("unknown experiment arm")
    pool = [row for row in bank
            if not arm.startswith("DROP_") or row["family"] != arm[5:]]
    chosen = _bank._rank(pool, max_per_family=2, top_k=12)
    if not chosen or len({x["formula_id"] for x in chosen}) != len(chosen):
        raise ValueError("invalid or duplicate original candidate formula")
    front = defaultdict(float)
    back = defaultdict(float)
    game_spec = GAMES[game]
    for row in chosen:
        predicted_front, predicted_back = _reverse.apply_formula(
            row["formula"], prefix, game_spec)
        weight = 1.0 if arm == "FULL_EQUAL" else row["vote_weight"]
        for n in predicted_front:
            front[n] += weight
        for n in predicted_back:
            back[n] += weight
    f_order = sorted(range(1, game_spec.front_max + 1),
                     key=lambda num: (-front[num], num))
    b_order = sorted(range(1, game_spec.back_max + 1),
                     key=lambda num: (-back[num], num))
    d2 = sorted(f_order[:2])
    chosen_front = sorted(f_order[:game_spec.front_pick])
    chosen_back = sorted(b_order[:game_spec.back_pick])
    if not set(d2).issubset(chosen_front):
        raise AssertionError("D2 not in original vote-ranking front")
    return {
        "prediction": {"front": chosen_front, "back": chosen_back,
                       "d2_pair": d2},
        "selected_formula_ids": [r["formula_id"] for r in chosen],
        "selected_families": [r["family"] for r in chosen],
        "selected_weights": [1.0 if arm == "FULL_EQUAL"
                             else r["vote_weight"] for r in chosen],
    }


def decide(prefix, game):
    _ready()
    if game not in GAMES or not prefix:
        raise ValueError("missing past-only game history")
    validate_roster(prefix)
    original_catalog = _bank.catalog(prefix, GAMES[game], lookback=24,
                                     min_followups=5)
    result = {}
    for arm in ARMS:
        decision = _selection(prefix, game, original_catalog, arm)
        decision["decision_sha256"] = _sha({
            "game": game, "asof": prefix[-1].issue, "arm": arm,
            "prediction": decision["prediction"],
            "selected_formula_ids": decision["selected_formula_ids"],
            "selected_weights": decision["selected_weights"],
            "original_source_commit": ORIGINAL_PIN,
        })
        result[arm] = decision
    # Must reproduce original FULL_WEIGHTED ticket exactly, not just a cousin.
    expected = prediction_ticket(original_prediction(prefix, game))
    if result["FULL_WEIGHTED"]["prediction"] != expected:
        raise RuntimeError("original Reverse Formula Bank behavior diverged")
    return result


def _score(ticket, actual):
    predicted = ticket["prediction"] if "prediction" in ticket else ticket
    front = predicted["front"]
    back = predicted["back"]
    d2 = predicted["d2_pair"]
    return {
        "front_hits": len(set(front).intersection(actual.front)),
        "back_hits": len(set(back).intersection(actual.back)),
        "d2_hit": int(set(d2).issubset(actual.front)),
        "full_hit": int(tuple(front) == actual.front
                        and tuple(back) == actual.back),
    }


def _placebo_ticket(game, issue, stream):
    _ready()
    if type(issue) is not int or issue <= 0 or stream not in PLACEBO_SEEDS:
        raise ValueError("invalid research placebo identity")
    g = GAMES[game]
    raw = _sha(["RFB_V2_PLACEBO_SHA256", game, issue, stream])
    rng = random.Random(int(raw[:16], 16))
    d2 = sorted(rng.sample(range(1, g.front_max + 1), 2))
    remaining = [n for n in range(1, g.front_max + 1) if n not in d2]
    front = sorted(d2 + rng.sample(remaining, g.front_pick - 2))
    back = sorted(rng.sample(range(1, g.back_max + 1), g.back_pick))
    return {"front": front, "back": back, "d2_pair": d2}


def exact_two_sided(a, b):
    if type(a) is not int or type(b) is not int or a < 0 or b < 0:
        raise ValueError("nonnegative integer discordant counts required")
    n = a + b
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(a, b) + 1))
               / (2 ** n)) if n else 1.0


def holm(pvalues):
    if not pvalues or any(
            type(x) not in (int, float) or not math.isfinite(x)
            or x < 0 or x > 1 for x in pvalues):
        raise ValueError("invalid multiple-comparison p-values")
    result = [0.0] * len(pvalues)
    previous = 0.0
    for index, (original, p) in enumerate(
            sorted(enumerate(pvalues), key=lambda z: (z[1], z[0]))):
        previous = min(1.0, max(previous, (len(pvalues) - index) * p))
        result[original] = previous
    return result


def run_game(game, *, periods=40):
    _ready()
    draws, source = load_game(game, periods=periods)
    begin = len(draws) - periods
    rows = []
    placebo_hits = {stream: 0 for stream in PLACEBO_SEEDS}
    for idx in range(begin, len(draws)):
        prefix = draws[:idx]
        actual = draws[idx]  # Never passed to catalog/decide.
        if actual.issue != prefix[-1].issue + 1:
            raise ValueError("missing or unexpected target issue")
        decisions = decide(prefix, game)
        # Original research NULL uses preknown target issue identity only;
        # it is distinct from the fixed official V4.7 Random NULL seed.
        null_ticket, pair = _bank._research_null(actual.issue, GAMES[game])
        null = {"front": list(null_ticket[0]),
                "back": list(null_ticket[1]), "d2_pair": list(pair)}
        arm_rows = {
            arm: {
                "ticket": decision["prediction"],
                "selected_formula_ids": decision["selected_formula_ids"],
                "selected_families": decision["selected_families"],
                "decision_sha256": decision["decision_sha256"],
                **_score(decision, actual),
            } for arm, decision in decisions.items()
        }
        ctrl = {"ticket": null, **_score(null, actual)}
        for stream in PLACEBO_SEEDS:
            placebo_hits[stream] += _score(
                _placebo_ticket(game, actual.issue, stream), actual)["d2_hit"]
        rows.append({
            "issue": actual.issue,
            "asof_issue": prefix[-1].issue,
            "actual_from_old_snapshot": {
                "front": list(actual.front), "back": list(actual.back)},
            "arms": arm_rows,
            "control": ctrl,
        })
    if (len(rows) != periods or
            len({row["issue"] for row in rows}) != periods):
        raise AssertionError("incomplete or cherry-picked historical cohort")
    summaries = {}
    for arm in ARMS:
        summaries[arm] = {
            "evaluated": periods,
            "d2_hits": sum(row["arms"][arm]["d2_hit"] for row in rows),
            "full_hits": sum(row["arms"][arm]["full_hit"] for row in rows),
            "front_hits_total": sum(
                row["arms"][arm]["front_hits"] for row in rows),
            "back_hits_total": sum(
                row["arms"][arm]["back_hits"] for row in rows),
        }
        summaries[arm]["d2_rate"] = summaries[arm]["d2_hits"] / periods
    ctrl_hits = sum(row["control"]["d2_hit"] for row in rows)
    next_decision = decide(draws, game)
    hypothetical = {
        "target_issue_unverified": draws[-1].issue + 1,
        "asof_issue": draws[-1].issue,
        "not_live_prediction": True,
        "model": "FULL_WEIGHTED",
        "candidate": next_decision["FULL_WEIGHTED"]["prediction"],
        "decision_sha256": next_decision["FULL_WEIGHTED"]["decision_sha256"],
        "disclaimer": ("Historical checked-in snapshot only; no authenticated "
                       "latest result or cutoff. Never call formal forecast."),
    }
    return {
        "game": game,
        "source": source,
        "evaluated": periods,
        "rows": rows,
        "arm_summary": summaries,
        "control_summary": {
            "evaluated": periods, "d2_hits": ctrl_hits,
            "d2_rate": ctrl_hits / periods,
            "identity": "PINNED_RESEARCH_NULL_NOT_OFFICIAL_V47",
        },
        "placebo_d2_hits": [placebo_hits[i] for i in PLACEBO_SEEDS],
        "placebo_seed_method": "32 predefined SHA256 issue-based placebo D2 streams",
        "theoretical_d2_probability": (
            GAMES[game].front_pick * (GAMES[game].front_pick - 1)
            / (GAMES[game].front_max * (GAMES[game].front_max - 1))),
        "full_roster_sha256": _sha(rows),
        "hypothetical_next_candidate": hypothetical,
        "study_type": "RETROSPECTIVE_MODEL_SELECTED_AFTER_DATA_NOT_PROSPECTIVE",
    }


def build_report(*, periods=40):
    _ready()
    games = {game: run_game(game, periods=periods)
             for game in ("ssq", "dlt")}
    comparisons = []
    for game, record in games.items():
        for arm in ARMS:
            model_only = sum(r["arms"][arm]["d2_hit"] == 1
                             and r["control"]["d2_hit"] == 0
                             for r in record["rows"])
            control_only = sum(r["arms"][arm]["d2_hit"] == 0
                               and r["control"]["d2_hit"] == 1
                               for r in record["rows"])
            both = sum(r["arms"][arm]["d2_hit"] == 1
                       and r["control"]["d2_hit"] == 1
                       for r in record["rows"])
            neither = periods - model_only - control_only - both
            if min(model_only, control_only, both, neither) < 0:
                raise AssertionError("negative incomplete cohort")
            comparisons.append({
                "game": game, "arm": arm, "paired_issues": periods,
                "model_only": model_only,
                "null_only": control_only,
                "both_hit": both,
                "both_miss": neither,
                "model_d2_hits": model_only + both,
                "same_issue_null_d2_hits": control_only + both,
                "net_over_null": model_only - control_only,
                "p_raw": exact_two_sided(model_only, control_only),
                "method": "TWO_SIDED_EXACT_PAIRED_DISCORDANCE",
            })
    if len(comparisons) != 16:
        raise AssertionError("research test family changed")
    for item, corrected in zip(
            comparisons, holm([row["p_raw"] for row in comparisons])):
        item["p_holm"] = corrected
        item["family_count"] = 16
        item["meaning"] = "POST_HOC_EXPLORATORY_P_VALUE_NOT_A_FUTURE_EDGE"
    return {
        "schema": "SSQDLT_REVERSE_FORMULA_BANK_ABLATION_V1",
        "observed_utc_untrusted": datetime.now(timezone.utc).isoformat(),
        "github_code_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNVERIFIED"),
        "original_formula_code_sha": ORIGINAL_PIN,
        "algorithm": "PINNED_REVERSE_FORMULA_BANK_SIX_FAMILIES",
        "original_formula_unchanged": True,
        "candidate_generation": {
            "families": list(METHODS),
            "lookback": 24, "min_followups": 5,
            "top_k": 12, "max_per_family": 2,
            "weights": "capped 0.3..2.0 original vote_weight",
        },
        "fixed_arm_roster": list(ARMS),
        "source_warning": ("Historical checked-in snapshots only; SSQ last "
                           "2026109, DLT last 26108; no live official verification."),
        "games": games,
        "paired_comparisons": comparisons,
        "test_family_registration": "POST_HOC_EXPLORATION_NO_INDEPENDENT_PREREGISTRATION",
        "prospective_scored": 0,
        "official_outcomes_authenticated": False,
        "predraw_independent_timestamp_verified": False,
        "actual_schedule_runs_verified": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
        "engineering_pass": "NOT_YET",
        "research_valid": "NOT_YET",
        "d2_edge_confirmed": "NO",
        "independent_review": "NOT_VERIFIED",
        "paid_api_calls": 0,
        "prediction_not_for_ticket_purchase": True,
    }


def render_summary(report):
    lines = [
        "# 逆向公式库：六类公式逐类消融与等权加权对照",
        "",
        "实验为**历史探索**，不是未来正式预测；不宣称加权公式可预测独立开奖。",
        "",
        f"原始公式源（PIN）：`{ORIGINAL_PIN}`；正式V4.7未变；",
        "`ENGINEERING_PASS=NOT_YET` / `RESEARCH_VALID=NOT_YET` / `NO_EDGE`",
        "",
        "| 彩种 | 模型 | 历史期数 | D2命中 | 同期NULL | 净增 | Holm校正p |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["paired_comparisons"]:
        lines.append(
            f"| {row['game'].upper()} | {row['arm']} "
            f"| {row['paired_issues']} | {row['model_d2_hits']} "
            f"| {row['same_issue_null_d2_hits']} | {row['net_over_null']:+d} "
            f"| {row['p_holm']:.6f} |"
        )
    lines += [
        "",
        "所有模型使用同一期开奖、相同的过去信息，不允许剔除未命中样本。32组不同的固定种子随机负对照也已计算。",
        "公式原始权重来自已知历史，不代表被校准的中奖概率。",
        "历史后验选择带来的统计偏差无法仅靠Holm修正消除，未来必须先预注册后开奖验证。",
        "",
        "| 彩种 | 实验数据截止 | 历史源SHA256 | FULL_WEIGHTED研究候选（并非最新正式预测） |",
        "|---|---|---|---|",
    ]
    for game, d in report["games"].items():
        pred = d["hypothetical_next_candidate"]
        lines.append(
            f"| {game.upper()} | {d['source']['asof_issue']} "
            f"| `{d['source']['sha256']}` | {pred['candidate']} |"
        )
    lines += [
        "",
        "**P0未完成**：独立官方数据核验、真实销售截止时间、可信时间戳、正式开奖前封存和未来实际评分。",
        "每期的8个预测、原始 NULL、票号评分与模型SHA256都在 report.json；报告使用 create-only 文件写入。",
        "",
    ]
    return "\n".join(lines)


def write_once(report, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, sort_keys=True, ensure_ascii=False,
                      indent=2, allow_nan=False) + "\n").encode("utf-8")
    with (folder / "report.json").open("xb") as f:
        f.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with (folder / "report.sha256").open("x", encoding="ascii") as f:
        f.write(sha + "  report.json\n")
    with (folder / "summary.md").open("x", encoding="utf-8") as f:
        f.write(render_summary(report))
    return sha


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--periods", type=int, default=40)
    p.add_argument("--out", type=Path, default=Path("reverse-bank-output"))
    args = p.parse_args(argv)
    validate_dependencies(Path(os.environ["FORMULA_CHECKOUT"]),
                          os.environ["FORMULA_EXPECTED_SHA"])
    report = build_report(periods=args.periods)
    sha = write_once(report, args.out)
    print(json.dumps({
        "status": "RETROSPECTIVE_RESEARCH_ONLY",
        "report_sha256": sha,
        "games": {k: v["evaluated"] for k, v in report["games"].items()},
        "comparisons": len(report["paired_comparisons"]),
        "formal_A": 0, "edge": "NO_EDGE",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
