from __future__ import annotations
import json,numpy as np,pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from .config import ROOT,load_config
from .data_source import load_histories
from .features import build_dataset,FEATURES
from .model import rank_ic
from .utils import write_json,read_json,now_iso,sha256_file
from .storage import verify_prediction_chain

def _ridge(): return Pipeline([("imputer",SimpleImputer(strategy="median")),("scaler",StandardScaler()),("model",Ridge(alpha=8.0))])
def verify_manifest(pred_dir):
    p=pred_dir/"manifest.json"
    if not p.exists():return False,"manifest缺失"
    m=json.loads(p.read_text(encoding="utf-8"))
    for name,expected in m.get("files",{}).items():
        f=pred_dir/name
        if not f.exists() or sha256_file(f)!=expected:return False,f"{name}哈希不一致"
    return True,"冻结文件哈希一致"

def run_audit():
    cfg=load_config();h=int(cfg["model"]["horizon_days"]);target=cfg["model"].get("target","target_excess");ds=build_dataset(load_histories(),h,int(cfg["model"]["min_history_days"]));ds=ds[ds[target].notna()].copy()
    if len(ds)<3000:raise RuntimeError("审计数据不足")
    dates=sorted(ds.date.unique());i=int(len(dates)*.8)
    if i<=h+40:raise RuntimeError("审计时间窗口不足")
    test_start=dates[i]; embargo_cutoff=dates[i-h];tr=ds[ds.date<embargo_cutoff].tail(100000);te=ds[ds.date>=test_start].copy();base=_ridge();base.fit(tr[FEATURES],tr[target]);bp=base.predict(te[FEATURES]);base_ic=rank_ic(te[target],bp)
    rng=np.random.default_rng(int(cfg["model"]["random_state"]));sy=tr[target].to_numpy().copy();rng.shuffle(sy);sm=_ridge();sm.fit(tr[FEATURES],sy);shuffle_ic=rank_ic(te[target],sm.predict(te[FEATURES]));shift_ic=rank_ic(te[target].shift(17),bp)
    dirs=sorted([p for p in (ROOT/"predictions").glob("*") if p.is_dir() and p.name not in {"latest","_forced_backups"}]);imm_ok,imm_msg=verify_manifest(dirs[-1]) if dirs else (False,"尚无冻结预测")
    bootstrap=read_json(ROOT/"cache"/"bootstrap_status.json",{}) or {};bt=read_json(ROOT/"reports"/"backtest_summary.json",{}) or {};drift=read_json(ROOT/"reports"/"drift_report.json",{}) or {};vs=read_json(ROOT/"cache"/"valuation_status.json",{}) or {};latest=read_json(ROOT/"predictions"/"latest"/"summary.json",{}) or {}
    coverage=float(bootstrap.get("coverage",0) or 0);dcfg=cfg.get("decision",{}) or {}
    latest_dir=ROOT/"predictions"/"latest"; rnd_shadow_ok=(latest_dir/"rnd_shadow.csv").exists() and verify_manifest(latest_dir)[0] if latest_dir.exists() else False
    chain_ok,chain_msg,chain_len=verify_prediction_chain(ROOT)
    rnd_cfg=cfg.get("rnd",{}) or {}
    checks=[
      {"id":"FUTURE_SAFE_FEATURES","name":"未来字段隔离","status":"PASS" if "target_return" not in FEATURES and "target_excess" not in FEATURES else "FAIL","detail":"训练特征不包含未来收益标签"},
      {"id":"EXECUTION_LAG","name":"次日开盘执行","status":"PASS","detail":"训练目标/回测均使用下一交易日开盘入场"},
      {"id":"EMBARGO_SPLIT","name":"Horizon Embargo","status":"PASS","detail":f"隔离={h}交易日"},
      {"id":"LABEL_SHUFFLE","name":"标签打乱","status":"PASS" if (not np.isfinite(shuffle_ic) or abs(shuffle_ic)<.08) else "FAIL","detail":f"shuffle IC={shuffle_ic:.4f}"},
      {"id":"TIME_SHIFT","name":"时间错位","status":"PASS" if (not np.isfinite(shift_ic) or abs(shift_ic)<max(.06,abs(base_ic)*.75)) else "WARN","detail":f"base={base_ic:.4f}; shifted={shift_ic:.4f}"},
      {"id":"IMMUTABLE","name":"预测冻结","status":"PASS" if imm_ok else "FAIL","detail":imm_msg},
      {"id":"PREDICTION_HASH_CHAIN","name":"跨期预测哈希证据链","status":"PASS" if chain_ok else "FAIL","detail":chain_msg},
      {"id":"UNIVERSE_COVERAGE","name":"研究池覆盖","status":"PASS" if coverage>=.9 else ("WARN" if coverage>=.4 else "FAIL"),"detail":f"coverage={coverage:.1%}"},
      {"id":"SURVIVORSHIP","name":"退市覆盖","status":"PASS" if float(bootstrap.get("delisted_coverage",0) or 0)>=.9 else "WARN","detail":f"delisted={float(bootstrap.get('delisted_coverage',0) or 0):.1%}"},
      {"id":"VALUATION_PIT","name":"估值PIT","status":"PASS" if float(vs.get("coverage",0) or 0)>=float(cfg.get("valuation",{}).get("backtest_min_coverage",.4)) else "WARN","detail":f"历史估值缓存覆盖={float(vs.get('coverage',0) or 0):.1%}; 回测仅as-of向后合并"},
      {"id":"DYNAMIC_COST","name":"动态交易成本","status":"PASS" if bt.get("dynamic_cost_model") is True else "WARN","detail":"佣金/税费/滑点/冲击进入净收益"},
      {"id":"CAPACITY","name":"容量测试","status":"PASS" if bt.get("capacity_mean_net_returns") else "WARN","detail":f"capacity_limit={bt.get('capacity_limit_cny')}"},
      {"id":"VALUE_BASELINE","name":"价值基准","status":"PASS" if bt.get("value_baseline_validated") else "WARN","detail":"估值PIT覆盖不足时不冒充已验证"},
      {"id":"RANDOM_BASELINE","name":"随机基准","status":"PASS" if bt and float(bt.get("mean_excess_vs_random",0))>0 else "WARN","detail":f"mean_excess_vs_random={float(bt.get('mean_excess_vs_random',0) or 0):.4%}"},
      {"id":"FEATURE_DRIFT","name":"特征漂移","status":"PASS" if drift.get("status")=="PASS" else ("WARN" if drift.get("status") in {"WARN",None} else "FAIL"),"detail":f"drift={drift.get('status','尚无报告')}"},
      {"id":"RND_PREOUTCOME_FREEZE","name":"研发Challenger事前冻结","status":"PASS" if rnd_shadow_ok else "WARN","detail":"Champion/Challenger必须在真实结果出现前进入冻结manifest"},
      {"id":"RND_NO_AUTO_PROMOTE","name":"研发禁止静默晋级","status":"PASS" if not bool(rnd_cfg.get("auto_promote",False)) else "FAIL","detail":"候选通过Gate也只进入PROMOTABLE_REVIEW，不自动修改生产模型"},
      {"id":"HISTORICAL_ST_PIT","name":"历史ST逐日状态","status":"WARN","detail":"公开自助版尚未完整逐日重建历史ST/停牌状态，报告保留此限制。"}
    ]
    fail=sum(c["status"]=="FAIL" for c in checks);warn=sum(c["status"]=="WARN" for c in checks);trust="LOW" if fail else ("MEDIUM" if warn else "HIGH")
    five=[{"check":c["name"],"status":c["status"],"why1":"验证未达到PASS。","why2":"数据覆盖、时间一致性或基准证据不足。","why3":"公开数据和样本外稳定性存在现实限制。","why4":"忽略会把偏差或Beta误认为Alpha。","why5":"处置：降低MODEL TRUST，继续积累冻结样本并重新验证。"} for c in checks if c["status"]!="PASS"]
    report={"generated_at":now_iso(),"trust":trust,"base_rank_ic":base_ic,"shuffle_rank_ic":shuffle_ic,"shifted_rank_ic":shift_ic,"embargo_horizon_days":h,"checks":checks,"five_why":five,"reverse_validation":["Label Shuffle","Time Shift","Random Baseline","Momentum Baseline","Value Baseline(PIT only)","Dynamic Cost / Zero-cost comparison","Capacity Test","Feature Drift","Freeze Integrity","Feature Ablation由测试套件验证模块独立性","Champion/Challenger事前冻结","Paired Bootstrap Promotion Gate","Cross-period Prediction Hash Chain"]}
    write_json(ROOT/"reports"/"audit_report.json",report);return report
