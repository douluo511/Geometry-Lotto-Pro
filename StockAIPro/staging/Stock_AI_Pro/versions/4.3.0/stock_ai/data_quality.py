
from __future__ import annotations
import pandas as pd, numpy as np

def inspect_histories(histories:dict)->dict:
    total=len(histories); good=0; issues=[]
    latest=[]
    for code,df in histories.items():
        try:
            x=df.copy()
            if x["date"].duplicated().any(): issues.append({"code":code,"issue":"duplicate_dates"}); continue
            c=pd.to_numeric(x["close"],errors="coerce")
            if c.isna().mean()>.01 or (c<=0).any(): issues.append({"code":code,"issue":"bad_close"}); continue
            r=c.pct_change().abs()
            if (r>0.8).sum()>2: issues.append({"code":code,"issue":"extreme_returns"}); continue
            good+=1; latest.append(pd.to_datetime(x["date"]).max())
        except Exception:
            issues.append({"code":code,"issue":"parse_error"})
    return {
        "total":total,"good":good,"good_ratio":good/max(1,total),
        "issue_count":len(issues),"issues":issues[:100],
        "latest_date":max(latest).strftime("%Y-%m-%d") if latest else None
    }
