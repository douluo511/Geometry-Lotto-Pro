import sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.features import build_dataset,FEATURES
from stock_ai.model import fit_ensemble,predict_ensemble,validation_metrics
from stock_ai.regime import detect_market_regime
from stock_ai.scoring import add_scores,make_portfolios
from stock_ai.decision import decide

def synthetic(code,n=420,seed=1):
    rng=np.random.default_rng(seed);d=pd.bdate_range("2023-01-02",periods=n);r=rng.normal(.0003,.014,n);c=20*np.exp(np.cumsum(r))
    return pd.DataFrame({"date":d,"code":code,"open":c*(1+rng.normal(0,.002,n)),"close":c,"high":c*(1+rng.uniform(0,.02,n)),"low":c*(1-rng.uniform(0,.02,n)),"volume":rng.integers(1_000_000,20_000_000,n),"amount":rng.integers(2e7,5e8,n)})
hist={f"{i:06d}":synthetic(f"{i:06d}",420,i+1) for i in range(1,61)};ds=build_dataset(hist,5,240);target="target_excess";train=ds[ds[target].notna()];dates=sorted(train.date.unique());tr=train[train.date<dates[-40]];va=train[train.date>=dates[-40]]
models=fit_ensemble(tr,target,42);metrics,w=validation_metrics(models,va,target);cur=ds[ds.date==ds.date.max()].copy();pred=predict_ensemble(models,cur,w)
snap=pd.DataFrame({"code":list(hist),"name":[f"测试{i}" for i in range(len(hist))],"price":[10.]*len(hist),"pct_chg":[.1]*len(hist),"amount":np.linspace(1e8,4e8,len(hist)),"turnover_rate":[.02]*len(hist),"pe_dynamic":np.linspace(10,40,len(hist)),"pb":np.linspace(1,5,len(hist)),"market_cap":[1e10]*len(hist),"spot_provider":["eastmoney"]*len(hist)})
cfg={"weights":{"ml":.32,"momentum":.15,"liquidity":.07,"risk":.08,"robustness":.08,"cost":.12,"valuation":.18},"portfolio":{"balanced_size":20,"offense_size":15,"defense_size":20,"max_per_industry":4},"model":{"top_k":20},"cost":{"order_size_cny":100000,"commission_rate":.00025,"minimum_commission_cny":5,"stamp_duty_sell_rate":.0005,"transfer_fee_rate_each_side":.00001,"base_slippage_bps_each_side":1,"impact_coefficient_bps":100,"range_slippage_fraction":.02,"max_dynamic_slippage_bps_each_side":30},"valuation":{"enabled":True,"pe_weight":.6,"pb_weight":.4,"loss_company_score":15,"missing_score":50,"extreme_pe":100,"extreme_pb":10,"extreme_penalty_points":12,"industry_relative":True},"decision":{"min_positive_net_alpha_count":0,"min_topk_mean_net_alpha":-1,"risk_off_min_topk_mean_net_alpha":-1}}
industries={c:f"I{i%8}" for i,c in enumerate(hist)};reg=detect_market_regime(cur,snap);sc=add_scores(pred,snap,cfg,reg,industries);ports=make_portfolios(sc,cfg,reg);dec=decide(sc,cfg,reg,"PASS",metrics.get("rank_ic"))
assert len(sc)==60 and sc.final_score.between(0,100).all();assert {"score_cost","score_valuation","expected_net_alpha"}<=set(sc);assert len(ports["balanced"])==20;assert dec["decision"] in {"TRADE","WATCH","NO_TRADE"};assert not {"target_return","target_excess","entry_open"}&set(FEATURES)
print("SELF TEST PASS")
