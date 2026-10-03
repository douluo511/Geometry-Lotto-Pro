import sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.features import FEATURES
from stock_ai.model import validation_metrics
class Dummy:
    def __init__(self,p):self.p=np.asarray(p,dtype=float)
    def predict(self,x):return self.p[:len(x)]
n=30;x=pd.DataFrame({c:np.arange(n,dtype=float) for c in FEATURES});x['target_excess']=np.arange(n,dtype=float)
models={'ridge':Dummy(np.arange(n)),'hgb':Dummy(np.arange(n)[::-1])}
_,w=validation_metrics(models,x,'target_excess','ridge_only');assert w=={'ridge':1.0,'hgb':0.0}
_,w=validation_metrics(models,x,'target_excess','hgb_only');assert w=={'ridge':0.0,'hgb':1.0}
m,w=validation_metrics(models,x,'target_excess','equal');assert w=={'ridge':.5,'hgb':.5} and m['ensemble_mode']=='equal'
m,w=validation_metrics(models,x,'target_excess','validation_dynamic');assert abs(sum(w.values())-1)<1e-9 and m['ensemble_mode']=='validation_dynamic'
print('MODEL ENSEMBLE MODE TEST PASS')
