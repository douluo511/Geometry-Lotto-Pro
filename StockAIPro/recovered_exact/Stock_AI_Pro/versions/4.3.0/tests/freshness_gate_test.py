
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stock_ai.pipeline as pl

cfg={
 "universe":{},
 "model":{},
 "automation":{},
 "safety":{"stale_lock_hours":4,"min_live_update_ratio":.7}
}
snap=pd.DataFrame({"code":["000001"],"name":["A"],"amount":[1e8]})

with tempfile.TemporaryDirectory() as td:
    tmp=Path(td)
    for d in ["logs","state","cache"]:
        (tmp/d).mkdir(parents=True,exist_ok=True)
    patches=[
      patch.object(pl,"ROOT",tmp),
      patch.object(pl,"load_config",return_value=cfg),
      patch.object(pl,"ensure_dirs",lambda:None),
      patch.object(pl,"fetch_full_universe",return_value=pd.DataFrame({"code":["000001"],"name":["A"]})),
      patch.object(pl,"fetch_market_snapshot",return_value=snap),
      patch.object(pl,"update_live_histories",return_value={"ok":1,"total":1,"failed":[],"latest_date":"2026-08-24"}),
      patch.object(pl,"fetch_expected_trade_date",return_value="2026-08-25"),
    ]
    for p in patches:p.start()
    try:
        try:
            pl.run(False,False)
            raise AssertionError("stale history should be rejected")
        except RuntimeError as e:
            assert "过期" in str(e)
    finally:
        for p in reversed(patches):p.stop()
print("FRESHNESS GATE TEST PASS")
