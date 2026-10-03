
from __future__ import annotations
import numpy as np, pandas as pd

def detect_market_regime(current_features:pd.DataFrame,snapshot:pd.DataFrame)->dict:
    x=current_features.copy()
    ret20=pd.to_numeric(x.get("ret20"),errors="coerce")
    vol20=pd.to_numeric(x.get("vol20"),errors="coerce")
    breadth20=float((ret20>0).mean()) if len(ret20.dropna()) else .5
    med20=float(ret20.median()) if len(ret20.dropna()) else 0.0
    medvol=float(vol20.median()) if len(vol20.dropna()) else 0.0
    pct=pd.to_numeric(snapshot.get("pct_chg"),errors="coerce") if "pct_chg" in snapshot else pd.Series(dtype=float)
    breadth_day=float((pct>0).mean()) if len(pct.dropna()) else .5
    raw=50+35*(breadth20-.5)+300*med20+15*(breadth_day-.5)
    score=float(np.clip(raw,0,100))
    if score>=62 and med20>0: regime="RISK_ON"
    elif score<=38 or med20<-0.03: regime="RISK_OFF"
    else: regime="NEUTRAL"
    return {
        "regime":regime,"score":round(score,2),"breadth20":round(breadth20,4),
        "median_ret20":round(med20,6),"daily_breadth":round(breadth_day,4),
        "median_vol20":round(medvol,6)
    }
