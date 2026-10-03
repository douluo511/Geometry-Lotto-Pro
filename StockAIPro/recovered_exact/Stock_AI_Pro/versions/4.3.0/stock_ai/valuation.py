from __future__ import annotations
from datetime import datetime,timedelta
import time, numpy as np, pandas as pd
from .config import ROOT
from .utils import write_json,now_iso

def _ak():
    try:
        import akshare as ak; return ak
    except Exception as e: raise RuntimeError("AkShare 未安装") from e

def _cheap_score(s,loss_score=15.0,missing_score=50.0):
    x=pd.to_numeric(s,errors="coerce"); out=pd.Series(float(missing_score),index=x.index,dtype=float)
    valid=x>0
    if valid.any(): out.loc[valid]=100*(-x.loc[valid]).rank(pct=True)
    out.loc[x.notna()&(x<=0)]=float(loss_score)
    return out.clip(0,100)

def add_live_valuation_scores(frame:pd.DataFrame,cfg:dict)->pd.DataFrame:
    x=frame.copy(); vc=cfg.get("valuation",{}) or {}
    if not vc.get("enabled",True): x["score_valuation"]=50.; return x
    pe=pd.to_numeric(x.get("pe_ttm",x.get("pe_dynamic",pd.Series(index=x.index,dtype=float))),errors="coerce")
    pb=pd.to_numeric(x.get("pb",pd.Series(index=x.index,dtype=float)),errors="coerce")
    loss=float(vc.get("loss_company_score",15)); missing=float(vc.get("missing_score",50))
    x["score_pe"]=_cheap_score(pe,loss,missing); x["score_pb"]=_cheap_score(pb,loss,missing)
    pw=float(vc.get("pe_weight",.6)); bw=float(vc.get("pb_weight",.4)); den=max(pw+bw,1e-9)
    x["score_valuation_global"]=(pw*x.score_pe+bw*x.score_pb)/den
    x["score_valuation_industry"]=50.
    if vc.get("industry_relative",True) and "industry" in x:
        rels=[]
        for vals in (pe,pb):
            med=vals.where(vals>0).groupby(x["industry"].fillna("未知")).transform("median")
            rels.append(_cheap_score(vals/med,loss,missing))
        x["score_valuation_industry"]=(rels[0]+rels[1])/2
    x["valuation_penalty"]=(pe>float(vc.get("extreme_pe",100))).fillna(False).astype(float)*float(vc.get("extreme_penalty_points",12))
    x["valuation_penalty"]+=(pb>float(vc.get("extreme_pb",10))).fillna(False).astype(float)*float(vc.get("extreme_penalty_points",12))
    x["score_valuation"]=(.7*x.score_valuation_global+.3*x.score_valuation_industry-x.valuation_penalty).clip(0,100)
    x["valuation_source"]=np.where(pd.to_numeric(x.get("pe_ttm"),errors="coerce").notna(),"PE_TTM",np.where(pe.notna(),"PE_DYNAMIC_FALLBACK","MISSING")) if "pe_ttm" in x else np.where(pe.notna(),"PE_DYNAMIC_FALLBACK","MISSING")
    return x

def _indicator_col(ind): return {"市盈率(TTM)":"pe_ttm","市净率":"pb","市现率":"pcf","总市值":"market_cap"}.get(ind,ind)

def _read(code):
    p=ROOT/"data"/"valuation"/f"{code}.csv"
    if not p.exists(): return pd.DataFrame()
    try: return pd.read_csv(p,parse_dates=["date"],dtype={"code":str})
    except Exception:return pd.DataFrame()

def update_valuation_history(code,cfg,logger=None):
    vc=cfg.get("valuation",{}) or {}; ak=_ak(); merged=None; errs=[]
    for ind in vc.get("history_indicators",["市盈率(TTM)","市净率"]):
        try:
            raw=ak.stock_zh_valuation_baidu(symbol=str(code),indicator=ind,period=str(vc.get("history_period","全部")))
            if raw is None or raw.empty: continue
            part=raw.rename(columns={"value":_indicator_col(ind)}).copy(); part["date"]=pd.to_datetime(part["date"],errors="coerce")
            part=part[["date",_indicator_col(ind)]].dropna(subset=["date"])
            merged=part if merged is None else merged.merge(part,on="date",how="outer")
        except Exception as e: errs.append(f"{ind}: {e}")
    if merged is None or merged.empty:
        old=_read(code)
        if not old.empty:return old
        raise RuntimeError("估值历史获取失败: "+" | ".join(errs))
    merged["code"]=str(code); merged["valuation_date"]=merged["date"]; merged["retrieved_at"]=now_iso()
    merged=merged.sort_values("date").drop_duplicates("date",keep="last")
    out=ROOT/"data"/"valuation"/f"{code}.csv"; out.parent.mkdir(parents=True,exist_ok=True); tmp=out.with_suffix('.csv.tmp')
    merged.to_csv(tmp,index=False,encoding='utf-8-sig'); tmp.replace(out); return merged

def refresh_valuation_histories(codes,cfg,logger=None):
    vc=cfg.get("valuation",{}) or {}
    if not vc.get("enabled",True): return {"enabled":False,"coverage":0}
    folder=ROOT/"data"/"valuation"; folder.mkdir(parents=True,exist_ok=True); due=[]; now=datetime.now(); days=int(vc.get("history_refresh_days",7))
    for c in map(str,codes):
        p=folder/f"{c}.csv"
        if not p.exists() or now-datetime.fromtimestamp(p.stat().st_mtime)>=timedelta(days=days): due.append(c)
    ok=0; failed=[]; delay=float((cfg.get("network",{}) or {}).get("request_delay_seconds",.12))
    for c in due[:int(vc.get("history_refresh_batch",20))]:
        try:update_valuation_history(c,cfg,logger);ok+=1
        except Exception as e: failed.append({"code":c,"error":str(e)})
        time.sleep(delay)
    coverage=valuation_history_coverage(codes); status={"enabled":True,"refreshed":ok,"failed":failed,"due":len(due),"coverage":coverage,"updated_at":now_iso()}; write_json(ROOT/"cache"/"valuation_status.json",status); return status

def valuation_history_coverage(codes):
    codes=list(map(str,codes)); folder=ROOT/"data"/"valuation"; return sum((folder/f"{c}.csv").exists() for c in codes)/max(1,len(codes))

def merge_historical_valuation(ds):
    if ds.empty:return ds
    parts=[]
    for code,g in ds.groupby("code",sort=False):
        v=_read(str(code)); g=g.sort_values("date").copy()
        if v.empty:
            for c in ["pe_ttm_hist","pb_hist","valuation_date"]: g[c]=pd.NaT if c=="valuation_date" else np.nan
        else:
            keep=["date"]+[c for c in ["pe_ttm","pb"] if c in v]; vv=v[keep].sort_values("date").rename(columns={"date":"valuation_date","pe_ttm":"pe_ttm_hist","pb":"pb_hist"})
            g=pd.merge_asof(g,vv,left_on="date",right_on="valuation_date",direction="backward")
        parts.append(g)
    return pd.concat(parts,ignore_index=True).sort_values(["date","code"])

def add_historical_valuation_score(frame,cfg):
    x=frame.copy(); vc=cfg.get("valuation",{}) or {}; loss=float(vc.get("loss_company_score",15)); missing=float(vc.get("missing_score",50))
    pe=_cheap_score(x.get("pe_ttm_hist",pd.Series(index=x.index,dtype=float)),loss,missing); pb=_cheap_score(x.get("pb_hist",pd.Series(index=x.index,dtype=float)),loss,missing)
    pw=float(vc.get("pe_weight",.6)); bw=float(vc.get("pb_weight",.4)); x["score_valuation_hist"]=(pw*pe+bw*pb)/max(pw+bw,1e-9); return x
