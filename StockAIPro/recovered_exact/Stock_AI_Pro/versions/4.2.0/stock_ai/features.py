
from __future__ import annotations
import numpy as np
import pandas as pd

FEATURES = [
    "ret1","ret5","ret10","ret20","ret60","ret120",
    "ma5_ratio","ma20_ratio","ma60_ratio","ma120_ratio",
    "vol20","vol60","volume_z20","amount_z20","log_amount20",
    "drawdown60","breakout20","range20"
]
EXECUTION_COLUMNS = ["entry_open","entry_high","entry_low","signal_close"]

def _zscore(s: pd.Series, w: int) -> pd.Series:
    m = s.rolling(w).mean()
    sd = s.rolling(w).std().replace(0, np.nan)
    return (s-m)/sd

def make_features(df:pd.DataFrame,horizon:int=5)->pd.DataFrame:
    x = df.copy().sort_values("date")
    c = pd.to_numeric(x["close"], errors="coerce")
    o = pd.to_numeric(x["open"], errors="coerce") if "open" in x else c
    hprice = pd.to_numeric(x["high"], errors="coerce") if "high" in x else c
    lprice = pd.to_numeric(x["low"], errors="coerce") if "low" in x else c

    for w in [1,5,10,20,60,120]:
        x[f"ret{w}"] = c.pct_change(w)
    for w in [5,20,60,120]:
        x[f"ma{w}_ratio"] = c/c.rolling(w).mean()-1

    x["vol20"] = x["ret1"].rolling(20).std()
    x["vol60"] = x["ret1"].rolling(60).std()

    volume = pd.to_numeric(x.get("volume", np.nan), errors="coerce")
    amount = pd.to_numeric(x.get("amount", np.nan), errors="coerce")
    x["volume_z20"] = _zscore(volume,20) if isinstance(volume,pd.Series) else np.nan
    x["amount_z20"] = _zscore(amount,20) if isinstance(amount,pd.Series) else np.nan
    x["log_amount20"] = (
        np.log1p(amount.rolling(20).mean().clip(lower=0))
        if isinstance(amount,pd.Series) else np.nan
    )

    x["drawdown60"] = c/c.rolling(60).max()-1
    x["breakout20"] = c/hprice.rolling(20).max().shift(1)-1
    x["range20"] = ((hprice-lprice)/c).rolling(20).mean()

    # Signal at t close; realistic research entry is t+1 open.
    x["signal_close"] = c
    x["entry_open"] = o.shift(-1)
    x["entry_high"] = hprice.shift(-1)
    x["entry_low"] = lprice.shift(-1)
    exit_close = c.shift(-horizon)
    x["target_return"] = exit_close/x["entry_open"] - 1
    return x

def build_dataset(histories:dict[str,pd.DataFrame],horizon:int,min_history_days:int=240)->pd.DataFrame:
    parts = []
    for code,df in histories.items():
        if len(df) < min_history_days:
            continue
        f = make_features(df,horizon)
        f["code"] = str(code)
        keep = ["date","code","close","target_return"] + EXECUTION_COLUMNS + FEATURES
        parts.append(f[keep])

    if not parts:
        return pd.DataFrame()

    ds = pd.concat(parts,ignore_index=True).sort_values(["date","code"])
    med = ds.groupby("date")["target_return"].transform("median")
    ds["target_excess"] = ds["target_return"] - med
    ds["target_rank"] = ds.groupby("date")["target_return"].rank(pct=True)
    return ds
