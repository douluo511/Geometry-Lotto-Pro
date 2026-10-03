from __future__ import annotations
import numpy as np, pandas as pd

def _c(cfg): return cfg.get("cost",{}) or {}

def explicit_roundtrip_cost_rate(cfg:dict, order_size_cny=None)->float:
    c=_c(cfg); order=max(float(order_size_cny or c.get("order_size_cny",100000)),1.0)
    comm=max(float(c.get("commission_rate",.00025)),0.0)
    minc=max(float(c.get("minimum_commission_cny",5.0)),0.0)
    one=max(order*comm,minc)/order
    transfer=max(float(c.get("transfer_fee_rate_each_side",.00001)),0.0)
    stamp=max(float(c.get("stamp_duty_sell_rate",.0005)),0.0)
    return 2*one+2*transfer+stamp

def _dynamic_slippage_rate(amount,range20,cfg,order_size_cny=None):
    c=_c(cfg); order=max(float(order_size_cny or c.get("order_size_cny",100000)),1.0)
    base=max(float(c.get("base_slippage_bps_each_side",1.0)),0.0)
    impact=max(float(c.get("impact_coefficient_bps",100.0)),0.0)
    rf=max(float(c.get("range_slippage_fraction",.02)),0.0)
    cap=max(float(c.get("max_dynamic_slippage_bps_each_side",30.0)),0.0)
    a=pd.to_numeric(amount,errors="coerce").fillna(order).clip(lower=order)
    r=pd.to_numeric(range20,errors="coerce").fillna(0).clip(lower=0)
    one_side=(base+impact*np.sqrt(order/a)+r*10000*rf).clip(upper=cap)
    return 2*one_side/10000

def add_live_cost_estimates(frame:pd.DataFrame,cfg:dict)->pd.DataFrame:
    x=frame.copy(); order=float(_c(cfg).get("order_size_cny",100000))
    explicit=explicit_roundtrip_cost_rate(cfg,order)
    dynamic=_dynamic_slippage_rate(x.get("amount",pd.Series(index=x.index,dtype=float)),x.get("range20",pd.Series(index=x.index,dtype=float)),cfg,order)
    x["explicit_cost_rate"]=explicit; x["dynamic_slippage_rate"]=dynamic
    x["estimated_roundtrip_cost_rate"]=explicit+dynamic
    x["estimated_roundtrip_cost_bps"]=x["estimated_roundtrip_cost_rate"]*10000
    x["estimated_roundtrip_cost_cny"]=x["estimated_roundtrip_cost_rate"]*order
    return x

def historical_roundtrip_cost_rate(frame:pd.DataFrame,cfg:dict,order_size_cny=None)->pd.Series:
    if "log_amount20" in frame:
        amount=np.expm1(pd.to_numeric(frame["log_amount20"],errors="coerce"))
    else: amount=pd.Series(index=frame.index,dtype=float)
    r=frame.get("range20",pd.Series(index=frame.index,dtype=float))
    return explicit_roundtrip_cost_rate(cfg,order_size_cny)+_dynamic_slippage_rate(amount,r,cfg,order_size_cny)
