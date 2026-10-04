
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stock_ai.data_source import _normalize_hist, _normalize_spot, _clean_code

em = pd.DataFrame({
    "日期":["2026-08-24"],"股票代码":["000001"],"开盘":[10.0],"收盘":[10.2],
    "最高":[10.3],"最低":[9.9],"成交量":[12345],"成交额":[123456789.0],
    "换手率":[2.5]
})
tx = pd.DataFrame({
    "date":["2026-08-24"],"open":[10.0],"close":[10.2],"high":[10.3],"low":[9.9],
    "volume":[1234500.0],"turnover":[0.025],"amount":[123456789.0]
})
a = _normalize_hist(em,"000001","hfq","eastmoney")
b = _normalize_hist(tx,"000001","hfq","tencent")
assert a.iloc[0]["volume"] == b.iloc[0]["volume"] == 1234500.0
assert abs(a.iloc[0]["turnover_rate"] - .025) < 1e-12
assert abs(b.iloc[0]["turnover_rate"] - .025) < 1e-12
assert a.iloc[0]["amount"] == b.iloc[0]["amount"] == 123456789.0

cfg={"universe":{"exclude_st":True,"include_bj":False}}
sina=pd.DataFrame({"代码":["sz000001"],"名称":["平安银行"],"最新价":[10],"涨跌幅":[1],
                   "成交量":[1000],"成交额":[100000]})
spot=_normalize_spot(sina,cfg,"sina")
assert spot.iloc[0]["code"]=="000001"
assert spot.iloc[0]["volume"]==1000
assert _clean_code("sh600000")=="600000"
print("PROVIDER NORMALIZATION TEST PASS")
