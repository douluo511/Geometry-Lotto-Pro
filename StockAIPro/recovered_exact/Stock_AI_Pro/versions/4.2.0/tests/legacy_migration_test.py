
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stock_ai.data_source import _upgrade_legacy_history

old=pd.DataFrame({
    "date":["2026-08-20"],
    "code":["000001"],
    "open":[10.0],"close":[10.1],"high":[10.2],"low":[9.9],
    "volume":[12345.0],        # old Eastmoney hands
    "turnover":[123456789.0], # old v2 amount field
    "turnover_rate":[2.5],    # old Eastmoney percent
    "provider":["eastmoney"],
    "adjust_mode":["hfq"]
})
x=_upgrade_legacy_history(old)
assert "amount" in x and "turnover" not in x
assert x.iloc[0]["volume"]==1234500.0
assert abs(x.iloc[0]["turnover_rate"]-.025)<1e-12
assert int(x.iloc[0]["schema_version"])==3
print("LEGACY MIGRATION TEST PASS")
