from __future__ import annotations
import argparse,pandas as pd
from .config import ROOT,load_config,ensure_dirs
from .utils import setup_logging,write_json,now_iso,process_lock
from .data_source import fetch_market_snapshot,fetch_full_universe,update_live_histories,bootstrap_research_pool,load_histories,enrich_industries,select_training_histories,fetch_expected_trade_date
from .features import build_dataset
from .model import train_validated_ensemble,predict_ensemble,persist_model
from .regime import detect_market_regime
from .data_quality import inspect_histories
from .scoring import add_scores,make_portfolios
from .storage import freeze_prediction
from .maintenance import maybe_run_maintenance
from .drift import feature_drift
from .backup import maybe_snapshot
from .valuation import refresh_valuation_histories
from .decision import decide
from .rnd import build_shadow_frame, run_rnd_cycle

def _run_locked(cfg,logger,force,run_maintenance):
    logger.info("=== Stock AI Pro 4.3 每日闭环开始 ===")
    master=fetch_full_universe(cfg,logger); snapshot=fetch_market_snapshot(cfg,logger)
    if snapshot.empty: raise RuntimeError("实时股票池为空，停止生成新预测")
    snapshot.to_csv(ROOT/"cache"/"market_snapshot.csv",index=False,encoding="utf-8-sig")
    upd=update_live_histories(snapshot,cfg,logger); expected=fetch_expected_trade_date(logger); upd["expected_trade_date"]=expected; write_json(ROOT/"cache"/"last_update_status.json",upd)
    ratio=upd["ok"]/max(1,upd["total"])
    if ratio<float(cfg["safety"].get("min_live_update_ratio",.7)): raise RuntimeError(f"有效行情更新比例过低 {ratio:.1%}，停止生成新预测")
    if expected and upd.get("latest_date") and pd.Timestamp(upd["latest_date"])<pd.Timestamp(expected): raise RuntimeError(f"个股历史数据过期：最新={upd['latest_date']}，市场基准最新交易日={expected}。停止新预测并保留旧结果。")
    bootstrap=bootstrap_research_pool(master,cfg,snapshot["code"].tolist(),logger)
    live_hist=load_histories(snapshot["code"].tolist()); live_quality=inspect_histories(live_hist)
    if live_quality["good_ratio"]<.7 and cfg["safety"].get("abort_on_low_data_quality",True): raise RuntimeError(f"实时候选历史质量不足 good_ratio={live_quality['good_ratio']:.1%}")
    all_hist=load_histories(); training_hist=select_training_histories(all_hist,snapshot["code"].tolist(),master,cfg); extra_count=max(0,len(training_hist)-len(live_hist))
    h=int(cfg["model"]["horizon_days"]); train_ds=build_dataset(training_hist,h,int(cfg["model"]["min_history_days"])); live_ds=build_dataset(live_hist,h,int(cfg["model"]["min_history_days"]))
    if train_ds.empty or live_ds.empty: raise RuntimeError("训练数据或实时候选特征为空")
    asof_dt=pd.to_datetime(live_ds["date"]).max(); asof=asof_dt.strftime("%Y-%m-%d"); current=live_ds[live_ds["date"]==asof_dt].drop_duplicates("code",keep="last").copy()
    target=cfg["model"].get("target","target_excess"); train_all=train_ds[train_ds[target].notna()].copy()
    max_rows=int(cfg["model"].get("max_train_rows",180000))
    models,weights,metrics,dev,valid,final_train=train_validated_ensemble(
        train_all,target,h,int(cfg["model"].get("validation_days",40)),
        int(cfg["model"]["random_state"]),cfg["model"].get("ensemble_mode","validation_dynamic"),
        cfg["model"],max_rows)
    metrics.update({"research_training_symbols":len(training_hist),"research_extra_symbols":extra_count})
    drift=feature_drift(final_train,current,cfg); write_json(ROOT/"reports"/"drift_report.json",drift)
    pred=predict_ensemble(models,current,weights); regime=detect_market_regime(current,snapshot)
    industries=enrich_industries(pred.sort_values("pred",ascending=False).head(120)["code"].tolist(),logger)
    valuation_status=refresh_valuation_histories(pred.sort_values("pred",ascending=False).head(120)["code"].tolist(),cfg,logger)
    scored=add_scores(pred,snapshot,cfg,regime,industries); decision=decide(scored,cfg,regime,drift.get("status","PASS"),metrics.get("rank_ic")); portfolios=make_portfolios(scored,cfg,regime); rnd_shadow=build_shadow_frame(scored)
    persist_model(models,weights,asof,metrics,cfg)
    summary={"version":"4.3.0-deliverable","asof":asof,"generated_at":now_iso(),"live_universe_size":len(snapshot),"research_master_size":len(master),"research_training_symbols":len(training_hist),"research_extra_symbols":extra_count,"dev_train_rows":len(dev),"production_train_rows":len(final_train),"validation_rows":len(valid),"model_names":metrics.get("model_names",[]),"horizon_days":h,"validation_embargo_days":h,"entry_assumption":"next_open","top_k":int(cfg["model"]["top_k"]),"market_regime":regime["regime"],"model_rank_ic":metrics.get("rank_ic"),"ensemble_mode":metrics.get("ensemble_mode","validation_dynamic"),"feature_drift":drift.get("status"),"bootstrap_coverage":bootstrap.get("coverage"),"delisted_coverage":bootstrap.get("delisted_coverage"),"valuation_history_coverage":valuation_status.get("coverage"),"spot_provider":str(snapshot["spot_provider"].mode().iloc[0]) if "spot_provider" in snapshot and not snapshot.empty else "unknown","history_provider_counts":upd.get("provider_counts",{}),"expected_trade_date":expected,"decision":decision["decision"],"model_trust":decision["model_trust"],"note":"评分是横截面相对排序，不是上涨概率。成本、估值和Net Alpha已进入同一生产决策链；历史估值覆盖不足时不会冒充已验证。"}
    data_quality=dict(live_quality); data_quality["feature_drift"]=drift
    cost_assumptions=cfg.get("cost",{})
    try: out=freeze_prediction(asof,scored,portfolios,summary,metrics,regime,data_quality,force,valuation_status,cost_assumptions,decision,rnd_shadow)
    except FileExistsError as e: logger.info(str(e)); out=ROOT/"predictions"/asof
    rnd_status=None
    if cfg.get("automation",{}).get("auto_rnd",True):
        try:rnd_status=run_rnd_cycle(cfg,logger).get("status")
        except Exception as e: logger.warning("R&D闭环失败但不阻断生产预测: %s",e); rnd_status="FAIL_NONBLOCKING"
    maintenance=maybe_run_maintenance(cfg,logger) if run_maintenance else None; backup=maybe_snapshot(cfg,logger)
    write_json(ROOT/"state"/"last_run.json",{"status":"PASS","asof":asof,"finished_at":now_iso(),"prediction_dir":str(out),"maintenance":maintenance,"backup":backup,"drift":drift.get("status"),"decision":decision,"rnd_status":rnd_status})
    logger.info("=== 每日闭环完成: %s / %s ===",asof,decision["decision"]); return out

def run(force=False,run_maintenance=True):
    cfg=load_config(); ensure_dirs(); logger=setup_logging(ROOT/"logs")
    try:
        with process_lock(ROOT/"state"/"daily.lock",cfg["safety"].get("stale_lock_hours",4)): return _run_locked(cfg,logger,force,run_maintenance)
    except Exception as e:
        if "已有流程正在运行" not in str(e): write_json(ROOT/"state"/"last_run.json",{"status":"FAIL","failed_at":now_iso(),"error":str(e)}); logger.exception("每日闭环失败: %s",e)
        else: logger.warning("跳过重复启动: %s",e)
        raise

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--force",action="store_true"); ap.add_argument("--no-maintenance",action="store_true"); a=ap.parse_args(); run(a.force,not a.no_maintenance)
if __name__=="__main__": main()
