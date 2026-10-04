from __future__ import annotations
import numpy as np,pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from .config import ROOT,load_config
from .data_source import load_histories
from .features import build_dataset,FEATURES
from .model import rank_ic
from .utils import write_json,now_iso
from .cost import historical_roundtrip_cost_rate
from .valuation import merge_historical_valuation,add_historical_valuation_score

def _model(): return Pipeline([("imputer",SimpleImputer(strategy="median")),("scaler",StandardScaler()),("model",Ridge(alpha=8.0))])
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
    # PIT valuation only. Missing coverage is allowed but never silently filled with current valuation.
    ds=merge_historical_valuation(ds); ds=add_historical_valuation_score(ds,cfg)
    dates=sorted(ds["date"].unique()); lookback=int(cfg["backtest"]["lookback_eval_days"]); step=int(cfg["backtest"]["rebalance_every_days"]); eval_dates=dates[-lookback::step]; topk=int(cfg["model"]["top_k"])
    trials=int(cfg["backtest"]["random_trials"]);rng=np.random.default_rng(int(cfg["model"]["random_state"])); min_test=int(cfg["backtest"].get("min_test_universe",50)); min_train=int(cfg["backtest"].get("min_train_rows",5000)); rows=[]
    cap_sizes=[int(x) for x in cfg["backtest"].get("capacity_order_sizes_cny",[100000,500000,1000000,5000000,10000000])]
    value_min=float(cfg.get("valuation",{}).get("backtest_min_coverage",.4)); value_valid_points=0
    for d in eval_dates:
        pos=dates.index(d)
        if pos<160 or pos-h<0:continue
        cutoff=dates[pos-h];train=ds[ds["date"]<cutoff].copy();test=ds[ds["date"]==d].copy();test=test[test.apply(_tradable_next_open,axis=1)]
        if len(train)<min_train or len(test)<max(topk,min_test):continue
        train=train.sort_values("date").tail(120000);m=_model();m.fit(train[FEATURES],train[target]);test["pred"]=m.predict(test[FEATURES]);top=test.sort_values("pred",ascending=False).head(topk)
        strat=_net_mean(top,cfg); market=float(test["target_return"].median()); momset=test.sort_values("ret20",ascending=False).head(topk);momentum=_net_mean(momset,cfg)
        vals=[]
        for _ in range(trials):
            sample=test.iloc[rng.choice(len(test),size=topk,replace=False)];vals.append(_net_mean(sample,cfg))
        rnd=float(np.mean(vals)); val_cov=float(test[["pe_ttm_hist","pb_hist"]].notna().any(axis=1).mean())
        value=float('nan')
        if val_cov>=value_min:
            value_valid_points+=1; value=_net_mean(test.sort_values("score_valuation_hist",ascending=False).head(topk),cfg)
        row={"date":pd.Timestamp(d).strftime("%Y-%m-%d"),"strategy_return":strat,"market_median_return":market,"random_return":rnd,"momentum_return":momentum,"value_return":value,"valuation_coverage":val_cov,"excess_vs_market":strat-market,"excess_vs_random":strat-rnd,"rank_ic":rank_ic(test[target],test["pred"]),"universe_n":len(test),"entry_assumption":"next_open"}
        for size in cap_sizes: row[f"strategy_return_cap_{size}"]=_net_mean(top,cfg,size)
        rows.append(row)
    out=pd.DataFrame(rows)
    if out.empty:raise RuntimeError("回测没有有效评估点；研究历史池可能尚未补齐")
    for col,name in [("strategy_return","equity"),("random_return","random_equity"),("momentum_return","momentum_equity")]:out[name]=(1+out[col].fillna(0)).cumprod()
    if out["value_return"].notna().any():out["value_equity"]=(1+out["value_return"].fillna(0)).cumprod()
    out.to_csv(ROOT/"reports"/"backtest.csv",index=False,encoding="utf-8-sig")
    capacity={str(size):float(out[f"strategy_return_cap_{size}"].mean()) for size in cap_sizes}; base=capacity.get(str(cap_sizes[0]),float('nan')); cap_limit=max([s for s in cap_sizes if np.isfinite(capacity[str(s)]) and (not np.isfinite(base) or capacity[str(s)]>0)],default=0)
    summary={"generated_at":now_iso(),"eval_points":len(out),"mean_strategy_return":float(out.strategy_return.mean()),"mean_random_return":float(out.random_return.mean()),"mean_market_return":float(out.market_median_return.mean()),"mean_momentum_return":float(out.momentum_return.mean()),"mean_value_return":float(out.value_return.mean()) if out.value_return.notna().any() else None,"value_baseline_validated":bool(value_valid_points>0),"value_valid_points":value_valid_points,"mean_excess_vs_random":float(out.excess_vs_random.mean()),"mean_excess_vs_market":float(out.excess_vs_market.mean()),"positive_excess_rate":float((out.excess_vs_random>0).mean()),"mean_rank_ic":float(out.rank_ic.mean()),"max_drawdown":_max_drawdown(out.strategy_return),"dynamic_cost_model":True,"capacity_mean_net_returns":capacity,"capacity_limit_cny":cap_limit,"entry_assumption":"信号日收盘后生成；下一交易日开盘入场；第horizon交易日收盘退出。","universe_note":"历史候选池按历史成交额门槛及流动性排名重建，不使用今天股票池倒推。","valuation_note":"Value Baseline 仅使用估值日期<=信号日期的历史PIT缓存；覆盖不足时标记未验证。"}
    write_json(ROOT/"reports"/"backtest_summary.json",summary);return out,summary
