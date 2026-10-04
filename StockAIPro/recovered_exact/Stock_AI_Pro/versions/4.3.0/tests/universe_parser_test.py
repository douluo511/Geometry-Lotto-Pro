
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.data_source import _parse_delist,_is_a_share_code,_filter_universe
df=pd.DataFrame({"证券代码":["000003","200011","300001"],"证券简称":["退A","B股","创业A"],
                 "上市日期":["1991-01-01"]*3,"终止上市日期":["2020-01-01"]*3})
x=_parse_delist(df,["证券代码"],["证券简称"],["上市日期"],["终止上市日期"])
cfg={"universe":{"include_bj":False,"exclude_st":True}}
x=_filter_universe(x,cfg,allow_st=True)
assert set(x.code)=={"000003","300001"}
assert _is_a_share_code("600001") and not _is_a_share_code("900901")
print("UNIVERSE PARSER TEST PASS")
