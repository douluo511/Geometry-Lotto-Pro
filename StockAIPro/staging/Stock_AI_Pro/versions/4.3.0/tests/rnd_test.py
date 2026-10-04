import sys,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.rnd as rnd

# Shadow construction must be outcome-free and keep all challengers.
sc=pd.DataFrame({
    'code':['000001','000002','000003'],'name':['A','B','C'],'industry':['I']*3,'date':['2026-01-02']*3,
    'final_score':[80,70,60],'expected_net_alpha':[.03,.02,.01],
    'pred_ridge':[.01,.03,.02],'pred_hgb':[.04,.01,.02],'pred_extra_trees':[.02,.025,.015],
    'estimated_roundtrip_cost_bps':[10,10,10],
    'score_momentum':[60,80,50],'score_valuation':[70,50,90],'score_cost':[80,80,80]})
shadow=rnd.build_shadow_frame(sc)
assert {'production_rank','ridge_rank','hgb_rank','extra_trees_rank','equal_rank','momentum_value_rank'}<=set(shadow)
assert 'realized_gross' not in shadow

# End-to-end frozen-before-outcome evaluation. Equal ensemble is deliberately superior.
with tempfile.TemporaryDirectory() as td:
    tmp=Path(td);(tmp/'predictions').mkdir();(tmp/'reports').mkdir();(tmp/'data'/'history').mkdir(parents=True)
    dates=pd.bdate_range('2026-01-02',periods=100)
    signal_idx=list(range(0,78,6))[:13]
    codes=[f'{i:06d}' for i in range(1,31)]
    histories={}
    for j,c in enumerate(codes):
        x=pd.DataFrame({'date':dates,'open':100.0,'close':100.0,'high':101.0,'low':99.0,'volume':1_000_000,'amount':100_000_000})
        desired=.03 if j<10 else (0.0 if j<20 else -.02)
        for idx in signal_idx:
            x.loc[idx+1,'open']=100.0;x.loc[idx+5,'close']=100*(1+desired)
        histories[c]=x
    for idx in signal_idx:
        d=dates[idx].strftime('%Y-%m-%d');p=tmp/'predictions'/d;p.mkdir()
        # production/ridge/hgb choose bad last 10; equal chooses good first 10.
        df=pd.DataFrame({'code':codes,'name':codes,'estimated_roundtrip_cost_bps':0.0})
        bad=list(range(21,31))+list(range(11,21))+list(range(1,11))
        good=list(range(1,11))+list(range(11,21))+list(range(21,31))
        rank_bad={f'{v:06d}':i+1 for i,v in enumerate(bad)};rank_good={f'{v:06d}':i+1 for i,v in enumerate(good)}
        df['production_rank']=df.code.map(rank_bad);df['ridge_rank']=df.code.map(rank_bad);df['hgb_rank']=df.code.map(rank_bad);df['extra_trees_rank']=df.code.map(rank_bad);df['equal_rank']=df.code.map(rank_good);df['momentum_value_rank']=df.code.map(rank_bad)
        fp=p/'rnd_shadow.csv';df.to_csv(fp,index=False)
        h=hashlib.sha256(fp.read_bytes()).hexdigest();(p/'manifest.json').write_text(json.dumps({'files':{'rnd_shadow.csv':h}}),encoding='utf-8')
    (tmp/'reports'/'audit_report.json').write_text(json.dumps({'trust':'HIGH'}),encoding='utf-8')
    cfg={'model':{'horizon_days':5,'top_k':10},'rnd':{'enabled':True,'max_prediction_days':120,'top_k':10,'min_eval_points':12,'bootstrap_trials':300,'min_mean_improvement':.001,'min_win_rate':.55,'max_drawdown_tolerance':.03,'require_positive_ci_lower':True,'recent_window':6,'degradation_threshold':.002,'auto_promote':False}}
    with patch.object(rnd,'ROOT',tmp),patch.object(rnd,'load_histories',return_value=histories):
        report=rnd.run_rnd_cycle(cfg)
    assert report['production_change_applied'] is False and report['auto_promote'] is False
    gates={g['challenger']:g for g in report['promotion_gates']}
    assert gates['equal_ensemble']['status']=='PROMOTABLE_REVIEW',gates['equal_ensemble']
    assert gates['equal_ensemble']['tests']['seed_window_stability'] is True
    assert gates['equal_ensemble']['tests']['multiple_testing_correction'] is True
    assert gates['equal_ensemble']['tests']['reality_check'] is True
    assert gates['equal_ensemble']['holm_adjusted_p'] <= .05
    assert gates['equal_ensemble']['reality_check']['p_value'] <= .05
    assert gates['ridge_only']['status']=='REJECT'
    assert (tmp/'reports'/'rnd_shadow_history.csv').exists()
    assert report.get('evidence_id') and len(report['evidence_id'])==64
    ev=json.loads((tmp/'reports'/'rnd_evidence.json').read_text(encoding='utf-8'));assert ev['evidence_id']==report['evidence_id'] and ev.get('report_sha256')
    reg=json.loads((tmp/'reports'/'rnd_candidate_registry.json').read_text(encoding='utf-8'));assert any(c['challenger']=='equal_ensemble' and c['auto_promote'] is False for c in reg['candidates'])
print('R&D CHAMPION/CHALLENGER TEST PASS')
