from __future__ import annotations
import numpy as np, pandas as pd, joblib
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor, ExtraTreesRegressor
from sklearn.metrics import mean_absolute_error
from .features import FEATURES
from .config import ROOT
from .utils import write_json, sha256_text, now_iso

MODEL_NAMES=("ridge","hgb","extra_trees")

def rank_ic(y,p):
    d=pd.DataFrame({"y":y,"p":p}).dropna()
    return float(d["y"].rank().corr(d["p"].rank())) if len(d)>=10 else float("nan")

def _ridge(model_cfg=None):
    model_cfg=model_cfg or {}
    return Pipeline([("imputer",SimpleImputer(strategy="median")),
                     ("scaler",StandardScaler()),
                     ("model",Ridge(alpha=float(model_cfg.get("ridge_alpha",8.0))))])

def _hgb(seed,model_cfg=None):
    model_cfg=model_cfg or {}
    return Pipeline([("imputer",SimpleImputer(strategy="median")),
                     ("model",HistGradientBoostingRegressor(
                         max_depth=int(model_cfg.get("hgb_max_depth",5)),
                         learning_rate=float(model_cfg.get("hgb_learning_rate",.05)),
                         max_iter=int(model_cfg.get("hgb_max_iter",260)),
                         l2_regularization=float(model_cfg.get("hgb_l2",1.0)),
                         random_state=seed))])

def _extra_trees(seed,model_cfg=None):
    model_cfg=model_cfg or {}
    return Pipeline([("imputer",SimpleImputer(strategy="median")),
                     ("model",ExtraTreesRegressor(
                         n_estimators=int(model_cfg.get("extra_trees_n_estimators",320)),
                         min_samples_leaf=int(model_cfg.get("extra_trees_min_samples_leaf",8)),
                         max_features=model_cfg.get("extra_trees_max_features",.8),
                         n_jobs=int(model_cfg.get("extra_trees_n_jobs",-1)),
                         random_state=seed))])

def fit_ensemble(train:pd.DataFrame,target_col:str="target_excess",random_state:int=42,model_cfg=None):
    model_cfg=model_cfg or {}
    y=train[target_col].astype(float)
    models={
        "ridge":_ridge(model_cfg),
        "hgb":_hgb(random_state,model_cfg),
        "extra_trees":_extra_trees(random_state+17,model_cfg),
    }
    for m in models.values(): m.fit(train[FEATURES],y)
    return models

def time_validation_split(train_all:pd.DataFrame,horizon:int,validation_days:int):
    dates=sorted(pd.to_datetime(train_all["date"]).dropna().unique())
    vd=min(int(validation_days),max(20,len(dates)//4))
    i=len(dates)-vd
    if i<=int(horizon)+40:
        raise RuntimeError("历史交易日不足以建立带 embargo 的验证集")
    valid_dates=set(dates[i:]); embargo_cutoff=dates[i-int(horizon)]
    dev=train_all[pd.to_datetime(train_all["date"])<embargo_cutoff].copy()
    valid=train_all[pd.to_datetime(train_all["date"]).isin(valid_dates)].copy()
    return dev,valid,pd.Timestamp(embargo_cutoff),pd.Timestamp(min(valid_dates))

def _model_weights(models,valid,target_col,shrinkage=.20):
    scores={}
    for name,m in models.items():
        p=m.predict(valid[FEATURES])
        ic=rank_ic(valid[target_col],p)
        scores[name]=0.0 if not np.isfinite(ic) else float(ic)
    vals=np.array([scores[k] for k in models],dtype=float)
    logits=np.clip(5*vals,-2.5,2.5)
    ex=np.exp(logits-logits.max()); dynamic=ex/ex.sum()
    shrink=float(np.clip(shrinkage,0,1)); equal=np.ones(len(models),dtype=float)/len(models)
    w=(1-shrink)*dynamic+shrink*equal
    w=w/w.sum()
    return {k:float(v) for k,v in zip(models,w)},scores

def _fixed_weights(models,chosen=None):
    names=list(models)
    if chosen:
        return {k:(1.0 if k==chosen else 0.0) for k in names}
    v=1.0/max(1,len(names)); return {k:v for k in names}

def validation_metrics(models,valid,target_col="target_excess",ensemble_mode="validation_dynamic",model_cfg=None):
    model_cfg=model_cfg or {}
    if valid.empty:return {},_fixed_weights(models)
    dynamic_weights,ics=_model_weights(models,valid,target_col,float(model_cfg.get("ensemble_shrinkage",.20)))
    mode=str(ensemble_mode or "validation_dynamic").lower()
    if mode in {"ridge_only","hgb_only","extra_trees_only"}:
        weights=_fixed_weights(models,mode.replace("_only",""))
    elif mode in {"equal","equal_ensemble"}:
        weights=_fixed_weights(models); mode="equal"
    else:
        weights=dynamic_weights; mode="validation_dynamic"
    preds={k:m.predict(valid[FEATURES]) for k,m in models.items()}
    ensemble=sum(weights[k]*preds[k] for k in models)
    return {
        "n":int(len(valid)),
        "mae":float(mean_absolute_error(valid[target_col],ensemble)),
        "rank_ic":rank_ic(valid[target_col],ensemble),
        "model_rank_ic":ics,
        "weights":weights,
        "ensemble_mode":mode,
        "dynamic_reference_weights":dynamic_weights,
        "model_names":list(models),
        "ensemble_shrinkage":float(model_cfg.get("ensemble_shrinkage",.20)),
    },weights

def train_validated_ensemble(train_all:pd.DataFrame,target_col:str,horizon:int,validation_days:int,
                             random_state:int=42,ensemble_mode="validation_dynamic",model_cfg=None,
                             max_train_rows:int|None=None):
    model_cfg=model_cfg or {}
    dev,valid,embargo_cutoff,valid_start=time_validation_split(train_all,horizon,validation_days)
    if max_train_rows:
        dev=dev.sort_values("date").tail(int(max_train_rows))
    validation_models=fit_ensemble(dev,target_col,random_state,model_cfg)
    metrics,weights=validation_metrics(validation_models,valid,target_col,ensemble_mode,model_cfg)
    final_train=train_all.sort_values("date")
    if max_train_rows:
        final_train=final_train.tail(int(max_train_rows))
    production_models=fit_ensemble(final_train,target_col,random_state,model_cfg)
    metrics.update({
        "embargo_horizon_days":int(horizon),
        "embargo_cutoff":embargo_cutoff.strftime("%Y-%m-%d"),
        "validation_start":valid_start.strftime("%Y-%m-%d"),
        "dev_rows":int(len(dev)),
        "production_train_rows":int(len(final_train)),
    })
    return production_models,weights,metrics,dev,valid,final_train

def predict_ensemble(models,frame,weights=None):
    weights=weights or _fixed_weights(models)
    out=frame.copy(); pred_cols=[]
    for name,m in models.items():
        col=f"pred_{name}"; out[col]=m.predict(frame[FEATURES]); pred_cols.append(col)
    total=sum(float(weights.get(name,0)) for name in models)
    if total<=0: weights=_fixed_weights(models); total=1.0
    out["pred"]=sum((float(weights.get(name,0))/total)*out[f"pred_{name}"] for name in models)
    arr=np.vstack([out[c].to_numpy() for c in pred_cols])
    out["model_disagreement"]=np.std(arr,axis=0)
    out["model_prediction_range"]=np.ptp(arr,axis=0)
    return out

def persist_model(models,weights,asof,metrics,cfg):
    path=ROOT/"models"/f"model_{asof}.joblib"
    bundle={"models":models,"weights":weights,"features":FEATURES,
            "asof":asof,"target":cfg["model"].get("target","target_excess"),
            "software_version":"4.3.0-deliverable"}
    joblib.dump(bundle,path)
    meta={
        "asof":asof,"created_at":now_iso(),"feature_count":len(FEATURES),
        "feature_hash":sha256_text("|".join(FEATURES)),
        "weights":weights,"metrics":metrics,"file":path.name,
        "model_names":list(models),"software_version":"4.3.0-deliverable"
    }
    write_json(ROOT/"models"/f"model_{asof}.json",meta)
    return path
