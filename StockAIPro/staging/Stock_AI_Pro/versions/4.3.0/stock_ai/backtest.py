from __future__ import annotations
import json
import numpy as np,pandas as pd
from .config import ROOT,load_config
from .data_source import load_histories
from .features import build_dataset
from .model import rank_ic,train_validated_ensemble,predict_ensemble
from .utils import write_json,now_iso
from .cost import historical_roundtrip_cost_rate
from .valuation import merge_historical_valuation,add_historical_valuation_score,qualify_backtest_valuation_histories
from .historical_pit import load_historical_st_pit_subset

def _max_drawdown(returns):
    eq=(1+pd.Series(returns).fillna(0)).cumprod(); return float((eq/eq.cummax()-1).min())
def _limit_pct(code): return .20 if str(code).startswith(("300","301","688")) else .10
def _tradable_next_open(row):
    try:
        prev=float(row["signal_close"]);low=float(row["entry_low"]);op=float(row["entry_open"])
        if not np.isfinite(prev) or not np.isfinite(low) or not np.isfinite(op) or prev<=0:return False
        return low<prev*(1+_limit_pct(row["code"])*.985)
    except Exception:return False

def _historical_candidate_pool(ds,cfg,research_calendar):
    min_amt=float(cfg["universe"].get("min_turnover_cny",0)); top_n=int(cfg["universe"].get("live_top_n",300))
    x=ds[ds["log_amount20"].notna()].copy()
    # Turnover threshold is independent of ST/PIT and commutes with that filter.
    # The non-commuting Top-N rank is intentionally applied only AFTER
    # signal-date ST/suspension state has been removed, matching live policy.
    if min_amt>0:x=x[x["log_amount20"]>=np.log1p(min_amt)]
    if x.empty:
        return x,{"status":"NOT VERIFIED","reason":"empty_after_turnover_filter"}

    calendar=sorted({pd.Timestamp(d).normalize() for d in research_calendar if pd.notna(d)})
    if len(calendar)<2:
        raise RuntimeError("historical PIT policy requires at least two research trading dates")
    expected_trade_date=calendar[-1].strftime("%Y-%m-%d")

    signal_day=pd.to_datetime(x["date"],errors="coerce").dt.strftime("%Y-%m-%d")
    actual_entry_day=pd.to_datetime(x["entry_date"],errors="coerce").dt.strftime("%Y-%m-%d")
    codes=x["code"].astype(str).str.zfill(6)
    if signal_day.isna().any():
        raise RuntimeError("historical PIT policy found invalid signal dates")
    signal_keys=list(zip(signal_day.tolist(),codes.tolist()))
    signal_states,signal_evidence=load_historical_st_pit_subset(
        ROOT,signal_keys,expected_trade_date=expected_trade_date
    )

    x["code"]=codes
    x["_pit_market"]=[signal_states[k]["market"] for k in signal_keys]
    x["_pit_signal_st"]=[bool(signal_states[k]["st"]) for k in signal_keys]
    x["_pit_signal_suspended"]=[bool(signal_states[k]["suspended"]) for k in signal_keys]
    exclude_st=bool((cfg.get("universe",{}) or {}).get("exclude_st",True))

    signal_st=x["_pit_signal_st"].to_numpy(dtype=bool)
    signal_suspended=x["_pit_signal_suspended"].to_numpy(dtype=bool)
    allowed_signal=~signal_suspended
    if exclude_st:
        allowed_signal &= ~signal_st
    signal_st_excluded=int(signal_st.sum()) if exclude_st else 0
    signal_suspended_excluded=int(signal_suspended.sum())
    rows_before_signal_pit=len(x)
    x=x.loc[allowed_signal].copy()
    if x.empty:
        raise RuntimeError("historical PIT policy removed all rows at signal date")

    if top_n>0:
        x["liq_rank"]=x.groupby("date")["log_amount20"].rank(method="first",ascending=False)
        x=x[x["liq_rank"]<=top_n].copy()
    if x.empty:
        raise RuntimeError("historical PIT policy has no rows after liquidity ranking")
    rows_after_liquidity_rank=len(x)

    market_dates=signal_evidence.get("market_dates") or {}
    next_by_market={}
    for market in ("SSE","SZSE","BSE"):
        days=sorted(str(d) for d in (market_dates.get(market) or []))
        if len(days)<2:
            raise RuntimeError(f"historical PIT verified calendar too short for {market}")
        next_by_market[market]={days[i]:days[i+1] for i in range(len(days)-1)}

    signal_day=pd.to_datetime(x["date"],errors="coerce").dt.strftime("%Y-%m-%d")
    actual_entry_day=pd.to_datetime(x["entry_date"],errors="coerce").dt.strftime("%Y-%m-%d")
    expected_entry_day=pd.Series(
        [next_by_market.get(m,{}).get(d) for m,d in zip(x["_pit_market"],signal_day)],
        index=x.index,dtype="object"
    )
    aligned=actual_entry_day.notna() & expected_entry_day.notna() & actual_entry_day.eq(expected_entry_day)
    entry_calendar_gap_count=int((~aligned).sum())
    x=x.loc[aligned].copy()
    expected_entry_day=expected_entry_day.loc[aligned]
    if x.empty:
        raise RuntimeError("historical PIT policy removed all rows: no true next-market-open entries")

    entry_codes=x["code"].astype(str).str.zfill(6)
    entry_keys=list(zip(expected_entry_day.tolist(),entry_codes.tolist()))
    entry_states,entry_evidence=load_historical_st_pit_subset(
        ROOT,entry_keys,expected_trade_date=expected_trade_date
    )
    if entry_evidence.get("canonical_sha256")!=signal_evidence.get("canonical_sha256"):
        raise RuntimeError("historical PIT canonical binding changed between signal and entry checks")
    entry_suspended=np.array([bool(entry_states[k]["suspended"]) for k in entry_keys],dtype=bool)
    entry_suspended_excluded=int(entry_suspended.sum())
    x=x.loc[~entry_suspended].copy()
    if x.empty:
        raise RuntimeError("historical PIT policy removed all candidates at entry execution")

    required_state_keys=len(set(signal_keys)|set(entry_keys))
    policy={
        "status":"PASS",
        "point_in_time_only":True,
        "selection_state_date":"signal_date",
        "execution_state_date":"next_market_open",
        "market_calendar_source":"verified_canonical_daily_state",
        "liquidity_ranking_after_signal_pit":True,
        "exclude_st":exclude_st,
        "rows_before_signal_pit":rows_before_signal_pit,
        "rows_after_signal_pit":rows_before_signal_pit-signal_st_excluded-signal_suspended_excluded,
        "rows_after_liquidity_rank":rows_after_liquidity_rank,
        "rows_after_entry_pit":len(x),
        "entry_calendar_gap_excluded":entry_calendar_gap_count,
        "signal_st_excluded":signal_st_excluded,
        "signal_suspended_excluded":signal_suspended_excluded,
        "entry_suspended_excluded":entry_suspended_excluded,
        "required_state_keys":required_state_keys,
        "canonical_sha256":signal_evidence.get("canonical_sha256"),
        "window_start":signal_evidence.get("window_start"),
        "window_end":signal_evidence.get("window_end"),
        "future_safety":"ST selection uses signal-date state only; next-day suspension is used only for execution feasibility",
    }
    drop=[c for c in x.columns if c.startswith("_pit_")]
    return x.drop(columns=drop),policy

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
    cfg=load_config();h=int(cfg["model"]["horizon_days"]); raw_ds=build_dataset(load_histories(),h,int(cfg["model"]["min_history_days"])); target=cfg["model"].get("target","target_excess")
    research_calendar=sorted(pd.to_datetime(raw_ds["date"],errors="coerce").dropna().unique())
    ds=raw_ds[raw_ds[target].notna()&raw_ds["target_return"].notna()].copy(); ds,pit_policy=_historical_candidate_pool(ds,cfg,research_calendar)
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
    summary={"generated_at":now_iso(),"software_version":"4.3.0-deliverable","eval_points":len(out),"mean_strategy_return":float(out.strategy_return.mean()),"mean_random_return":float(out.random_return.mean()),"mean_market_return":float(out.market_median_return.mean()),"mean_momentum_return":float(out.momentum_return.mean()),"mean_value_return":float(out.value_return.mean()) if out.value_return.notna().any() else None,"value_baseline_validated":bool(value_valid_points>0),"value_valid_points":value_valid_points,"valuation_qualification":qualification,"mean_excess_vs_random":float(out.excess_vs_random.mean()),"mean_excess_vs_market":float(out.excess_vs_market.mean()),"positive_excess_rate":float((out.excess_vs_random>0).mean()),"mean_rank_ic":float(out.rank_ic.mean()),"mean_validation_rank_ic":float(pd.to_numeric(out.validation_rank_ic,errors='coerce').mean()),"max_drawdown":_max_drawdown(out.strategy_return),"dynamic_cost_model":True,"production_model_parity":True,"model_stack":["ridge","hgb","extra_trees"],"capacity_mean_net_returns":capacity,"capacity_limit_cny":cap_limit,"entry_assumption":"信号日收盘后生成；下一交易日开盘入场；第horizon交易日收盘退出。","historical_pit_policy":pit_policy,"universe_note":"历史候选池按历史成交额门槛、流动性排名及哈希绑定的逐日ST/停牌PIT状态重建；ST筛选只使用信号日状态，次交易日停牌仅用于执行可行性，不使用今天股票池倒推。","valuation_note":"Value Baseline 仅使用估值日期<=信号日期的历史PIT缓存；资格补齐按最新合格评估日、股票代码固定顺序执行，不按收益/预测挑样本；覆盖不足时标记未验证。","model_note":"每个回测点只使用该日以前的数据，并在历史训练区内部再次使用 horizon embargo 的验证窗口学习集成权重。"}
    write_json(ROOT/"reports"/"backtest_summary.json",summary);return out,summary
