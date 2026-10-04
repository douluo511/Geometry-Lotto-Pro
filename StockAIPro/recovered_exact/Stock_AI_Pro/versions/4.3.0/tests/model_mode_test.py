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
models={'ridge':Dummy(np.arange(n)),'hgb':Dummy(np.arange(n)[::-1]),'extra_trees':Dummy(np.arange(n)*.9)}
for mode,name in [('ridge_only','ridge'),('hgb_only','hgb'),('extra_trees_only','extra_trees')]:
    _,w=validation_metrics(models,x,'target_excess',mode);assert w[name]==1.0 and abs(sum(w.values())-1)<1e-12
m,w=validation_metrics(models,x,'target_excess','equal');assert all(abs(v-1/3)<1e-12 for v in w.values()) and m['ensemble_mode']=='equal'
m,w=validation_metrics(models,x,'target_excess','validation_dynamic',{'ensemble_shrinkage':.2});assert abs(sum(w.values())-1)<1e-9 and m['ensemble_mode']=='validation_dynamic' and set(m['model_names'])==set(models)
print('MODEL ENSEMBLE MODE TEST PASS')
