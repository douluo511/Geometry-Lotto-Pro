from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .config import ROOT, CODE_ROOT, load_config
from .data_source import load_histories
from .utils import now_iso, write_json

STRATEGIES = {
    "production": "production_rank",
    "ridge_only": "ridge_rank",
    "hgb_only": "hgb_rank",
    "extra_trees_only": "extra_trees_rank",
    "equal_ensemble": "equal_rank",
    "momentum_value": "momentum_value_rank",
}
PROMOTABLE_MODES = {
    "ridge_only": "ridge_only",
    "hgb_only": "hgb_only",
    "extra_trees_only": "extra_trees_only",
    "equal_ensemble": "equal",
}


def _canonical_hash(obj) -> str:
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _file_hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def _build_evidence(cfg, hist: pd.DataFrame, audit: dict, degradation: dict, gates: list[dict]):
    used_dates=sorted(set(hist.get("signal_date",pd.Series(dtype=str)).astype(str).tolist())) if not hist.empty else []
    frozen=[]
    for d in used_dates:
        p=ROOT/"predictions"/d/"manifest.json"
        if p.exists(): frozen.append({"signal_date":d,"manifest_sha256":_file_hash(p)})
    stable={
        "schema_version":1,
        "software_version":(CODE_ROOT/"VERSION").read_text(encoding="utf-8").strip() if (CODE_ROOT/"VERSION").exists() else "unknown",
        "config_sha256":_canonical_hash(cfg),
        "shadow_history_sha256":_canonical_hash(hist.sort_values([c for c in ["signal_date","strategy"] if c in hist.columns]).to_dict("records")),
        "audit_sha256":_canonical_hash({k:v for k,v in (audit or {}).items() if k!="generated_at"}),
        "frozen_manifests":frozen,
        "degradation":degradation,
        "promotion_gates":gates,
    }
    evidence_id=_canonical_hash(stable)
    return evidence_id, stable

def _update_candidate_registry(evidence_id: str, gates: list[dict], stable: dict):
    path=ROOT/"reports"/"rnd_candidate_registry.json"
    try: registry=json.loads(path.read_text(encoding="utf-8"))
    except Exception: registry={"schema_version":1,"candidates":[]}
    existing={str(x.get("candidate_id")):x for x in registry.get("candidates",[]) if x.get("candidate_id")}
    for g in gates:
        if g.get("status")!="PROMOTABLE_REVIEW" or not g.get("proposed_config_patch"): continue
        payload={"evidence_id":evidence_id,"challenger":g.get("challenger"),"proposed_config_patch":g.get("proposed_config_patch")}
        cid=_canonical_hash(payload)
        existing[cid]={
            "candidate_id":cid,
            "evidence_id":evidence_id,
            "challenger":g.get("challenger"),
            "status":"PROMOTABLE_REVIEW",
            "proposed_config_patch":g.get("proposed_config_patch"),
            "paired_points":g.get("paired_points"),
            "mean_excess_improvement":g.get("mean_excess_improvement"),
            "win_rate_vs_production":g.get("win_rate_vs_production"),
            "created_at":now_iso(),
            "auto_promote":False,
        }
    registry={"schema_version":1,"updated_at":now_iso(),"candidates":list(existing.values())[-200:]}
    write_json(path,registry)
    return registry

def _rank(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").rank(method="first", ascending=False)

def _num_col(frame: pd.DataFrame, name: str, default=np.nan) -> pd.Series:
    if name in frame.columns:
        return pd.to_numeric(frame[name],errors="coerce")
    return pd.Series(default,index=frame.index,dtype=float)

def build_shadow_frame(scored: pd.DataFrame) -> pd.DataFrame:
    x=scored.copy()
    cost=_num_col(x,"estimated_roundtrip_cost_bps",0).fillna(0)/10000.0
    x["production_score"]=_num_col(x,"final_score")
    x["production_net_alpha"]=_num_col(x,"expected_net_alpha")
    x["ridge_net_alpha"]=_num_col(x,"pred_ridge")-cost
    x["hgb_net_alpha"]=_num_col(x,"pred_hgb")-cost
    x["extra_trees_net_alpha"]=_num_col(x,"pred_extra_trees")-cost
    preds=pd.concat([_num_col(x,c) for c in ["pred_ridge","pred_hgb","pred_extra_trees"]],axis=1)
    x["equal_net_alpha"]=preds.mean(axis=1)-cost
    mom=_num_col(x,"score_momentum",50).fillna(50)
    val=_num_col(x,"score_valuation",50).fillna(50)
    cst=_num_col(x,"score_cost",50).fillna(50)
    x["momentum_value_score"]=.45*mom+.40*val+.15*cst
    x["production_rank"]=_rank(x["production_score"])
    x["ridge_rank"]=_rank(x["ridge_net_alpha"])
    x["hgb_rank"]=_rank(x["hgb_net_alpha"])
    x["extra_trees_rank"]=_rank(x["extra_trees_net_alpha"])
    x["equal_rank"]=_rank(x["equal_net_alpha"])
    x["momentum_value_rank"]=_rank(x["momentum_value_score"])
    keep=["code","name","industry","date","estimated_roundtrip_cost_bps","production_score","production_net_alpha",
          "ridge_net_alpha","hgb_net_alpha","extra_trees_net_alpha","equal_net_alpha","momentum_value_score"]+list(STRATEGIES.values())
    keep=[c for c in keep if c in x.columns]
    return x[keep].sort_values("production_rank").reset_index(drop=True)

def _verify_frozen_dir(path: Path) -> bool:
    mf=path/"manifest.json"
    if not mf.exists(): return False
    try: m=json.loads(mf.read_text(encoding="utf-8"))
    except Exception: return False
    for name,expected in (m.get("files") or {}).items():
        p=path/name
        if not p.exists(): return False
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        if h!=expected: return False
    return True

def _prepare_lookup(histories: dict[str,pd.DataFrame]):
    out={}
    for code,df in histories.items():
        if df is None or df.empty: continue
        x=df.copy();x["date"]=pd.to_datetime(x["date"],errors="coerce").dt.strftime("%Y-%m-%d");x=x.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        pos={d:i for i,d in enumerate(x["date"].tolist())}
        out[str(code)]=(x,pos)
    return out

def _realized(lookup,code,signal_date,horizon):
    item=lookup.get(str(code))
    if not item:return np.nan
    x,pos=item;i=pos.get(str(signal_date))
    if i is None or i+1>=len(x) or i+horizon>=len(x): return np.nan
    try:
        entry=float(x.iloc[i+1]["open"]); exit_=float(x.iloc[i+horizon]["close"])
        if not np.isfinite(entry) or not np.isfinite(exit_) or entry<=0:return np.nan
        return exit_/entry-1
    except Exception:return np.nan

def _max_drawdown(returns):
    s=pd.Series(returns,dtype=float).fillna(0)
    if s.empty:return None
    eq=(1+s).cumprod();return float((eq/eq.cummax()-1).min())

def _bootstrap_ci(diff, trials, seed=42):
    a=np.asarray(pd.Series(diff).dropna(),dtype=float)
    if len(a)<2:return (None,None)
    rng=np.random.default_rng(seed);n=len(a);means=np.empty(int(trials),dtype=float)
    for i in range(int(trials)):means[i]=a[rng.integers(0,n,n)].mean()
    return float(np.quantile(means,.05)),float(np.quantile(means,.95))

def evaluate_shadow_history(cfg=None):
    cfg=cfg or load_config();rcfg=cfg.get("rnd",{}) or {};h=int(cfg["model"]["horizon_days"]);topk=int(rcfg.get("top_k",cfg["model"].get("top_k",20)))
    dirs=[p for p in (ROOT/"predictions").glob("*") if p.is_dir() and p.name not in {"latest","_forced_backups"} and (p/"rnd_shadow.csv").exists()]
    dirs=sorted(dirs,key=lambda p:p.name)[-int(rcfg.get("max_prediction_days",120)):]
    frozen=[];codes=set()
    for d in dirs:
        if not _verify_frozen_dir(d):continue
        try:x=pd.read_csv(d/"rnd_shadow.csv",dtype={"code":str})
        except Exception:continue
        if x.empty:continue
        frozen.append((d.name,x));codes.update(x["code"].astype(str).tolist())
    if not frozen:return pd.DataFrame()
    lookup=_prepare_lookup(load_histories(sorted(codes)))
    rows=[]
    for signal_date,x in frozen:
        y=x.copy();y["realized_gross"]=[_realized(lookup,c,signal_date,h) for c in y["code"].astype(str)]
        y=y[pd.to_numeric(y["realized_gross"],errors="coerce").notna()].copy()
        if len(y)<max(topk,10):continue
        cost=pd.to_numeric(y.get("estimated_roundtrip_cost_bps",0),errors="coerce").fillna(0)/10000.0
        y["realized_net"]=pd.to_numeric(y["realized_gross"],errors="coerce")-cost
        universe=float(y["realized_net"].median())
        for strategy,rank_col in STRATEGIES.items():
            if rank_col not in y:continue
            chosen=y.sort_values(rank_col).head(topk)
            if chosen.empty:continue
            net=float(chosen["realized_net"].mean());gross=float(chosen["realized_gross"].mean())
            rows.append({"signal_date":signal_date,"strategy":strategy,"gross_return":gross,"net_return":net,"universe_median_net":universe,"excess_vs_universe":net-universe,"n":int(len(chosen))})
    return pd.DataFrame(rows)

def _strategy_summary(hist:pd.DataFrame):
    out={}
    for s,g in hist.groupby("strategy"):
        g=g.sort_values("signal_date")
        out[s]={"eval_points":int(len(g)),"mean_net_return":float(g["net_return"].mean()),"mean_excess":float(g["excess_vs_universe"].mean()),"positive_excess_rate":float((g["excess_vs_universe"]>0).mean()),"max_drawdown":_max_drawdown(g["net_return"])}
    return out

def _degradation(hist,cfg):
    rcfg=cfg.get("rnd",{}) or {};w=int(rcfg.get("recent_window",6));thr=float(rcfg.get("degradation_threshold",.002))
    p=hist[hist.strategy=="production"].sort_values("signal_date")
    if len(p)<max(w*2,6):return {"status":"WAITING","detail":"冻结实盘样本不足，继续积累。"}
    recent=float(p.tail(w)["excess_vs_universe"].mean());prior=float(p.iloc[:-w].tail(max(w,len(p)-w))["excess_vs_universe"].mean())
    degraded=(recent<0 and recent<prior-thr)
    return {"status":"DEGRADED" if degraded else "STABLE","recent_mean_excess":recent,"prior_mean_excess":prior,"threshold":thr}

def _promotion_gates(hist,summary,cfg,audit):
    rcfg=cfg.get("rnd",{}) or {};minpts=int(rcfg.get("min_eval_points",12));minimp=float(rcfg.get("min_mean_improvement",.001));minwin=float(rcfg.get("min_win_rate",.55));ddtol=float(rcfg.get("max_drawdown_tolerance",.03));trials=int(rcfg.get("bootstrap_trials",1000));require_ci=bool(rcfg.get("require_positive_ci_lower",True))
    prod=hist[hist.strategy=="production"][["signal_date","excess_vs_universe"]].rename(columns={"excess_vs_universe":"production"})
    prod_dd=(summary.get("production") or {}).get("max_drawdown")
    gates=[]
    for challenger in STRATEGIES:
        if challenger=="production":continue
        c=hist[hist.strategy==challenger][["signal_date","excess_vs_universe"]].rename(columns={"excess_vs_universe":"challenger"})
        m=prod.merge(c,on="signal_date",how="inner");diff=m["challenger"]-m["production"] if not m.empty else pd.Series(dtype=float)
        n=int(len(diff));mean=float(diff.mean()) if n else None;win=float((diff>0).mean()) if n else None;lo,hi=_bootstrap_ci(diff,trials)
        ch_dd=(summary.get(challenger) or {}).get("max_drawdown")
        tests={
            "sample_size": n>=minpts,
            "mean_improvement": mean is not None and mean>=minimp,
            "win_rate": win is not None and win>=minwin,
            "bootstrap_ci": (not require_ci) or (lo is not None and lo>0),
            "drawdown": prod_dd is not None and ch_dd is not None and ch_dd>=prod_dd-ddtol,
            "audit_trust": str((audit or {}).get("trust","MEDIUM")).upper()!="LOW",
            "production_mode_supported": challenger in PROMOTABLE_MODES,
        }
        status="PROMOTABLE_REVIEW" if all(tests.values()) else ("WAITING" if n<minpts else "REJECT")
        gates.append({"challenger":challenger,"status":status,"paired_points":n,"mean_excess_improvement":mean,"win_rate_vs_production":win,"bootstrap_90_ci":[lo,hi],"challenger_max_drawdown":ch_dd,"production_max_drawdown":prod_dd,"tests":tests,"proposed_config_patch":{"model":{"ensemble_mode":PROMOTABLE_MODES[challenger]}} if challenger in PROMOTABLE_MODES else None})
    return gates

def _five_why(degradation,gates):
    issues=[]
    if degradation.get("status")=="DEGRADED":
        issues.append({"issue":"生产模型近期相对表现下降","why1":"最近冻结样本的相对收益低于此前窗口。","why2":"市场结构可能变化，训练关系在新状态下减弱。","why3":"动态集成权重只依据验证窗口，可能未覆盖当前状态。","why4":"如果直接追逐最近结果，会产生二次过拟合。","why5":"处置：保留生产版，继续冻结 challenger；只有配对样本、Bootstrap、回撤和审计 Gate 同时通过才允许进入人工复核。"})
    rejected=[g for g in gates if g["status"]=="REJECT"]
    if rejected:
        issues.append({"issue":"Challenger 未达到晋级门槛","why1":"样本外改善不足或不稳定。","why2":"单一窗口/模型优势不能证明可重复 Alpha。","why3":"交易成本、市场状态和随机波动可能解释表面优势。","why4":"过早晋级会把研究噪声带入生产。","why5":"处置：不自动修改生产配置，继续积累冻结样本并重新验证。"})
    return issues

def run_rnd_cycle(cfg=None, logger=None):
    cfg=cfg or load_config();rcfg=cfg.get("rnd",{}) or {}
    if not rcfg.get("enabled",True):
        report={"generated_at":now_iso(),"status":"DISABLED"};write_json(ROOT/"reports"/"rnd_report.json",report);return report
    hist=evaluate_shadow_history(cfg)
    if hist.empty:
        report={"generated_at":now_iso(),"status":"WAITING_FOR_REALIZED_FROZEN_SAMPLES","auto_promote":False,"production_change_applied":False,"note":"研发闭环只使用先冻结、后实现的结果；不会用当前结果回填历史。"}
        write_json(ROOT/"reports"/"rnd_report.json",report);return report
    (ROOT/"reports").mkdir(parents=True,exist_ok=True);hist.to_csv(ROOT/"reports"/"rnd_shadow_history.csv",index=False,encoding="utf-8-sig")
    summary=_strategy_summary(hist)
    try:audit=json.loads((ROOT/"reports"/"audit_report.json").read_text(encoding="utf-8"))
    except Exception:audit={}
    degradation=_degradation(hist,cfg);gates=_promotion_gates(hist,summary,cfg,audit);promotable=[g for g in gates if g["status"]=="PROMOTABLE_REVIEW"]
    evidence_id,stable=_build_evidence(cfg,hist,audit,degradation,gates)
    report={"generated_at":now_iso(),"status":"PROMOTABLE_REVIEW" if promotable else "RESEARCH_ONLY","evaluation_rule":"Only pre-outcome frozen shadow predictions are evaluated; realized returns use next-open to horizon-close and frozen estimated costs.","strategy_summary":summary,"degradation":degradation,"promotion_gates":gates,"promotable_candidates":promotable,"five_why":_five_why(degradation,gates),"reverse_validation":["Champion-vs-Challenger paired dates","Bootstrap confidence interval","Win-rate threshold","Drawdown non-inferiority","Audit trust gate","Frozen-before-outcome integrity","Reproducible evidence fingerprint"],"evidence_id":evidence_id,"auto_promote":False,"production_change_applied":False,"note":"系统可以自动研究和提出候选，但不会因为短期结果自动改生产模型。晋级必须先通过冻结样本 Gate，再进入人工复核/正式版本验收。"}
    registry=_update_candidate_registry(evidence_id,gates,stable)
    report["candidate_registry_count"]=len(registry.get("candidates",[]))
    write_json(ROOT/"reports"/"rnd_report.json",report)
    evidence={**stable,"evidence_id":evidence_id,"generated_at":now_iso(),"report_sha256":_file_hash(ROOT/"reports"/"rnd_report.json")}
    write_json(ROOT/"reports"/"rnd_evidence.json",evidence)
    if logger:logger.info("R&D闭环: %s / realized points=%s / evidence=%s",report["status"],len(hist),evidence_id[:12])
    return report
