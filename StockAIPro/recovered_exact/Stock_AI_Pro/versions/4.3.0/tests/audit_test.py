import sys,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.audit as au

def synthetic(code,n=430,seed=1):
    rng=np.random.default_rng(seed);d=pd.bdate_range('2023-01-02',periods=n)
    r=rng.normal(.0003,.013,n);c=20*np.exp(np.cumsum(r))
    return pd.DataFrame({'date':d,'code':code,'open':c*(1+rng.normal(0,.002,n)),'close':c,
        'high':c*(1+rng.uniform(0,.015,n)),'low':c*(1-rng.uniform(0,.015,n)),
        'volume':rng.integers(1_000_000,15_000_000,n),'amount':rng.integers(3e7,4e8,n)})

hist={f'{i:06d}':synthetic(f'{i:06d}',430,i+17) for i in range(1,61)}
cfg={'model':{'horizon_days':5,'target':'target_excess','min_history_days':240,'random_state':42},
     'valuation':{'backtest_min_coverage':.4},'decision':{}}
with tempfile.TemporaryDirectory() as td:
    tmp=Path(td)
    for d in ['predictions/2026-09-09','cache','reports']:(tmp/d).mkdir(parents=True,exist_ok=True)
    pred=tmp/'predictions'/'2026-09-09'/'predictions.csv';pred.write_text('code,score\n000001,88\n',encoding='utf-8')
    digest=hashlib.sha256(pred.read_bytes()).hexdigest()
    (pred.parent/'manifest.json').write_text(json.dumps({'files':{'predictions.csv':digest}}),encoding='utf-8')
    (tmp/'cache'/'bootstrap_status.json').write_text(json.dumps({'coverage':1.0,'delisted_coverage':1.0}),encoding='utf-8')
    (tmp/'cache'/'valuation_status.json').write_text(json.dumps({'coverage':.8}),encoding='utf-8')
    (tmp/'reports'/'backtest_summary.json').write_text(json.dumps({'dynamic_cost_model':True,'capacity_mean_net_returns':{'100000':.01},'capacity_limit_cny':1000000,'value_baseline_validated':True,'mean_excess_vs_random':.002}),encoding='utf-8')
    (tmp/'reports'/'drift_report.json').write_text(json.dumps({'status':'PASS'}),encoding='utf-8')
    with patch.object(au,'ROOT',tmp),patch.object(au,'load_config',return_value=cfg),patch.object(au,'load_histories',return_value=hist):
        report=au.run_audit()
ids={x['id'] for x in report['checks']}
required={'FUTURE_SAFE_FEATURES','EMBARGO_SPLIT','LABEL_SHUFFLE','TIME_SHIFT','IMMUTABLE','UNIVERSE_COVERAGE','SURVIVORSHIP','VALUATION_PIT','DYNAMIC_COST','CAPACITY','VALUE_BASELINE','RANDOM_BASELINE','FEATURE_DRIFT'}
assert required<=ids
assert report['trust'] in {'MEDIUM','HIGH'}
assert 'Label Shuffle' in report['reverse_validation'] and 'Time Shift' in report['reverse_validation']
assert report['five_why'], 'Expected documented limitation to produce Five-Why output'
print('AUDIT / 5WHY / REVERSE VALIDATION TEST PASS',report['trust'])
