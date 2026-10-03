from __future__ import annotations
import numpy as np,pandas as pd
from .cost import add_live_cost_estimates
from .valuation import add_live_valuation_scores

def pct_rank(s,higher_better=True):
    x=pd.to_numeric(s,errors="coerce")
    if not higher_better:x=-x
    return x.rank(pct=True).fillna(.5)

def add_scores(pred,snapshot,cfg,regime=None,industries=None):
    x=pred.merge(snapshot,on="code",how="left",suffixes=("","_snap"))
    if industries is not None: x["industry"]=x["code"].astype(str).map(industries).fillna("未知")
    elif "industry" not in x: x["industry"]="未知"
    x=add_live_cost_estimates(x,cfg)
    x=add_live_valuation_scores(x,cfg)
    mom=.45*x["ret20"].fillna(0)+.35*x["ret60"].fillna(0)+.20*x["breakout20"].fillna(0)
    x["score_ml"]=100*pct_rank(x["pred"])
    x["score_momentum"]=100*pct_rank(mom)
    x["score_liquidity"]=100*pct_rank(x.get("amount",pd.Series(0,index=x.index)))
    risk=x["vol20"].fillna(x["vol20"].median())+.5*x["model_disagreement"].fillna(0)
    x["score_risk"]=100*pct_rank(risk,False)
    x["score_robustness"]=100*pct_rank(x["model_disagreement"],False)
    x["score_cost"]=100*pct_rank(x["estimated_roundtrip_cost_rate"],False)
    x["expected_alpha"]=pd.to_numeric(x["pred"],errors="coerce")
    x["expected_net_alpha"]=x["expected_alpha"]-x["estimated_roundtrip_cost_rate"]
    w=cfg["weights"]
    x["final_score"]=(float(w["ml"])*x["score_ml"]+float(w["momentum"])*x["score_momentum"]+
                      float(w["liquidity"])*x["score_liquidity"]+float(w["risk"])*x["score_risk"]+
                      float(w["robustness"])*x["score_robustness"]+float(w["cost"])*x["score_cost"]+
                      float(w["valuation"])*x["score_valuation"])
    completeness=x[["ret20","ret60","vol20","pred"]].notna().mean(axis=1)
    x["confidence"]=100*(.55*pct_rank(x["model_disagreement"],False)+.25*pct_rank(x["vol20"],False)+.20*completeness)
    x["signal"]="观察"
    x.loc[(x["final_score"]>=85)&(x["confidence"]>=65)&(x["expected_net_alpha"]>0),"signal"]="高优先级候选"
    x.loc[(x["final_score"]<55)|(x["expected_net_alpha"]<=0),"signal"]="低优先级"
    cols=["code","name","industry","date","close","price","final_score","confidence","signal",
          "expected_alpha","expected_net_alpha","estimated_roundtrip_cost_bps","estimated_roundtrip_cost_cny",
          "pred","pred_ridge","pred_hgb","pred_extra_trees","model_prediction_range","score_ml","score_momentum","score_liquidity","score_risk","score_robustness","score_cost","score_valuation","score_pe","score_pb","valuation_source","valuation_penalty",
          "ret5","ret20","ret60","ret120","vol20","breakout20","model_disagreement","amount","turnover_rate","spot_provider","pe_ttm","pe_dynamic","pb","market_cap"]
    cols=[c for c in cols if c in x]
    return x[cols].sort_values(["final_score","expected_net_alpha"],ascending=False).reset_index(drop=True)

def greedy_industry_select(df,n,max_per_industry,score_col="final_score"):
    chosen=[];counts={}
    for _,r in df.sort_values(score_col,ascending=False).iterrows():
        ind=str(r.get("industry","未知"))
        if counts.get(ind,0)>=max_per_industry:continue
        chosen.append(r);counts[ind]=counts.get(ind,0)+1
        if len(chosen)>=n:break
    return pd.DataFrame(chosen)

def make_portfolios(scored,cfg,regime=None):
    p=cfg["portfolio"];max_ind=int(p.get("max_per_industry",3)); cand=scored.head(max(120,int(p["balanced_size"])*6)).copy()
    balanced=cand.copy(); balanced["portfolio_score"]=.45*balanced.final_score+.20*balanced.score_valuation+.15*balanced.score_cost+.10*balanced.score_risk+.10*balanced.confidence
    balanced=greedy_industry_select(balanced,int(p["balanced_size"]),max_ind,"portfolio_score")
    offense=cand.copy(); offense["portfolio_score"]=.45*offense.final_score+.25*offense.score_momentum+.15*offense.score_ml+.15*offense.confidence
    offense=greedy_industry_select(offense,int(p["offense_size"]),max_ind,"portfolio_score")
    defense=cand.copy(); defense["portfolio_score"]=.35*defense.final_score+.25*defense.score_risk+.15*defense.score_robustness+.15*defense.score_valuation+.10*defense.score_cost
    defense=greedy_industry_select(defense,int(p["defense_size"]),max_ind,"portfolio_score")
    return {"balanced":balanced,"offense":offense,"defense":defense}
