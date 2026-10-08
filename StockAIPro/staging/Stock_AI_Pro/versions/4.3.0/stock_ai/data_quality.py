
from __future__ import annotations
import pandas as pd, numpy as np
from .completed_session import validated_daily_dates, require_exact_completed_asof

def inspect_histories(histories:dict, expected_trade_date=None)->dict:
    total=len(histories); good=0; issues=[]
    latest=[]
    for code,df in histories.items():
        try:
            x=df.copy()
            dates=validated_daily_dates(x["date"])
            if expected_trade_date is not None:
                require_exact_completed_asof(dates.max().strftime("%Y-%m-%d"), expected_trade_date)
            if x["date"].duplicated().any(): issues.append({"code":code,"issue":"duplicate_dates"}); continue
            c=pd.to_numeric(x["close"],errors="coerce")
            if (expected_trade_date is not None and not np.isfinite(c.to_numpy(dtype=float)).all()) or c.isna().mean()>.01 or (c<=0).any(): issues.append({"code":code,"issue":"bad_close"}); continue
            r=c.pct_change().abs()
            if (r>0.8).sum()>2: issues.append({"code":code,"issue":"extreme_returns"}); continue
            good+=1; latest.append(pd.to_datetime(x["date"]).max())
        except Exception:
            issues.append({"code":code,"issue":"parse_error"})
    return {
        "total":total,"good":good,"good_ratio":good/max(1,total),
        "issue_count":len(issues),"issues":issues[:100],
        "latest_date":max(latest).strftime("%Y-%m-%d") if latest else None,
        "completed_session_qualification": "PASS" if expected_trade_date is not None and good==total and total else "NOT VERIFIED",
        "expected_completed_session": expected_trade_date
    }
