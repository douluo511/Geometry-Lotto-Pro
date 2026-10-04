
from __future__ import annotations
import numpy as np, pandas as pd, joblib
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from .features import FEATURES
from .config import ROOT
from .utils import write_json, sha256_text, now_iso

def rank_ic(y,p):
    d=pd.DataFrame({"y":y,"p":p}).dropna()
    return float(d["y"].rank().corr(d["p"].rank())) if len(d)>=10 else float("nan")

def _ridge():
    return Pipeline([("imputer",SimpleImputer(strategy="median")),
                     ("scaler",StandardScaler()),("model",Ridge(alpha=8.0))])

def _hgb(seed):
    return Pipeline([("imputer",SimpleImputer(strategy="median")),
                     ("model",HistGradientBoostingRegressor(
                         max_depth=5,learning_rate=.05,max_iter=220,
                         l2_regularization=1.0,random_state=seed))])

def fit_ensemble(train:pd.DataFrame,target_col:str="target_excess",random_state:int=42):
    y=train[target_col].astype(float)
    models={"ridge":_ridge(),"hgb":_hgb(random_state)}
    for m in models.values(): m.fit(train[FEATURES],y)
    return models

def _model_weights(models,valid,target_col):
    scores={}
    for name,m in models.items():
        p=m.predict(valid[FEATURES])
        ic=rank_ic(valid[target_col],p)
        scores[name]=0.0 if not np.isfinite(ic) else ic
    vals=np.array([scores[k] for k in models],dtype=float)
    # 温和动态权重：负IC仍保留小权重，避免单窗口过拟合
    logits=np.clip(4*vals,-2,2)
    ex=np.exp(logits-logits.max())
    w=ex/ex.sum()
    return {k:float(v) for k,v in zip(models,w)},scores

def validation_metrics(models,valid,target_col="target_excess",ensemble_mode="validation_dynamic"):
    if valid.empty:return {},{"ridge":.5,"hgb":.5}
    dynamic_weights,ics=_model_weights(models,valid,target_col)
    mode=str(ensemble_mode or "validation_dynamic").lower()
    if mode=="ridge_only": weights={"ridge":1.0,"hgb":0.0}
    elif mode=="hgb_only": weights={"ridge":0.0,"hgb":1.0}
    elif mode in {"equal","equal_ensemble"}: weights={"ridge":.5,"hgb":.5}
    else: weights=dynamic_weights; mode="validation_dynamic"
    preds={k:m.predict(valid[FEATURES]) for k,m in models.items()}
    ensemble=sum(weights[k]*preds[k] for k in models)
    return {
        "n":int(len(valid)),
        "mae":float(mean_absolute_error(valid[target_col],ensemble)),
        "rank_ic":rank_ic(valid[target_col],ensemble),
        "model_rank_ic":ics,
        "weights":weights,"ensemble_mode":mode,"dynamic_reference_weights":dynamic_weights
    },weights

def predict_ensemble(models,frame,weights=None):
    weights=weights or {"ridge":.5,"hgb":.5}
    out=frame.copy()
    pred_cols=[]
    for name,m in models.items():
        col=f"pred_{name}"
        out[col]=m.predict(frame[FEATURES]); pred_cols.append(col)
    out["pred"]=sum(float(weights.get(name,0))*out[f"pred_{name}"] for name in models)
    arr=np.vstack([out[c].to_numpy() for c in pred_cols])
    out["model_disagreement"]=np.std(arr,axis=0)
    return out

def persist_model(models,weights,asof,metrics,cfg):
    path=ROOT/"models"/f"model_{asof}.joblib"
    bundle={"models":models,"weights":weights,"features":FEATURES,
            "asof":asof,"target":cfg["model"].get("target","target_excess")}
    joblib.dump(bundle,path)
    meta={
        "asof":asof,"created_at":now_iso(),"feature_count":len(FEATURES),
        "feature_hash":sha256_text("|".join(FEATURES)),
        "weights":weights,"metrics":metrics,"file":path.name
    }
    write_json(ROOT/"models"/f"model_{asof}.json",meta)
    return path
