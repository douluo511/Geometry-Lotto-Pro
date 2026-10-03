import sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.features import FEATURES
from stock_ai.model import train_validated_ensemble,predict_ensemble

rng=np.random.default_rng(123)
dates=pd.bdate_range('2024-01-02',periods=280)
rows=[]
for d in dates:
    for i in range(12):
        vals=rng.normal(size=len(FEATURES))
        target=.012*vals[FEATURES.index('ret20')]-.008*abs(vals[FEATURES.index('vol20')])+0.004*np.tanh(vals[FEATURES.index('amount_z20')])+rng.normal(0,.008)
        row={c:float(v) for c,v in zip(FEATURES,vals)};row.update(date=d,code=f'{i:06d}',target_excess=target);rows.append(row)
ds=pd.DataFrame(rows)
cfg={'ensemble_shrinkage':.2,'extra_trees_n_estimators':50,'extra_trees_min_samples_leaf':4,'hgb_max_iter':70,'hgb_max_depth':4}
models,weights,metrics,dev,valid,final_train=train_validated_ensemble(ds,'target_excess',5,40,42,'validation_dynamic',cfg,50000)
assert set(models)=={'ridge','hgb','extra_trees'}
assert abs(sum(weights.values())-1)<1e-9 and all(v>=0 for v in weights.values())
assert metrics['embargo_horizon_days']==5 and metrics['validation_start']>metrics['embargo_cutoff']
assert pd.to_datetime(dev.date).max()<pd.Timestamp(metrics['embargo_cutoff'])
cur=ds.groupby('code',as_index=False).tail(1).copy();out=predict_ensemble(models,cur,weights)
assert {'pred','pred_ridge','pred_hgb','pred_extra_trees','model_disagreement','model_prediction_range'}<=set(out)
assert np.isfinite(out['pred']).all() and (out['model_disagreement']>=0).all()
print('THREE-MODEL VALIDATED ENSEMBLE TEST PASS',weights,metrics['rank_ic'])
