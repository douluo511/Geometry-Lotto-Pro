from __future__ import annotations
import numpy as np

def decide(scored,cfg,regime,drift_status="PASS",model_rank_ic=None):
    dc=cfg.get("decision",{}) or {}; topk=int(cfg.get("model",{}).get("top_k",20)); top=scored.head(topk)
    mean_net=float(top["expected_net_alpha"].mean()) if len(top) and "expected_net_alpha" in top else float("nan")
    positive=int((top.get("expected_net_alpha",0)>0).sum()) if len(top) else 0
    trust="HIGH"
    reasons=[]
    if drift_status=="FAIL": trust="LOW"; reasons.append("特征漂移FAIL")
    elif drift_status=="WARN": trust="MEDIUM"; reasons.append("特征漂移WARN")
    if model_rank_ic is None or not np.isfinite(model_rank_ic): trust="MEDIUM" if trust!="LOW" else trust; reasons.append("验证Rank IC不可用")
    elif model_rank_ic<0: trust="LOW"; reasons.append("验证Rank IC为负")
    elif model_rank_ic<.02 and trust=="HIGH": trust="MEDIUM"; reasons.append("验证Rank IC偏弱")
    if positive<int(dc.get("min_positive_net_alpha_count",5)): reasons.append("正Net Alpha候选不足")
    threshold=float(dc.get("min_topk_mean_net_alpha",0.0)); reg=str((regime or {}).get("regime","NEUTRAL"))
    if reg=="RISK_OFF": threshold=max(threshold,float(dc.get("risk_off_min_topk_mean_net_alpha",.002)))
    if trust=="LOW" or not np.isfinite(mean_net) or mean_net<threshold or positive<int(dc.get("min_positive_net_alpha_count",5)):
        status="NO_TRADE"
    elif trust=="MEDIUM": status="WATCH"
    else: status="TRADE"
    return {"decision":status,"model_trust":trust,"topk_mean_expected_net_alpha":mean_net,"positive_net_alpha_count":positive,"threshold":threshold,"reasons":reasons}
