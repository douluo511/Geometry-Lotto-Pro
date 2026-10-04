
from __future__ import annotations
import numpy as np
import pandas as pd
from .features import FEATURES

def feature_drift(train: pd.DataFrame, current: pd.DataFrame, cfg: dict) -> dict:
    dc = cfg.get("drift", {}) or {}
    if not dc.get("enabled", True):
        return {"enabled": False, "status": "DISABLED", "features": []}

    rows = []
    shifted = 0
    for f in FEATURES:
        tr = pd.to_numeric(train[f], errors="coerce").replace([np.inf,-np.inf], np.nan).dropna()
        cu = pd.to_numeric(current[f], errors="coerce").replace([np.inf,-np.inf], np.nan).dropna()
        if len(tr) < 30 or len(cu) < 10:
            rows.append({"feature":f, "z_shift":None, "status":"INSUFFICIENT"})
            continue
        mean = float(tr.mean())
        std = float(tr.std())
        cur_mean = float(cu.mean())
        z = 0.0 if std <= 1e-12 else abs(cur_mean - mean) / std
        if z >= float(dc.get("fail_mean_z",1.5)):
            status = "FAIL"
            shifted += 1
        elif z >= float(dc.get("warn_mean_z",0.75)):
            status = "WARN"
            shifted += 1
        else:
            status = "PASS"
        rows.append({
            "feature":f,
            "train_mean":mean,
            "current_mean":cur_mean,
            "train_std":std,
            "z_shift":float(z),
            "status":status
        })

    usable = [r for r in rows if r["status"] != "INSUFFICIENT"]
    frac = shifted / max(1, len(usable))
    if frac >= float(dc.get("fail_fraction_shifted",0.60)):
        overall = "FAIL"
    elif frac >= float(dc.get("warn_fraction_shifted",0.30)):
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "enabled": True,
        "status": overall,
        "shifted_fraction": frac,
        "usable_features": len(usable),
        "features": rows
    }
