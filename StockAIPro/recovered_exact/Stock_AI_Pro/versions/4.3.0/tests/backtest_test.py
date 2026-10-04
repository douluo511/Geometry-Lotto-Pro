
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.backtest as bt

def synthetic(code,n=520,seed=1):
    rng=np.random.default_rng(seed);d=pd.bdate_range("2022-01-03",periods=n)
    r=rng.normal(.0003,.012,n);c=15*np.exp(np.cumsum(r))
    op=c*(1+rng.normal(0,.003,n));hi=np.maximum(op,c)*(1+rng.uniform(0,.01,n))
    lo=np.minimum(op,c)*(1-rng.uniform(0,.01,n))
    return pd.DataFrame({"date":d,"code":code,"open":op,"close":c,"high":hi,"low":lo,
      "volume":rng.integers(1e6,2e7,n),"amount":rng.integers(3e7,5e8,n),"adjust_mode":"hfq"})
hist={f"{i:06d}":synthetic(f"{i:06d}",520,i+10) for i in range(1,101)}
cfg={"universe":{"min_turnover_cny":2e7,"live_top_n":80},
     "model":{"horizon_days":5,"min_history_days":240,"validation_days":30,"top_k":10,"random_state":42,"target":"target_excess","ensemble_mode":"validation_dynamic","extra_trees_n_estimators":30,"extra_trees_min_samples_leaf":4,"hgb_max_iter":60,"ensemble_shrinkage":.2},
     "backtest":{"lookback_eval_days":60,"rebalance_every_days":5,"random_trials":10,"min_test_universe":30,"min_train_rows":3000,"max_eval_points":6,"max_train_rows":25000,"capacity_order_sizes_cny":[100000,500000]},
     "cost":{"order_size_cny":100000,"commission_rate":.00025,"minimum_commission_cny":5,"stamp_duty_sell_rate":.0005,"transfer_fee_rate_each_side":.00001,"base_slippage_bps_each_side":1,"impact_coefficient_bps":100,"range_slippage_fraction":.02,"max_dynamic_slippage_bps_each_side":30},
     "valuation":{"backtest_min_coverage":.4,"loss_company_score":15,"missing_score":50,"pe_weight":.6,"pb_weight":.4}}
with tempfile.TemporaryDirectory() as td:
    tmp=Path(td);(tmp/"reports").mkdir()
    with patch.object(bt,"ROOT",tmp),patch.object(bt,"load_config",return_value=cfg),patch.object(bt,"load_histories",return_value=hist),patch.object(bt,"merge_historical_valuation",side_effect=lambda x:x.assign(pe_ttm_hist=np.nan,pb_hist=np.nan,valuation_date=pd.NaT)):
        out,summary=bt.run_backtest()
assert not out.empty
assert (out["entry_assumption"]=="next_open").all()
assert summary["eval_points"]>0
assert summary["production_model_parity"] is True and "extra_trees" in summary["model_stack"]
assert "model_weights" in out.columns
assert "下一交易日开盘" in summary["entry_assumption"]
print("BACKTEST EXECUTION TEST PASS",summary["eval_points"])
