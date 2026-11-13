"""Strict additive analysis of the immutable PR 492 cache; no predictive-edge promotion."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import zipfile
import numpy as np
import scipy
from scipy.stats import binomtest
from research.mother_v1 import rolling_audit as old
from research.mother_v1 import historical_example

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ZIP_SHA = "a64f09f2b6d253e385a1b254492ea27194ff950f53c43da4c639901b564894e4"
BASE_SHA = "206a4f997a84c53df201180f50809f51fc902d34"
NULLS = {"random_null", "supercompute_random_null"}
SEED = 20261113

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def interval(k, n):
    if not isinstance(k, (int, np.integer)) or not isinstance(n, (int, np.integer)) or not 0 <= k <= n:
        raise ValueError("INVALID_COUNT")
    if not n:
        return {"k":0,"n":0,"rate":None,"wilson95":None,"exact95":None}
    result = binomtest(int(k), int(n))
    return {"k":int(k),"n":int(n),"rate":float(k/n),
            "wilson95":list(result.proportion_ci(.95, method="wilson")),
            "exact95":list(result.proportion_ci(.95, method="exact"))}

def theory(game):
    r = old.core.RULES[game]
    n,k,m,l = r["pool"],r["front"],r["back_pool"],r["back"]
    return {"d2":math.comb(k,2)/math.comb(n,2),
            "ticket":1/(math.comb(n,k)*math.comb(m,l)),
            "kill3_error":1-math.comb(n-k,3)/math.comb(n,3)}

def holm(values):
    if any(not math.isfinite(x) or not 0 <= x <= 1 for x in values.values()):
        raise ValueError("INVALID_P")
    result, running = {},0.
    for i,(name,p) in enumerate(sorted(values.items(),key=lambda x:(x[1],x[0]))):
        running = max(running,min(1.,(len(values)-i)*p))
        result[name] = running
    return result

def paired(left,right):
    left,right = np.asarray(left),np.asarray(right)
    if left.shape != right.shape or not np.isin(left,[0,1]).all() or not np.isin(right,[0,1]).all():
        raise ValueError("UNALIGNED_BINARY_OUTCOMES")
    wins = int(np.sum((left==1)&(right==0)))
    losses = int(np.sum((left==0)&(right==1)))
    return {"wins":wins,"losses":losses,
            "p":float(binomtest(wins,wins+losses,.5,alternative="greater").pvalue) if wins+losses else 1.,
            "difference":float(np.mean(left-right))}

def select_model(counts,names):
    valid = [i for i,name in enumerate(names) if name not in NULLS]
    return names[max(valid,key=lambda i:(counts[i],-i))]

def bootstrap_means(x,reps,block,seed):
    x=np.asarray(x,dtype=float)
    if x.ndim!=2 or not len(x) or reps<1 or not 1<=block<=len(x):
        raise ValueError("INVALID_BOOTSTRAP_SHAPE")
    rng=np.random.default_rng(seed)
    n=len(x); chunks=math.ceil(n/block)
    result=np.empty((reps,x.shape[1]))
    for start in range(0,reps,128):
        b=min(128,reps-start)
        starts=rng.integers(0,n,size=(b,chunks))
        idx=((starts[:,:,None]+np.arange(block))%n).reshape(b,-1)[:,:n]
        result[start:start+b]=x[idx].mean(axis=1)
    return result

def correlations(x,names):
    x=np.asarray(x,dtype=float)
    centered=x-x.mean(axis=0)
    norms=np.sqrt((centered*centered).sum(axis=0))
    phi=[]; matrix=np.zeros((len(names),len(names)))
    for i in range(len(names)):
        row=[]
        for j in range(len(names)):
            v=float(np.clip(centered[:,i]@centered[:,j]/(norms[i]*norms[j]),-1,1)) if norms[i]*norms[j] else None
            row.append(v); matrix[i,j]=v if v is not None else 0
        phi.append(row)
    eig=np.linalg.eigvalsh(matrix)
    rank=float(eig.sum()**2/(eig@eig)) if eig@eig else 0.
    duplicates=[[names[i],names[j]] for i in range(len(names)) for j in range(i+1,len(names))
                if np.array_equal(x[:,i],x[:,j])]
    return {"model_order":list(names),"phi":phi,"identical_hit_streams":duplicates,
            "spectral_effective_rank_descriptive_only":rank,
            "warning":"Outcome correlation is not forecast-set correlation; do not reduce Holm family size."}

def load_prior_bytes(raw):
    if digest(raw)!=ZIP_SHA:
        raise ValueError("PRIOR_ZIP_HASH_MISMATCH")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        receipt=json.loads(z.read("SHA256.json"))
        if receipt["git_sha"]!=BASE_SHA: raise ValueError("PRIOR_SOURCE_MISMATCH")
        for name,expected in receipt["sha256"].items():
            if digest(z.read(name))!=expected: raise ValueError("PRIOR_MEMBER_HASH_MISMATCH")
        return json.loads(z.read("comparisons.json")),json.loads(z.read("candidate_dan_kill.json")),receipt

def load_prior():
    prior,future,receipt = load_prior_bytes((HERE/"evidence/prior-rolling-14-arm.zip").read_bytes())
    raw=(HERE/"evidence/validation_events.json.gz").read_bytes()
    if digest(raw)!="0253a06b8b55bc7516bb157bb734f959793ca27dac2c4daf7a33ea65cfc885be":
        raise ValueError("VALIDATION_EVENTS_HASH_MISMATCH")
    supplement=json.loads(gzip.decompress(raw))
    for game in ("SSQ","DLT"):
        if prior["games"][game]["validation"]["events"]:
            raise ValueError("PRIOR_VALIDATION_ALREADY_HAS_EVENTS")
        prior["games"][game]["validation"]["events"]=supplement[game]
    return prior,future,receipt

def load_history():
    return old.load_pinned()[0]

def validate_prior(prior,history):
    if prior["model_names"]!=list(old.ACTIVE) or prior["history_canonical_sha256"]!=old.PINNED_CANON:
        raise ValueError("REGISTRY_OR_HISTORY_CHANGED")
    for game in ("SSQ","DLT"):
        rows=history[game]; n=old.WINDOWS[game]
        if any(a["draw_date"]>=b["draw_date"] or int(a["issue"])>=int(b["issue"])
               for a,b in zip(rows,rows[1:])):
            raise ValueError("HISTORY_PREFIX_CHRONOLOGY")
        for stage,start in (("validation",len(rows)-2*n),("test",len(rows)-n)):
            p=prior["games"][game][stage]; events=p["events"]
            if p["n"]!=n or len(events)!=n: raise ValueError("EVENT_COUNT")
            if p["first_issue"]!=rows[start]["issue"] or p["last_issue"]!=rows[start+n-1]["issue"]:
                raise ValueError("PERIOD_BOUNDARY")
            for j,event in enumerate(events):
                idx=start+j
                if (event["index"]!=idx or event["issue"]!=rows[idx]["issue"] or
                    event["target_history_last_issue"]!=rows[idx-1]["issue"] or
                    rows[idx-1]["draw_date"]>=rows[idx]["draw_date"]):
                    raise ValueError("EVENT_CHRONOLOGY")
                if set(event["d2_hit"])!=set(old.ACTIVE) or any(v not in (0,1) for v in event["d2_hit"].values()):
                    raise ValueError("EVENT_MODEL_OR_OUTCOME")
            for model,score in p["model_scores"].items():
                if score["n"]!=n or sum(e["d2_hit"][model] for e in events)!=score["d2"]:
                    raise ValueError("SCORE_COUNT_MISMATCH")
                if score["kill3_safe"]+score["kill3_risk"]+score["kill3_unavailable"]!=n:
                    raise ValueError("KILL_COVERAGE_MISMATCH")
    return True

def clean_holdout():
    return {"n":0,"winner":None,"status":"BLOCKED",
            "reason":"Historical validation/test and nine later rows were already exposed; no untouched test is evidenced."}

def check_target(context,official):
    rows=context["history"]; last=rows[-1]
    observed=datetime.fromisoformat(official["retrieved_utc"].replace("Z","+00:00"))
    if observed.tzinfo is None: raise ValueError("NAIVE_OBSERVATION_TIME")
    # Conservative bound: no release on or after China's target draw date.
    china_day=observed.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    target_day=context["target_draw_date"]
    if (last["issue"]!=official["latest_issue"] or last["front"]!=official["front"]
        or last["back"]!=official["back"] or int(context["target_issue"])!=int(last["issue"])+1
        or target_day<=china_day or last["draw_date"]>=target_day
        or any(int(r["issue"])>=int(context["target_issue"]) or r["draw_date"]>=target_day for r in rows)):
        raise ValueError("TARGET_ALREADY_DRAWN_OR_UNVERIFIED_TAIL")
    return True

def temporal_label(target_day,executed_utc):
    stamp=datetime.fromisoformat(executed_utc.replace("Z","+00:00"))
    if stamp.tzinfo is None: raise ValueError("NAIVE_EXECUTION_TIME")
    china_day=stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    return ("HISTORICAL_REPLAY_NOT_CURRENT" if china_day>=target_day else
            "UNOPENED_AT_EXECUTION_DATE_RECHECK_OFFICIAL_SOURCE")

def load_historical_search(raw=None):
    if raw is None:
        raw=(ROOT/"research/harness_v46/evidence/recency_ablation_20261024/statistics_summary.json.gz").read_bytes()
    if digest(raw)!="8a1ecf9b34652178ca72f715b526cd8f83756a53ac590fb2def2b34b428c4c18":
        raise ValueError("HISTORICAL_SEARCH_HASH_MISMATCH")
    return json.loads(gzip.decompress(raw))

def verify_official_snapshot(game,official,snapshot):
    allowed={"SSQ":"https://www.swlc.net.cn/","DLT":"https://www.shsportslottery.com/dlt/kjgg.html"}
    meta=snapshot["metadata"]; text=snapshot["markdown"]
    if meta["sourceURL"]!=allowed[game] or official["url"]!=allowed[game] or meta["statusCode"]!=200:
        raise ValueError("OFFICIAL_SOURCE_MISMATCH")
    if game=="SSQ":
        match=re.search(r"## 双色球\s+第(\d+)期.*?\n(\d{14})\n",text,re.S)
        if not match: raise ValueError("SSQ_LATEST_NOT_PARSED")
        issue=match[1]; values=[int(match[2][i:i+2]) for i in range(0,14,2)]
        front,back=values[:6],values[6:]
    else:
        match=re.search(r"第(\d+)期开奖公告",text)
        balls=re.search(r"本期开奖号码：\s*\|\s*([\d ]+)\|\s*([\d ]+)\|",text)
        if not match or not balls: raise ValueError("DLT_LATEST_NOT_PARSED")
        issue=match[1]; front=list(map(int,balls[1].split())); back=list(map(int,balls[2].split()))
    if (issue,front,back)!=(official["latest_issue"],official["front"],official["back"]):
        raise ValueError("OFFICIAL_PARSED_NUMBERS_MISMATCH")
    return True

def matrix(period):
    return np.array([[e["d2_hit"][name] for name in old.ACTIVE] for e in period["events"]],dtype=int)

def replay_sample(prior,history):
    checked=0; sample=[]
    for game in ("SSQ","DLT"):
        for stage in ("validation","test"):
            events=prior["games"][game][stage]["events"]; n=len(events)
            for offset in sorted({0,n//4,n//2,3*n//4,n-1}):
                event=events[offset]; idx=event["index"]; actual=history[game][idx]
                for model in old.ACTIVE:
                    ticket=old.one_ticket(game,history[game][:idx],model,actual["issue"])
                    if int(set(ticket["d2"])<=set(actual["front"]))!=event["d2_hit"][model]:
                        raise ValueError("SAMPLED_REPLAY_MISMATCH")
                    checked+=1
                sample.append({"game":game,"period":stage,"issue":actual["issue"],"models":14})
    return {"status":"PASS","checked_model_draw_pairs":checked,"draws":sample,
            "scope":"Sampled cache D2 parity only, not a second full historical computation."}

def blocks(x,events):
    result=[]
    for idx in np.array_split(np.arange(len(x)),4):
        counts=x[idx].sum(axis=0)
        result.append({"first_issue":events[int(idx[0])]["issue"],"last_issue":events[int(idx[-1])]["issue"],
                       "n":len(idx),"hits":dict(zip(old.ACTIVE,map(int,counts))),
                       "winner_posthoc":select_model(counts,old.ACTIVE)})
    return result

def historical_adaptive(val,test):
    # At draw t only validation and previously scored test draws select the model.
    scores=val.sum(axis=0).copy(); choices=[]; hits=[]
    for row in test:
        name=select_model(scores,old.ACTIVE); i=old.ACTIVE.index(name)
        choices.append(name); hits.append(int(row[i])); scores+=row
    return {"status":"EXPLORATORY_POLICY_NOT_NEW_HOLDOUT","d2":interval(sum(hits),len(hits)),
            "per_draw_choices":choices,
            "choices":{name:choices.count(name) for name in old.ACTIVE if name in choices},
            "switches":sum(a!=b for a,b in zip(choices,choices[1:]))}

def compute(prior,reps):
    result={"schema":"STRICT_ADDITIVE_AUDIT_V1","decision":"NO_EDGE","formal_A":0,
            "genuine_untouched_test":clean_holdout(),"games":{},
            "interval_scope":"95% marginal descriptive; not simultaneous or selection-adjusted",
            "bootstrap_repetitions":reps,"seed":SEED}
    family={}; original24={}
    for game in ("SSQ","DLT"):
        source=prior["games"][game]; fair=theory(game)
        val,test=matrix(source["validation"]),matrix(source["test"])
        chosen=select_model(val.sum(axis=0),old.ACTIVE)
        if chosen!=source["selected_model_by_validation_d2_exploratory"]:
            raise ValueError("VALIDATION_SELECTION_CHANGED")
        g={"fair":fair,"selected_from_validation":chosen,"selection_status":"HISTORICAL_RULE_NOT_TRUSTED_PREREGISTRATION",
           "old_test_posthoc_winner":select_model(test.sum(axis=0),old.ACTIVE),
           "validation":{},"test":{}}
        for stage,x in (("validation",val),("test",test)):
            p=source[stage]; metrics={}
            for i,model in enumerate(old.ACTIVE):
                s=p["model_scores"][model]; n=p["n"]
                d2=interval(s["d2"],n); ticket=interval(s["full"],n)
                kill=interval(s["kill3_risk"],n-s["kill3_unavailable"])
                pair=paired(x[:,i],x[:,old.ACTIVE.index("random_null")])
                pf=float(binomtest(s["d2"],n,fair["d2"],alternative="greater").pvalue)
                joint=max(pf,pair["p"])
                metrics[model]={"d2":d2,"full_ticket":ticket,"kill3_error":kill,
                    "p_d2_fair":pf,"paired_fixed_null":pair,"p_d2_joint":joint,
                    "kill3_minus_fixed_null":None if kill["rate"] is None else kill["rate"]-p["model_scores"]["random_null"]["kill3_risk"]/n,
                    "paired_kill3_test":"UNVERIFIED_NO_CACHED_PER_DRAW_KILL_EVENTS"}
                if model not in NULLS:
                    prefix=f"{game}:{stage}:{model}:"
                    family[prefix+"d2"]=joint
                    family[prefix+"ticket"]=float(binomtest(s["full"],n,fair["ticket"],alternative="greater").pvalue)
                    family[prefix+"kill3"]=float(binomtest(s["kill3_risk"],n,fair["kill3_error"],alternative="less").pvalue)
                    if stage=="test":
                        original24[f"{game}:{model}"]=joint
                        if not math.isclose(joint,source["significance"][model]["p_joint_nominal"],abs_tol=1e-10):
                            raise ValueError("PRIOR_P_NOT_REPRODUCED")
            eligible=[name for name in old.ACTIVE if name not in NULLS]
            ranked=sorted(eligible,key=lambda name:(-metrics[name]["d2"]["k"],old.ACTIVE.index(name)))
            top=metrics[ranked[0]]["d2"]["k"]
            g[stage]={"n":p["n"],"first_issue":p["first_issue"],"last_issue":p["last_issue"],
                      "ranking_nonrandom":ranked,"top_ties":[m for m in ranked if metrics[m]["d2"]["k"]==top],
                      "metrics":metrics,"quarters":blocks(x,p["events"]),
                      "correlation":correlations(x,old.ACTIVE)}
        g["validation_to_test_rate_change"]={m:g["test"]["metrics"][m]["d2"]["rate"]-g["validation"]["metrics"][m]["d2"]["rate"] for m in old.ACTIVE}
        g["historical_adaptive"]=historical_adaptive(val,test)
        bootstrap={}
        selectable=[i for i,m in enumerate(old.ACTIVE) if m not in NULLS]
        ni=old.ACTIVE.index("random_null"); si=old.ACTIVE.index(chosen)
        for length in (5,20,60):
            vm=bootstrap_means(val,reps,length,SEED+length)
            tm=bootstrap_means(test,reps,length,SEED+length+1000)
            choices=np.asarray(selectable)[np.argmax(vm[:,selectable],axis=1)]
            selected_test=tm[np.arange(reps),choices]
            oracle=tm[:,selectable].max(axis=1)
            bootstrap[str(length)]={"selected_minus_null95":np.quantile(tm[:,si]-tm[:,ni],[.025,.975]).tolist(),
                "selected_d2_rate95":np.quantile(tm[:,si],[.025,.975]).tolist(),
                "reselected_validation_frequency":{old.ACTIVE[i]:float(np.mean(choices==i)) for i in selectable},
                "posthoc_max_minus_validation_choice_mean":float(np.mean(oracle-selected_test)),
                "posthoc_max_minus_validation_choice95":np.quantile(oracle-selected_test,[.025,.975]).tolist()}
        g["paired_circular_block_bootstrap"]=bootstrap
        result["games"][game]=g
    historical=load_historical_search()
    known={f"recency128:{k}":v for k,v in historical["p_unadjusted"].items()}
    known.update({f"prior492:{k}":v for k,v in original24.items()})
    known.update({f"current:{k}":v for k,v in family.items()})
    if len(family)!=144 or len(original24)!=24 or len(known)!=296:
        raise ValueError("MULTIPLICITY_FAMILY_INCOMPLETE")
    adjusted=holm(family); sensitivity=holm(known); original_adj=holm(original24)
    result["multiplicity"]={"current_family_n":144,"known_search_family_n":296,
        "prior492_holm24":original_adj,"current_raw144":family,"current_holm144":adjusted,
        "known_search_holm296":sensitivity,"min_current_adjusted":min(adjusted.values()),
        "min_known_search_adjusted":min(sensitivity.values()),
        "significant_current":[k for k,v in adjusted.items() if v<.05],
        "significant_known_search":[k for k,v in sensitivity.items() if v<.05],
        "scope":"Exploratory sensitivity. Repeated hypotheses intentionally counted conservatively; unknown searches not covered."}
    return result

def all_model_candidates(game,context):
    rows=[]
    for name in old.ACTIVE:
        ticket=old.one_ticket(game,context["history"],name,context["target_issue"])
        rows.append({"model":name,"status":"RESEARCH_CANDIDATE",
                     "role":"RANDOM_CONTROL" if name in NULLS else "NONRANDOM_RESEARCH",**ticket})
    for name in old.PHYSICAL:
        rows.append({"model":name,"status":"ABSTAIN","front":None,"back":None,
                     "d2":None,"kill3":None,
                     "reason":"No qualified predraw physical evidence supplied; no fallback is presented as a prediction."})
    return rows

def candidate_report(result,old_future):
    official=json.loads((HERE/"evidence/official_verification.json").read_text(encoding="utf-8"))
    contexts=historical_example.build()
    report={"decision":"NO_EDGE","formal_A":0,"mode":"RESEARCH_CANDIDATE","games":{},
            "trusted_predraw_seal":"UNVERIFIED","full_history_official_authenticity":"UNVERIFIED"}
    for game in ("SSQ","DLT"):
        context=contexts[game]; evidence=official["games"][game]
        snapshot=json.loads((HERE/"evidence"/evidence["snapshot"]).read_text(encoding="utf-8"))
        verify_official_snapshot(game,evidence,snapshot)
        check_target(context,evidence)
        name=result["games"][game]["selected_from_validation"]
        ticket=old.one_ticket(game,context["history"],name,context["target_issue"])
        prior=old_future["games"][game]
        if (ticket["front"]!=prior["front"] or ticket["back"]!=prior["back"] or
            ticket["d2"]!=prior["d2_candidates_unproven"] or ticket["kill3"]!=prior["kill3_unproven"]):
            raise ValueError("CANDIDATE_REPLAY_CHANGED")
        report["games"][game]={"target_issue":context["target_issue"],"draw_date_china":context["target_draw_date"],
            "all_models":all_model_candidates(game,context),
            "temporal_status":temporal_label(context["target_draw_date"],datetime.now(timezone.utc).isoformat()),
            "publication_scope":"Only as of the stored official observation; rerun is not a fresh official check.",
            "latest_confirmed_issue":evidence["latest_issue"],"model":name,**ticket,
            "latest_source":evidence["url"],"observed_utc":evidence["retrieved_utc"],
            "kill3_historical_test_error":result["games"][game]["test"]["metrics"][name]["kill3_error"],
            "kill3_fair_error":theory(game)["kill3_error"],
            "physics":{"physical_exit_order":"ABSTAIN","physical_ball_group":"ABSTAIN"}}
    return report

def write_results(out,payloads):
    out=Path(out); out.mkdir(parents=True,exist_ok=False)
    for name,payload in payloads.items():
        raw=payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
        with (out/name).open("x",encoding="utf-8",newline="\n") as f:f.write(raw)

def all_models_markdown(candidates):
    lines=["# 2026-11-13 核验时点：SSQ / DLT 全模型研究候选","",
           "每彩种14条可运行模型（含2条随机对照）+2条物理ABSTAIN。NO_EDGE；不自动投注。",
           "D2为注册的两枚红球/前区号码；杀号是可能误杀的低排位候选，没有任何保证。",
           "旧超算D2沿用母体口径：已排序前区票的最小两个数。其随机对照未注册杀号。",""]
    fmt=lambda x:"—" if x is None else " ".join(f"{n:02d}" for n in x)
    for game,g in candidates["games"].items():
        lines += [f"## {game} {g['target_issue']}，中国开奖日期 {g['draw_date_china']}",
                  f"官方最新已开奖 {g['latest_confirmed_issue']}；来源 {g['latest_source']}。",
                  f"只代表 {g['observed_utc']} 的核验；{g['temporal_status']}。",
                  f"验证区选型 **{g['model']}**；两个物理模型都拒绝预测。","",
                  "| 模型 | 红球/前区 | 蓝球/后区 | D2候选 | 杀号3码候选 | 状态 |",
                  "|---|---|---|---|---|---|"]
        for r in g["all_models"]:
            status=r["status"]+(" / 随机对照" if r.get("role")=="RANDOM_CONTROL" else "")
            lines.append(f"| {r['model']} | {fmt(r['front'])} | {fmt(r['back'])} | {fmt(r['d2'])} | {fmt(r['kill3'])} | {status} |")
        k=g["kill3_historical_test_error"]
        lines += ["",f"验证选定模型的旧测试杀号误杀 {k['k']}/{k['n']}={k['rate']:.2%}；95% Wilson {k['wilson95'][0]:.2%}–{k['wilson95'][1]:.2%}。",
                  f"公平随机排除3码误杀率 {g['kill3_fair_error']:.2%}。",""]
    lines += ["全部历史比较见 report.md / analysis.json。真正未参与选型测试 n=0，BLOCKED；不能把历史冠军称为可靠预测冠军。",
              "SHA及公开GitHub提交只记录本次内容，未认证全历史来源，也不是第三方可信预售封存。",""]
    return "\n".join(lines)

def markdown(r,c):
    lines=["# SSQ / DLT 严格扩展审计","",
        "**NO_EDGE；formal_A=0。真正未参与选型测试：BLOCKED，n=0，不能产生冠军。**",
        "原验证/测试区都已被研究者查看；下列排名、区间和p值均为事后描述。",
        "完整票=全部红球/前区和蓝球/后区都中；不等于中任意奖。杀号误杀=三个排除号至少一个开出。",""]
    for game,g in r["games"].items():
        lines += [f"## {game}",f"验证选型：**{g['selected_from_validation']}**；旧测试区事后最高：**{g['old_test_posthoc_winner']}**。",
                  f"公平随机 D2={g['fair']['d2']:.4%}；完整票={g['fair']['ticket']:.12%}；杀3码误杀={g['fair']['kill3_error']:.4%}。","",
                  "| 模型 | 验证D2 | 旧测试D2 | 旧测试95% Wilson | 旧测试杀3误杀及95% Wilson | 完整票及95%精确上限 |",
                  "|---|---:|---:|---|---|---|"]
        order=g["test"]["ranking_nonrandom"]+[m for m in old.ACTIVE if m in NULLS]
        for m in order:
            v=g["validation"]["metrics"][m]["d2"]; s=g["test"]["metrics"][m]; d=s["d2"]; k=s["kill3_error"]; f=s["full_ticket"]
            ks="无注册杀号，未计算" if k["rate"] is None else f"{k['k']}/{k['n']}={k['rate']:.2%} [{k['wilson95'][0]:.2%},{k['wilson95'][1]:.2%}]"
            lines.append(f"| {m} | {v['k']}/{v['n']} | {d['k']}/{d['n']}={d['rate']:.2%} | {d['wilson95'][0]:.2%}–{d['wilson95'][1]:.2%} | {ks} | {f['k']}/{f['n']} 上限{f['exact95'][1]:.3%} |")
        choice=g["selected_from_validation"]
        q=[b["hits"][choice] for b in g["test"]["quarters"]]
        lines += ["",f"选定模型旧测试区四等分命中数：{q}。",
            f"配对区块重采样选定模型减固定NULL的95%差值区间："+
            "；".join(f"L={l}: {v['selected_minus_null95'][0]:.2%} 至 {v['selected_minus_null95'][1]:.2%}" for l,v in g["paired_circular_block_bootstrap"].items()),
            f"旧测试命中序列有效秩（仅描述）={g['test']['correlation']['spectral_effective_rank_descriptive_only']:.3f} / 14；不能据此减少检验数。",
            f"完全相同D2命中序列：{g['test']['correlation']['identical_hit_streams']}。"]
        f=c["games"][game]
        lines += ["",f"### 研究候选 {f['target_issue']}（中国开奖日期 {f['draw_date_china']}）",
            f"仅代表 {f['observed_utc']} 核验时点；本次重放状态 {f['temporal_status']}；重跑不会自动重新查询官方最新期。",
            f"红球/前区 {f['front']}；蓝球/后区 {f['back']}；D2 {f['d2']}；排除候选 {f['kill3']}。",
            f"最新已开奖 {f['latest_confirmed_issue']}，核验来源：{f['latest_source']}。",
            "物理出球/球组均 ABSTAIN；候选不是可信优势或保证，不自动投注。",""]
    m=r["multiplicity"]
    lines += ["## 检验与证据",
        f"144项当前族 Holm 最小p={m['min_current_adjusted']:.6g}；296项已知重复搜索敏感性最小p={m['min_known_search_adjusted']:.6g}。",
        f"当前族显著项：{m['significant_current']}；已知搜索族显著项：{m['significant_known_search']}。",
        "296包含此前128项、PR492的24项和本次144项，重复假设有意保守计数；不能覆盖未知历史搜索。",
        "95%区间为逐项边际描述区间，没有校正选冠军过程。重采样不重新训练模型，不能制造独立样本。",
        "已验证：原ZIP/成员/历史哈希、逐期D2计数、边界与抽样复放、最新官方期号匹配。",
        "UNVERIFIED：全历史官方真实性、第三方开奖前可信封存、逐期杀号配对检验。",
        "BLOCKED：真正未触碰测试集与其最高模型；仍需未来逐期事前记录。",
        "来源保存的是Firecrawl抽取文本JSON，不是官方HTTP原始字节。SHA证明留存内容一致，不证明事前已知。",
        "统计方法：[SciPy binomial test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)；"+
        "[95% exact/Wilson intervals](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)。",
        "完整相关矩阵、两窗口全部指标/区间、逐块数据与重采样见 analysis.json。",""]
    return "\n".join(lines)

def run(out,reps=10000):
    prior,future,receipt=load_prior(); history=load_history()
    validate_prior(prior,history)
    replay=replay_sample(prior,history)
    result=compute(prior,reps); result["sampled_replay"]=replay
    candidates=candidate_report(result,future)
    files=[p for p in (ROOT/"research").rglob("*") if p.is_file() and p.suffix in (".py",".gz")]
    files += [p for p in (HERE/"evidence").iterdir() if p.is_file()]
    provenance={"upstream_base":BASE_SHA,"github_execution_sha":os.environ.get("GITHUB_SHA"),
        "execution_source":"actions_checkout" if os.environ.get("GITHUB_SHA") else "isolated_codeload_snapshot_with_local_git_baseline",
        "runtime":{"numpy":np.__version__,"scipy":scipy.__version__},
        "prior_run":"https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/43422587316",
        "prior_receipt":receipt,"source_sha256":{p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(set(files))},
        "checks":{"prior_integrity":"PASS","chronology":"PASS","sampled_d2_replay":"PASS",
                  "untouched_test":"BLOCKED","physics":"ABSTAIN","independent_predraw_seal":"UNVERIFIED"}}
    protocol={"status":"DESIGN_ONLY_NOT_ACTIVATED","n_scored_clean":0,
        "start":"First eligible draw after public commit plus verified presale publication",
        "selected_models":{g:x["selected_from_validation"] for g,x in result["games"].items()},
        "endpoint":"registered D2 both hit","eligible_draws_per_game":500,
        "family":"two games, max(fair p, paired fixed NULL p), Holm .05",
        "optional_stopping":False,"model_switching":False,"retain_failed_or_missing_seals":True,
        "missing_seal_policy":"Record failure; no success assigned; block complete-case promotion",
        "parameters_and_null_unchanged":True,"betting":False}
    payload={"analysis.json":result,"candidates.json":candidates,"provenance.json":provenance,
             "prospective_design.json":protocol,"report.md":markdown(result,candidates),
             "all_models.md":all_models_markdown(candidates)}
    write_results(out,payload)
    hashes={p.name:digest(p.read_bytes()) for p in sorted(Path(out).iterdir())}
    with (Path(out)/"SHA256.json").open("x",encoding="utf-8",newline="\n") as f:
        json.dump(hashes,f,sort_keys=True,indent=2);f.write("\n")
    print(json.dumps({"status":"PASS_COMPUTATION","edge":"NO_EDGE","untouched_test":"BLOCKED","reps":reps,
        "replay_pairs":replay["checked_model_draw_pairs"],"holm144_min":result["multiplicity"]["min_current_adjusted"],
        "holm296_min":result["multiplicity"]["min_known_search_adjusted"],"sha256":hashes},sort_keys=True))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reps",type=int,default=10000)
    args=parser.parse_args()
    if args.out.exists(): raise FileExistsError("CREATE_ONLY_OUTPUT_EXISTS")
    run(args.out,args.reps)

if __name__=="__main__": main()
