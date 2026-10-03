import sys,tempfile
from pathlib import Path
import pandas as pd,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.cost import add_live_cost_estimates,historical_roundtrip_cost_rate
from stock_ai.valuation import add_live_valuation_scores
from stock_ai.decision import decide
cfg={"cost":{"order_size_cny":100000,"commission_rate":.00025,"minimum_commission_cny":5,"stamp_duty_sell_rate":.0005,"transfer_fee_rate_each_side":.00001,"base_slippage_bps_each_side":1,"impact_coefficient_bps":100,"range_slippage_fraction":.02,"max_dynamic_slippage_bps_each_side":30},"valuation":{"enabled":True,"pe_weight":.6,"pb_weight":.4,"loss_company_score":15,"missing_score":50,"extreme_pe":100,"extreme_pb":10,"extreme_penalty_points":12,"industry_relative":True},"model":{"top_k":3},"decision":{"min_positive_net_alpha_count":2,"min_topk_mean_net_alpha":0.0,"risk_off_min_topk_mean_net_alpha":.002}}
x=pd.DataFrame({"amount":[1e8,5e8,1e7],"range20":[.02,.01,.05],"pe_dynamic":[10,30,-5],"pb":[1,3,2],"industry":["A","A","B"]})
x=add_live_cost_estimates(x,cfg);x=add_live_valuation_scores(x,cfg);assert x.loc[1,"estimated_roundtrip_cost_rate"]<x.loc[2,"estimated_roundtrip_cost_rate"];assert x.loc[0,"score_valuation"]>x.loc[1,"score_valuation"]
x["expected_net_alpha"]=[.01,.005,-.01];d=decide(x,cfg,{"regime":"NEUTRAL"},"PASS",.05);assert d["decision"]=="TRADE"
d2=decide(x,cfg,{"regime":"NEUTRAL"},"FAIL",.05);assert d2["decision"]=="NO_TRADE"
print("COST/VALUATION/DECISION TEST PASS")
