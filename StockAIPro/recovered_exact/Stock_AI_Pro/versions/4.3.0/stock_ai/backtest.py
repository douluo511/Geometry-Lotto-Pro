from __future__ import annotations
import json
import numpy as np,pandas as pd
from .config import ROOT,load_config
from .data_source import load_histories
from .features import build_dataset
from .model import rank_ic,train_validated_ensemble,predict_ensemble
from .utils import write_json,now_iso
from .cost import historical_roundtrip_cost_rate
from .valuation import merge_historical_valuation,add_historical_valuation_score

def _max_drawdown(returns):
    eq=(1+pd.Series(returns).fillna(0)).cumprod(); return float((eq/eq.cummax()-1).min())
def _limit_pct(code): return .20 if str(code).startswith(("300","301","688")) else .10
def _tradable_next_open(row):
    try:
        prev=float(row["signal_close"]);low=float(row["entry_low"]);op=float(row["entry_open"])
        if not np.isfinite(prev) or not np.isfinite(low) or not np.isfinite(op) or prev<=0:return False
        return low<prev*(1+_limit_pct(row["code"])*.985)
    except Exception:return False

def _historical_candidate_pool(ds,cfg):
    min_amt=float(cfg["universe"].get("min_turnover_cny",0)); top_n=int(cfg["universe"].get("live_top_n",300)); x=ds[ds["log_amount20"].notna()].copy()
    if min_amt>0:x=x[x["log_amount20"]>=np.log1p(min_amt)]
    if top_n>0 and not x.empty:
        x["liq_rank"]=x.groupby("date")["log_amount20"].rank(method="first",ascending=False);x=x[x["liq_rank"]<=top_n]
    return x

def _net_mean(frame,cfg,order_size=None):
    if frame.empty:return float('nan')
    return float((frame["target_return"]-historical_roundtrip_cost_rate(frame,cfg,order_size)).mean())

def run_backtest():
    cfg=load_config();h=int(cfg["model"]["horizon_days"]); ds=build_dataset(load_histories(),h,int(cfg["model"]["min_history_days"])); target=cfg["model"].get("target","target_excess")
    ds=ds[ds[target].notna()&ds["target_return"].notna()].copy(); ds=_historical_candidate_pool(ds,cfg)
    if ds.empty:raise RuntimeError("没有可回测数据")
    ds=merge_historical_valuation(ds); ds=add_historical_valuation_score(ds,cfg)
    dates=sorted(ds["date"].unique()); lookback=int(cfg["backtest"]["lookback_eval_days"]); step=int(cfg["backtest"]["rebalance_every_days"]); eval_dates=dates[-lookback::step]
    max_eval=int(cfg["backtest"].get("max_eval_points",24) or 0)
    if max_eval>0 and len(eval_dates)>max_eval: eval_dates=eval_dates[-max_eval:]
    topk=int(cfg["model"]["top_k"]);trials=int(cfg["backtest"]["random_trials"]);rng=np.random.default_rng(int(cfg["model"]["random_state"])); min_test=int(cfg["backtest"].get("min_test_universe",50)); min_train=int(cfg["backtest"].get("min_train_rows",5000)); rows=[]
    cap_sizes=[int(x) for x in cfg["backtest"].get("capacity_order_sizes_cny",[100000,500000,1000000,5000000,10000000])]
    value_min=float(cfg.get("valuation",{}).get("backtest_min_coverage",.4)); value_valid_points=0
    model_max_rows=int(cfg["backtest"].get("max_train_rows",80000))
    validation_days=int(cfg["model"].get("validation_days",40))
    ensemble_mode=cfg["model"].get("ensemble_mode","validation_dynamic")
    for d in eval_dates:
        pos=dates.index(d)
        if pos<160 or pos-h<0:continue
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
    summary={"generated_at":now_iso(),"software_version":"4.3.0-deliverable","eval_points":len(out),"mean_strategy_return":float(out.strategy_return.mean()),"mean_random_return":float(out.random_return.mean()),"mean_market_return":float(out.market_median_return.mean()),"mean_momentum_return":float(out.momentum_return.mean()),"mean_value_return":float(out.value_return.mean()) if out.value_return.notna().any() else None,"value_baseline_validated":bool(value_valid_points>0),"value_valid_points":value_valid_points,"mean_excess_vs_random":float(out.excess_vs_random.mean()),"mean_excess_vs_market":float(out.excess_vs_market.mean()),"positive_excess_rate":float((out.excess_vs_random>0).mean()),"mean_rank_ic":float(out.rank_ic.mean()),"mean_validation_rank_ic":float(pd.to_numeric(out.validation_rank_ic,errors='coerce').mean()),"max_drawdown":_max_drawdown(out.strategy_return),"dynamic_cost_model":True,"production_model_parity":True,"model_stack":["ridge","hgb","extra_trees"],"capacity_mean_net_returns":capacity,"capacity_limit_cny":cap_limit,"entry_assumption":"信号日收盘后生成；下一交易日开盘入场；第horizon交易日收盘退出。","universe_note":"历史候选池按历史成交额门槛及流动性排名重建，不使用今天股票池倒推。","valuation_note":"Value Baseline 仅使用估值日期<=信号日期的历史PIT缓存；覆盖不足时标记未验证。","model_note":"每个回测点只使用该日以前的数据，并在历史训练区内部再次使用 horizon embargo 的验证窗口学习集成权重。"}
    write_json(ROOT/"reports"/"backtest_summary.json",summary);return out,summary
