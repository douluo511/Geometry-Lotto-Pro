"""Full retrospective walk-forward audit of the 14 executable mother model arms.

Outputs *exploratory* comparisons, never a production champion or true
prospective evidence. Temporal splits are fixed by the Oct 24 historical
research bundle: SSQ train 1175 / validation 392 / test 392, DLT train 1690 /
validation 564 / test 564 (after 120 warmup observations).
Scores: registered D2 first-two-hit, whole ticket, and precisely defined
"kill tail-3" failure if any excluded number actually wins.

The mother has another two physical model slots; both ABSTAIN in this study.
The Windows native features were deliberately retired and are not executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import gzip
import json
import math
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46.d2_challenger_lab import ablation_rank, pick_recency_pair
from research.supercompute import engine as legacy
from research.mother_v1.registry import (
    ALL_MODELS, REGISTERED_V47, EXPLORATORY_V47, LEGACY_SUPERCOMPUTE, PHYSICAL,
)
from research.mother_v1 import historical_example

WINDOWS = {"SSQ": 392, "DLT": 564}
PINNED_CANON = "3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c"
PINNED = (Path(__file__).resolve().parents[1] / "harness_v46" / "evidence"
          / "recency_ablation_20261024" / "observations.json.gz")
EXPLORATORY_TO_ARM = {
    "hot30": "HOT30",
    "hot120": "HOT120",
    "pair_margin": "P-MARGIN",
    "pair_residual": "P-RESIDUAL",
}
LEGACY_TO_ARM = {
    "supercompute_hot60": "HOT60",
    "supercompute_ewma30": "EWMA30",
    "supercompute_random_null": "RANDOM_NULL",
}
ACTIVE = tuple(x for x in ALL_MODELS if x not in PHYSICAL)
assert len(ACTIVE) == 14 and len(PHYSICAL) == 2


class ComparisonBlocked(ValueError):
    pass


def canonical_sha(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def load_pinned():
    raw = PINNED.read_bytes()
    bundle = json.loads(gzip.decompress(raw))
    if set(bundle) != {"SSQ", "DLT"} or core.digest(bundle) != PINNED_CANON:
        raise ComparisonBlocked("PINNED_HISTORY_HASH_OR_SCHEMA_MISMATCH")
    for game, n in WINDOWS.items():
        if len(bundle[game]) != (120 + (1175 if game == "SSQ" else 1690) + 2*n):
            raise ComparisonBlocked("SPLIT_LENGTH_CHANGED")
        seen = set()
        for row in bundle[game]:
            if set(row) != {"issue", "draw_date", "front", "back"}:
                raise ComparisonBlocked("ROW_SCHEMA_INVALID")
            if row["issue"] in seen:
                raise ComparisonBlocked("DUPLICATE_ISSUE")
            seen.add(row["issue"])
            r = core.RULES[game]
            core._balls(row["front"], r["pool"], r["front"])
            core._balls(row["back"], r["back_pool"], r["back"])
    return bundle, sha256(raw).hexdigest()


def pair_rank(game, rows, name, issue):
    state = {"lottery": game, "target_issue": issue, "draws": rows}
    if name in REGISTERED_V47:
        return core._model_ranking(state, name)
    if name in EXPLORATORY_V47:
        if name == "recency_pair_h45_120":
            pair = pick_recency_pair(rows, game)
            hot60 = core._model_ranking(state, "hot60")
            return pair + [x for x in hot60 if x not in pair]
        return ablation_rank(rows, game, EXPLORATORY_TO_ARM[name], target_issue=issue)
    raise ComparisonBlocked("UNKNOWN_RANK_MODEL")


def one_ticket(game, rows, name, issue):
    r = core.RULES[game]
    if name in LEGACY_SUPERCOMPUTE:
        rawname = LEGACY_TO_ARM[name]
        old = legacy.ticket(rows, game.lower(), rawname, seed=2026)
        # MUST match the mother adapter: legacy D2 uses the first two of
        # its *sorted ticket.front*, not a retroactively revised ordering.
        front, back = old["front"], old["back"]
        if rawname == "RANDOM_NULL":
            kill3 = None  # zero independently registered ranking; do not invent it
        else:
            ordered = legacy.rank(rows, "front", r["pool"], rawname)
            kill3 = sorted(ordered[-3:])
        d2 = front[:2]
    else:
        ordered = pair_rank(game, rows, name, issue)
        front = sorted(ordered[:r["front"]])
        back_perm = core._stable_permutation(
            list(range(1, r["back_pool"]+1)), core.NULL_SEED,
            game, issue, name, "back")
        back = sorted(back_perm[:r["back"]])
        d2, kill3 = ordered[:2], sorted(ordered[-3:])
    core._balls(front, r["pool"], r["front"])
    core._balls(back, r["back_pool"], r["back"])
    if len(d2) != 2 or len(set(d2)) != 2:
        raise ComparisonBlocked("D2_NOT_PAIR")
    if kill3 is not None:
        if len(kill3) != 3 or set(kill3).intersection(front):
            raise ComparisonBlocked("KILL3_OVERLAPS_FORECAST_FRONT")
    return {"front": front, "back": back, "d2": d2, "kill3": kill3}


def _tail(k, n, p):
    """Exact binomial upper tail; nominal iid null approximation only."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(math.exp(math.lgamma(n+1) - math.lgamma(j+1)
                                - math.lgamma(n-j+1) + j*math.log(p)
                                + (n-j)*math.log1p(-p))
                        for j in range(k, n+1)))


def _paired_p(wins, losses):
    """One-sided exact McNemar/sign test on discordant SAME-draw predictions."""
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, sum(math.exp(math.lgamma(n+1) -
                                math.lgamma(j+1) - math.lgamma(n-j+1) -
                                n*math.log(2))
                        for j in range(wins, n+1)))


def _wilson(k, n):
    z = 1.959963984540054
    p = k/n
    den = 1 + z*z/n
    mid = (p + z*z/(2*n))/den
    err = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [max(0.0, mid-err), min(1.0, mid+err)]


def _score_period(draws, game, first, last, *, details):
    rows = draws
    models = {name: {"d1": 0, "d2": 0, "full": 0, "front_matches_sum": 0,
                     "back_matches_sum": 0, "kill3_safe": 0,
                     "kill3_risk": 0, "kill3_unavailable": 0,
                     "half_d2": [0, 0]} for name in ACTIVE}
    events = []
    n = last-first
    if n <= 0:
        raise ComparisonBlocked("EMPTY_PERIOD")
    null_d2 = {}
    # One target at a time: no row at index >= target is supplied to any
    # model, including its NULL seed or legacy draw-history interface.
    for idx in range(first, last):
        actual = rows[idx]
        history = rows[:idx]
        front, back = set(actual["front"]), set(actual["back"])
        round_d2 = {}
        for name in ACTIVE:
            ticket = one_ticket(game, history, name, actual["issue"])
            r = models[name]
            successes = int(set(ticket["d2"]).issubset(front))
            r["d2"] += successes
            r["d1"] += int(ticket["d2"][0] in front)
            r["half_d2"][0 if idx-first < n//2 else 1] += successes
            r["front_matches_sum"] += len(front.intersection(ticket["front"]))
            r["back_matches_sum"] += len(back.intersection(ticket["back"]))
            r["full"] += int(ticket["front"] == actual["front"] and
                             ticket["back"] == actual["back"])
            if ticket["kill3"] is None:
                r["kill3_unavailable"] += 1
            else:
                safe = int(front.isdisjoint(ticket["kill3"]))
                r["kill3_safe"] += safe
                r["kill3_risk"] += 1-safe
            round_d2[name] = successes
        null_d2[actual["issue"]] = round_d2["random_null"]
        if details:
            events.append({"issue": actual["issue"], "index": idx,
                           "target_history_last_issue": history[-1]["issue"],
                           "d2_hit": round_d2})
    for name, r in models.items():
        r["n"] = n
        r["d2_rate"] = r["d2"]/n
        r["d2_wilson95"] = _wilson(r["d2"], n)
        r["kill3_safe_rate"] = None if r["kill3_unavailable"] else r["kill3_safe"]/n
        if r["kill3_unavailable"] not in (0, n):
            raise ComparisonBlocked("INCONSISTENT_KILL3_COVERAGE")
    return {"n": n, "first_issue": rows[first]["issue"],
            "last_issue": rows[last-1]["issue"], "model_scores": models,
            "events": events}


def _holms(values: dict[str, float]) -> dict[str, float]:
    order = sorted(values, key=lambda key: (values[key], key))
    adj, running = {}, 0.
    m = len(order)
    for i, name in enumerate(order):
        running = max(running, min(1., (m-i)*values[name]))
        adj[name] = running
    return adj


def analyze():
    bundle, raw_sha = load_pinned()
    result = {"schema": "SSQDLT_MOTHER_V1_ALL_ARM_RETROSPECTIVE_V1",
              "history_canonical_sha256": PINNED_CANON,
              "history_gzip_sha256": raw_sha,
              "model_names": list(ACTIVE),
              "physical_models": [{"name": x, "status": "ABSTAIN_NO_PRE_DRAW_VERIFIED_PHYSICAL_HISTORY"}
                                  for x in PHYSICAL],
              "date_and_publication_policy": "DRAW_DATE_ONLY_NO_AUTHENTICATED_PUBLICATION_TIMESTAMPS",
              "research_type": "RETROSPECTIVE_POSTHOC_NOT_PROSPECTIVE",
              "model_renaming_or_selection_on_test": "EXPLORATORY_REPORT_ONLY",
              "formal_A": 0, "decision": "NO_EDGE", "games": {}}
    family_p = {}
    for game in ("SSQ","DLT"):
        rows = bundle[game]
        test_n = WINDOWS[game]
        val_first = len(rows)-2*test_n
        test_first = len(rows)-test_n
        validation = _score_period(rows, game, val_first, test_first, details=False)
        test = _score_period(rows, game, test_first, len(rows), details=True)
        if validation["n"] != test_n or test["n"] != test_n:
            raise ComparisonBlocked("SPLIT_LENGTH_INVALID")
        # Chosen on validation only (still exploratory because archive was
        # already examined by earlier researchers).
        selectable = tuple(x for x in ACTIVE if x not in
                           ("random_null", "supercompute_random_null"))
        best_val = sorted(selectable, key=lambda m:
                          (-validation["model_scores"][m]["d2"], ACTIVE.index(m)))[0]
        best_test_posthoc = sorted(selectable, key=lambda m:
                          (-test["model_scores"][m]["d2"], ACTIVE.index(m)))[0]
        selected_legacy = best_val.startswith("supercompute_")
        fair = core.RULES[game]["d2"]
        pool = core.RULES[game]["pool"]
        draw_size = core.RULES[game]["front"]
        p_kill3_safe = math.comb(pool-draw_size,3)/math.comb(pool,3)
        null_scores = {ev["issue"]:ev["d2_hit"]["random_null"] for ev in test["events"]}
        tests = {}
        for name in selectable:
            hits=test["model_scores"][name]["d2"]
            wins=sum(ev["d2_hit"][name] == 1 and null_scores[ev["issue"]] == 0
                     for ev in test["events"])
            losses=sum(ev["d2_hit"][name] == 0 and null_scores[ev["issue"]] == 1
                       for ev in test["events"])
            pfair=_tail(hits,test_n,fair)
            ppaired=_paired_p(wins,losses)
            joint=max(pfair,ppaired)
            tests[name]={"p_fair_nominal":pfair, "p_paired_null_nominal":ppaired,
                         "paired_wins":wins, "paired_losses":losses,
                         "p_joint_nominal":joint}
            family_p[game+":"+name]=joint
        result["games"][game] = {
            "history_n":len(rows),
            "validation":validation,
            "test":test,
            "fair_d2_rate":fair,
            "fair_kill3_safe_rate":p_kill3_safe,
            "fair_exact_ticket_probability":1/(math.comb(pool,draw_size)*
                                               math.comb(core.RULES[game]["back_pool"],
                                                         core.RULES[game]["back"])),
            "selected_model_by_validation_d2_exploratory":best_val,
            "best_test_d2_model_posthoc_not_prospective":best_test_posthoc,
            "source_count_selectable":len(selectable),
            "significance":tests,
            "legacy_D2_warning": ("legacy supercompute D2 = two smallest front numbers "
                                  "by legacy mother adapter; not first-two-ranked")
        }
    adjusted = _holms(family_p)
    for game in ("SSQ","DLT"):
        for name, entry in result["games"][game]["significance"].items():
            entry["p_holm_across_24_tests"] = adjusted[game+":"+name]
    # We report a ranking but never promote because the validation and test
    # windows existed and were examined previously; no prospective A accepted.
    result["number_of_joint_hypotheses"] = len(family_p)
    result["any_adjusted_below_005"] = any(p < .05 for p in adjusted.values())
    result["statistical_caveat"] = (
        "Nominal binomial and paired sign tests are exploratory, may not "
        "calibrate dependence across rolling draws; Holm does not cure "
        "posthoc search or biased outcomes publication.")
    result["source_identity"] = {
        "core_version":core.VERSION,"null_seed":core.NULL_SEED,
        "legacy_seed":2026,"physical": "ABSTAIN"}
    return result


def _future_report(outcome):
    data = historical_example.build()
    future = {"schema":"SSQDLT_RESEARCH_CANDIDATE_D2_KILL3_NOT_VERIFIED_PREDRAW",
              "data_input_class": "MANUALLY_TRANSCRIBED_RECENT_DRAW_ROWS",
              "frozen_predictions_are_not_proven":True,
              "decision":"NO_EDGE","formal_A":0,
              "games":{}}
    for game in ("SSQ","DLT"):
        context = data[game]
        history = context["history"]
        name = outcome["games"][game]["selected_model_by_validation_d2_exploratory"]
        ticket = one_ticket(game,history,name,context["target_issue"])
        future["games"][game]={
            "target_issue":context["target_issue"],
            "expected_draw_date":context["target_draw_date"],
            "history_last_issue":history[-1]["issue"],
            "validation_selected_model_exploratory":name,
            "front":ticket["front"],"back":ticket["back"],
            "d2_candidates_unproven":ticket["d2"],
            "kill3_unproven":ticket["kill3"],
            "kill_is_never_guaranteed":True,
            "kill3_random_expected_error_rate":
                1-outcome["games"][game]["fair_kill3_safe_rate"],
            "physical_status":"ABSTAIN_NO_VERIFIED_PREDRAW_FEATURES",
        }
    return future


def _markdown(report, future):
    lines=["# SSQ＋DLT 新母体：14条可运行模型历史滚动比较",
           "",
           "**研究性质：事后探索，formal_A=0，NO_EDGE。**"
           "最高历史率≠可复制的未来优势。物理2条均ABSTAIN。"
           "窗口事前并未获得外部可信时间封存。",
           "",
           "每期使用此前全部已开奖记录；暖机120期。按固定历史档案后两段各392期/564期划分验证与测试；"
           "模型历史数据虽在代码中隔离，研究者已能查看历史测试结果，因此不是可信前瞻实验。",
           ""]
    for game in ("SSQ","DLT"):
        r=report["games"][game]
        val,test=r["validation"],r["test"]
        lines += [f"## {game}｜验证{val['n']}期，测试{test['n']}期",
                  f"数据期号：验证 {val['first_issue']}–{val['last_issue']}；"
                  f"测试 {test['first_issue']}–{test['last_issue']}。",
                  f"理论随机 D2 双中 {r['fair_d2_rate']:.4%}，"
                  f"随机杀号3码误杀概率 {1-r['fair_kill3_safe_rate']:.4%}。",
                  "",
                  "| 模型 | 验证D2 | 测试D2 | 测试95% Wilson CI | 杀3码无误杀 | 完整票中奖 | Holm p（联合比较） |",
                  "|---|---:|---:|---|---:|---:|---:|"]
        order=sorted(ACTIVE,key=lambda a:(-test["model_scores"][a]["d2"],ACTIVE.index(a)))
        for m in order:
            v=val["model_scores"][m]
            x=test["model_scores"][m]
            s=r["significance"].get(m,{}).get("p_holm_across_24_tests")
            kill="不可计算" if x["kill3_safe_rate"] is None else f"{x['kill3_safe']}/{x['n']}"
            ci=x["d2_wilson95"]
            lines.append(f"| {m} | {v['d2']}/{v['n']} | {x['d2']}/{x['n']} | "
                         f"{ci[0]:.2%}–{ci[1]:.2%} | {kill} | "
                         f"{x['full']}/{x['n']} | {'对照' if s is None else f'{s:.4g}'} |")
        f=future["games"][game]
        lines += ["",
                  f"测试区最高历史D2（事后）: **{r['best_test_d2_model_posthoc_not_prospective']}**；"
                  f"按验证区选型: **{r['selected_model_by_validation_d2_exploratory']}**。",
                  f"下一期 {f['target_issue']} 研究号码：前区/红球 {f['front']}；"
                  f"后区/蓝球 {f['back']}；"
                  f"候选胆码D2（无确认优势）{f['d2_candidates_unproven']}；"
                  f"候选杀号3码（随时可能误杀）{f['kill3_unproven']}。",
                  ""]
    lines += ["## 结论与边界",
              "",
              f"已对 {report['number_of_joint_hypotheses']} 个非随机候选×彩种比较"
              "做一侧联合p与Holm校正。校正显著结果是 "
              + ("有（仅属于未经预注册的探索性证据）" if report["any_adjusted_below_005"] else "无") + "。",
              "完整票极难命中；单期中大奖0次不能证明模型没有优势，也不能证明有优势。",
              "杀码是低排位号码的研究性排除，**任何号码都不是绝对不会开**；"
              "评估采用固定3个排除号码且只要一个真实开出即视为误杀。",
              "固定 Random NULL 仍作为原始对照，不得因其测试区表现低而替换种子。",
              "物理模型缺乏经证实且可在停售前获得的输入，统一标记ABSTAIN。",
              "无可信前瞻登记、独立来源及发布时间，不晋级，不自动投注。",
              ""]
    return "\n".join(lines)


def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--out",required=True,type=Path)
    opt=a.parse_args(argv)
    if opt.out.exists():
        raise ComparisonBlocked("CREATE_ONLY_OUTPUT_DIRECTORY_EXISTS")
    report=analyze()
    future=_future_report(report)
    markdown=_markdown(report,future)
    opt.out.mkdir(parents=True,exist_ok=False)
    for name,payload in (("comparisons.json",report),("candidate_dan_kill.json",future)):
        with (opt.out/name).open("x",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,sort_keys=True,indent=2)
            f.write("\n")
    with (opt.out/"model_comparison.md").open("x",encoding="utf-8") as f:
        f.write(markdown)
    digest={p.name:sha256(p.read_bytes()).hexdigest() for p in sorted(opt.out.iterdir())}
    with (opt.out/"SHA256.json").open("x",encoding="utf-8") as f:
        json.dump({"sha256":digest,
                   "git_sha":__import__("os").environ.get("GITHUB_SHA","LOCAL_UNTRUSTED"),
                   "formal_A":0,"decision":"NO_EDGE"},f,indent=2,sort_keys=True)
        f.write("\n")
    print(json.dumps({"status":"PASS_COMPUTED_SHADOW","files":digest,
                      "summary":{
                          game:{"test_best":report["games"][game]["best_test_d2_model_posthoc_not_prospective"],
                                "selected_on_validation":report["games"][game]["selected_model_by_validation_d2_exploratory"],
                                "target":future["games"][game]["target_issue"],
                                "candidate":future["games"][game]["front"],
                                "D2":future["games"][game]["d2_candidates_unproven"],
                                "kill3":future["games"][game]["kill3_unproven"],
                                "test_n":report["games"][game]["test"]["n"],
                                "top3_test_scores":sorted(
                                    ((k,v["d2"]) for k,v in
                                     report["games"][game]["test"]["model_scores"].items()),
                                    key=lambda a:-a[1])[:3]}
                          for game in ("SSQ","DLT")},
                      "holm_significance_pass":report["any_adjusted_below_005"],
                      "edge":"NO_EDGE"},ensure_ascii=False,sort_keys=True))


if __name__ == "__main__":
    main()
