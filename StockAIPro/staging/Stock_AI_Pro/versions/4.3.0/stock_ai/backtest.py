from __future__ import annotations
import json
import numpy as np,pandas as pd
from .config import ROOT,load_config
from .data_source import load_histories
from .features import build_dataset
from .model import rank_ic,train_validated_ensemble,predict_ensemble
from .utils import write_json,now_iso,read_json
from .cost import historical_roundtrip_cost_rate
from .valuation import merge_historical_valuation,add_historical_valuation_score,qualify_backtest_valuation_histories
from .historical_pit import load_verified_historical_st_pit

def _max_drawdown(returns):
    eq=(1+pd.Series(returns).fillna(0)).cumprod(); return float((eq/eq.cummax()-1).min())
def _limit_pct(code): return .20 if str(code).startswith(("300","301","688")) else .10
def _tradable_next_open(row):
    try:
        prev=float(row["signal_close"]);low=float(row["entry_low"]);op=float(row["entry_open"])
        if not np.isfinite(prev) or not np.isfinite(low) or not np.isfinite(op) or prev<=0:return False
        return low<prev*(1+_limit_pct(row["code"])*.985)
    except Exception:return False

def _pit_market(code):
    code=str(code)
    if code.startswith(("6","9")): return "SSE"
    if code.startswith(("4","8")): return "BSE"
    return "SZSE"

def _apply_historical_pit_policy(ds,cfg,root=None):
    """Apply exact-date historical ST/suspension policy before any backtest selection.

    This is deliberately fail-closed.  The policy accepts only the canonical
    bytes whose evidence/hash gate passes, joins signal and next-market-day
    state by exact (date, code), and never uses backward/as-of lookup.
    """
    root=ROOT if root is None else root
    x=ds.copy()
    if x.empty:return x,{"status":"PASS","input_rows":0,"output_rows":0}
    if "entry_date" not in x.columns:
        raise RuntimeError("historical PIT policy requires entry_date in feature dataset")
    latest=read_json(root/"cache"/"last_update_status.json",{}) or {}
    expected=latest.get("expected_trade_date")
    pit,evidence=load_verified_historical_st_pit(root,expected)

    x["date"]=pd.to_datetime(x["date"],errors="coerce").dt.normalize()
    x["entry_date"]=pd.to_datetime(x["entry_date"],errors="coerce").dt.normalize()
    x["code"]=x["code"].astype(str).str.zfill(6)
    if x["date"].isna().any() or x["entry_date"].isna().any():
        raise RuntimeError("historical PIT policy found invalid signal/entry dates")
    x["_pit_market"]=x["code"].map(_pit_market)

    p=pit.copy()
    p["date"]=pd.to_datetime(p["date"],errors="raise").dt.normalize()
    p["code"]=p["code"].astype(str).str.zfill(6)

    signal=p[["date","code","market","st","suspended"]].rename(columns={
        "market":"_pit_signal_market","st":"_pit_signal_st","suspended":"_pit_signal_suspended"
    })
    x=x.merge(signal,on=["date","code"],how="left",validate="many_to_one")
    missing_signal=x["_pit_signal_st"].isna()|x["_pit_signal_suspended"].isna()|x["_pit_signal_market"].isna()
    if bool(missing_signal.any()):
        sample=x.loc[missing_signal,["date","code"]].head(5).to_dict("records")
        raise RuntimeError(f"historical PIT missing exact signal-date coverage: {sample}")
    bad_signal_market=x["_pit_signal_market"]!=x["_pit_market"]
    if bool(bad_signal_market.any()):
        sample=x.loc[bad_signal_market,["date","code","_pit_signal_market","_pit_market"]].head(5).to_dict("records")
        raise RuntimeError(f"historical PIT signal market mismatch: {sample}")

    next_market={}
    for market,g in p.groupby("market"):
        dates=sorted(pd.Timestamp(v) for v in g["date"].dropna().unique())
        next_market.update({(market,dates[i]):dates[i+1] for i in range(len(dates)-1)})
    x["_pit_expected_entry_date"]=[next_market.get((m,pd.Timestamp(d))) for m,d in zip(x["_pit_market"],x["date"])]
    missing_calendar=pd.isna(x["_pit_expected_entry_date"])
    if bool(missing_calendar.any()):
        sample=x.loc[missing_calendar,["date","code","_pit_market"]].head(5).to_dict("records")
        raise RuntimeError(f"historical PIT trading calendar missing next market date: {sample}")
    x["_pit_expected_entry_date"]=pd.to_datetime(x["_pit_expected_entry_date"]).dt.normalize()

    entry=p[["date","code","market","st","suspended"]].rename(columns={
        "date":"_pit_expected_entry_date","market":"_pit_entry_market",
        "st":"_pit_entry_st","suspended":"_pit_entry_suspended"
    })
    x=x.merge(entry,on=["_pit_expected_entry_date","code"],how="left",validate="many_to_one")
    missing_entry=x["_pit_entry_st"].isna()|x["_pit_entry_suspended"].isna()|x["_pit_entry_market"].isna()
    if bool(missing_entry.any()):
        sample=x.loc[missing_entry,["date","_pit_expected_entry_date","code"]].head(5).to_dict("records")
        raise RuntimeError(f"historical PIT missing exact entry-date coverage: {sample}")
    bad_entry_market=x["_pit_entry_market"]!=x["_pit_market"]
    if bool(bad_entry_market.any()):
        sample=x.loc[bad_entry_market,["date","code","_pit_entry_market","_pit_market"]].head(5).to_dict("records")
        raise RuntimeError(f"historical PIT entry market mismatch: {sample}")

    aligned=x["entry_date"].eq(x["_pit_expected_entry_date"])
    signal_suspended=x["_pit_signal_suspended"].astype(bool)
    entry_suspended=x["_pit_entry_suspended"].astype(bool)
    signal_st=x["_pit_signal_st"].astype(bool)
    entry_st=x["_pit_entry_st"].astype(bool)
    keep=aligned & ~signal_suspended & ~entry_suspended
    exclude_st=bool((cfg.get("universe",{}) or {}).get("exclude_st",True))
    if exclude_st:keep &= ~signal_st & ~entry_st

    stats={
        "status":"PASS",
        "input_rows":int(len(x)),
        "output_rows":int(keep.sum()),
        "exclude_st":exclude_st,
        "excluded_signal_st":int(signal_st.sum()) if exclude_st else 0,
        "excluded_entry_st":int(entry_st.sum()) if exclude_st else 0,
        "excluded_signal_suspended":int(signal_suspended.sum()),
        "excluded_entry_suspended":int(entry_suspended.sum()),
        "excluded_not_next_market_open":int((~aligned).sum()),
        "exact_date_join":True,
        "future_lookup":False,
        "canonical_sha256":evidence.get("canonical_sha256"),
        "canonical_rows":evidence.get("row_count"),
        "window_start":evidence.get("window_start"),
        "window_end":evidence.get("window_end"),
    }
    drop=[c for c in x.columns if c.startswith("_pit_")]
    return x.loc[keep].drop(columns=drop).copy(),stats

def _historical_candidate_pool(ds,cfg):
    min_amt=float(cfg["universe"].get("min_turnover_cny",0)); top_n=int(cfg["universe"].get("live_top_n",300)); x=ds[ds["log_amount20"].notna()].copy()
    if min_amt>0:x=x[x["log_amount20"]>=np.log1p(min_amt)]
    if top_n>0 and not x.empty:
        x["liq_rank"]=x.groupby("date")["log_amount20"].rank(method="first",ascending=False);x=x[x["liq_rank"]<=top_n]
    return x

def _net_mean(frame,cfg,order_size=None):
    if frame.empty:return float('nan')
    return float((frame["target_return"]-historical_roundtrip_cost_rate(frame,cfg,order_size)).mean())

def _qualification_target(ds,dates,eval_dates,h,topk,min_test,min_train):
    for d in reversed(eval_dates):
        pos=dates.index(d)
        if pos<160 or pos-h<0:continue
        cutoff=dates[pos-h]
        train=ds[ds["date"]<cutoff]
        test=ds[ds["date"]==d].copy();test=test[test.apply(_tradable_next_open,axis=1)]
        if len(train)>=min_train and len(test)>=max(topk,min_test):
            return d,sorted(test["code"].astype(str).unique())
    return None,[]

def run_backtest():
    cfg=load_config();h=int(cfg["model"]["horizon_days"]); ds=build_dataset(load_histories(),h,int(cfg["model"]["min_history_days"])); target=cfg["model"].get("target","target_excess")
    ds=ds[ds[target].notna()&ds["target_return"].notna()].copy(); ds,pit_policy=_apply_historical_pit_policy(ds,cfg); ds=_historical_candidate_pool(ds,cfg)
    if ds.empty:raise RuntimeError("没有可回测数据")
    dates=sorted(ds["date"].unique()); lookback=int(cfg["backtest"]["lookback_eval_days"]); step=int(cfg["backtest"]["rebalance_every_days"]); eval_dates=dates[-lookback::step]
    max_eval=int(cfg["backtest"].get("max_eval_points",24) or 0)
    if max_eval>0 and len(eval_dates)>max_eval: eval_dates=eval_dates[-max_eval:]
    topk=int(cfg["model"]["top_k"]);trials=int(cfg["backtest"]["random_trials"]);rng=np.random.default_rng(int(cfg["model"]["random_state"])); min_test=int(cfg["backtest"].get("min_test_universe",50)); min_train=int(cfg["backtest"].get("min_train_rows",5000)); rows=[]
    cap_sizes=[int(x) for x in cfg["backtest"].get("capacity_order_sizes_cny",[100000,500000,1000000,5000000,10000000])]
    value_min=float(cfg.get("valuation",{}).get("backtest_min_coverage",.4)); value_valid_points=0
    qualification={"status":"NOT_REQUIRED","target_coverage":value_min}
    if (cfg.get("valuation",{}) or {}).get("enabled",True):
        qdate,qcodes=_qualification_target(ds,dates,eval_dates,h,topk,min_test,min_train)
        if qdate is None:
            qualification={"status":"FAIL","target_coverage":value_min,"error":"no eligible historical evaluation date for valuation qualification"}
        else:
            qualification=qualify_backtest_valuation_histories(qcodes,cfg,qdate,value_min)
    # PIT valuation only. Qualification is code-order deterministic and uses no return/prediction outcome.
    ds=merge_historical_valuation(ds); ds=add_historical_valuation_score(ds,cfg)
    model_max_rows=int(cfg["backtest"].get("max_train_rows",80000))
    validation_days=int(cfg["model"].get("validation_days",40))
    ensemble_mode=cfg["model"].get("ensemble_mode","validation_dynamic")
    for d in eval_dates:
        pos=dates.index(d)
        if pos<160 or pos-h<0:continue
        # Outer embargo: labels whose horizon could touch the test date are excluded.
        cutoff=dates[pos-h];train=ds[ds["date"]<cutoff].copy();test=ds[ds["date"]==d].copy();test=test[test.apply(_tradable_next_open,axis=1)]
        if len(train)<min_train or len(test)<max(topk,min_test):continue
        train=train.sort_values("date").tail(model_max_rows)
        try:
            models,weights,metrics,dev,valid,final_train=train_validated_ensemble(
                train,target,h,validation_days,int(cfg["model"]["random_state"]),ensemble_mode,cfg["model"],model_max_rows)
        except RuntimeError:
            continue
        test=predict_ensemble(models,test,weights);top=test.sort_values("pred",ascending=False).head(topk)
        strat=_net_mean(top,cfg); market=float(test["target_return"].median()); momset=test.sort_values("ret20",ascending=False).head(topk);momentum=_net_mean(momset,cfg)
        vals=[]
        for _ in range(trials):
            sample=test.iloc[rng.choice(len(test),size=topk,replace=False)];vals.append(_net_mean(sample,cfg))
        rnd=float(np.mean(vals)); val_cov=float(test[["pe_ttm_hist","pb_hist"]].notna().any(axis=1).mean())
        value=float('nan')
        if val_cov>=value_min:
            value_valid_points+=1; value=_net_mean(test.sort_values("score_valuation_hist",ascending=False).head(topk),cfg)
        row={"date":pd.Timestamp(d).strftime("%Y-%m-%d"),"strategy_return":strat,"market_median_return":market,"random_return":rnd,"momentum_return":momentum,"value_return":value,"valuation_coverage":val_cov,"excess_vs_market":strat-market,"excess_vs_random":strat-rnd,"rank_ic":rank_ic(test[target],test["pred"]),"validation_rank_ic":metrics.get("rank_ic"),"universe_n":len(test),"entry_assumption":"next_open","ensemble_mode":metrics.get("ensemble_mode"),"model_weights":json.dumps(weights,sort_keys=True)}
        for size in cap_sizes: row[f"strategy_return_cap_{size}"]=_net_mean(top,cfg,size)
        rows.append(row)
    out=pd.DataFrame(rows)
    if out.empty:raise RuntimeError("回测没有有效评估点；研究历史池可能尚未补齐")
    for col,name in [("strategy_return","equity"),("random_return","random_equity"),("momentum_return","momentum_equity")]:out[name]=(1+out[col].fillna(0)).cumprod()
    if out["value_return"].notna().any():out["value_equity"]=(1+out["value_return"].fillna(0)).cumprod()
    out.to_csv(ROOT/"reports"/"backtest.csv",index=False,encoding="utf-8-sig")
    capacity={str(size):float(out[f"strategy_return_cap_{size}"].mean()) for size in cap_sizes}; base=capacity.get(str(cap_sizes[0]),float('nan')); cap_limit=max([s for s in cap_sizes if np.isfinite(capacity[str(s)]) and (not np.isfinite(base) or capacity[str(s)]>0)],default=0)
    summary={"generated_at":now_iso(),"software_version":"4.3.0-deliverable","eval_points":len(out),"mean_strategy_return":float(out.strategy_return.mean()),"mean_random_return":float(out.random_return.mean()),"mean_market_return":float(out.market_median_return.mean()),"mean_momentum_return":float(out.momentum_return.mean()),"mean_value_return":float(out.value_return.mean()) if out.value_return.notna().any() else None,"value_baseline_validated":bool(value_valid_points>0),"value_valid_points":value_valid_points,"valuation_qualification":qualification,"mean_excess_vs_random":float(out.excess_vs_random.mean()),"mean_excess_vs_market":float(out.excess_vs_market.mean()),"positive_excess_rate":float((out.excess_vs_random>0).mean()),"mean_rank_ic":float(out.rank_ic.mean()),"mean_validation_rank_ic":float(pd.to_numeric(out.validation_rank_ic,errors='coerce').mean()),"max_drawdown":_max_drawdown(out.strategy_return),"dynamic_cost_model":True,"production_model_parity":True,"historical_pit_policy":pit_policy,"model_stack":["ridge","hgb","extra_trees"],"capacity_mean_net_returns":capacity,"capacity_limit_cny":cap_limit,"entry_assumption":"信号日收盘后生成；下一交易日开盘入场；第horizon交易日收盘退出。","universe_note":"历史候选池先严格消费哈希绑定的逐日ST/停牌PIT状态，再按历史成交额门槛及流动性排名重建；精确(date,code)连接，不使用未来状态或今天股票池倒推。","valuation_note":"Value Baseline 仅使用估值日期<=信号日期的历史PIT缓存；资格补齐按最新合格评估日、股票代码固定顺序执行，不按收益/预测挑样本；覆盖不足时标记未验证。","model_note":"每个回测点只使用该日以前的数据，并在历史训练区内部再次使用 horizon embargo 的验证窗口学习集成权重。"}
    write_json(ROOT/"reports"/"backtest_summary.json",summary);return out,summary
