import sys,tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.storage as st

def frame():return pd.DataFrame({'code':['000001','000002'],'final_score':[80,70]})
with tempfile.TemporaryDirectory() as td:
    data=Path(td);(data/'predictions').mkdir();(data/'state').mkdir()
    with patch.object(st,'ROOT',data):
        st.freeze_prediction('2026-09-01',frame(),{'balanced':frame()}, {'asof':'2026-09-01'},{},{},{},False,{}, {}, {}, None)
        st.freeze_prediction('2026-09-02',frame(),{'balanced':frame()}, {'asof':'2026-09-02'},{},{},{},False,{}, {}, {}, None)
        ok,msg,n=st.verify_prediction_chain(data);assert ok and n==2,msg
        head=__import__('json').loads((data/'state'/'prediction_chain.json').read_text());assert head['sequence']==2 and head['head_date']=='2026-09-02'
        # Any historical mutation must break chain verification.
        p=data/'predictions'/'2026-09-01'/'predictions.csv';p.write_text(p.read_text(encoding='utf-8-sig')+'\nTAMPER',encoding='utf-8-sig')
        ok,msg,n=st.verify_prediction_chain(data);assert not ok and '哈希不一致' in msg
print('PREDICTION CROSS-PERIOD HASH CHAIN TEST PASS')
