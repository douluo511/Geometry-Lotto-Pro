
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.maintenance as m

cfg={"automation":{"maintenance_every_days":5,"auto_backtest":True,"auto_audit":True}}
with tempfile.TemporaryDirectory() as td:
    tmp=Path(td);(tmp/"state").mkdir()
    # first attempt fails: must NOT write last_success_date
    with patch.object(m,"ROOT",tmp),patch.object(m,"run_backtest",side_effect=RuntimeError("x")),patch.object(m,"run_audit",side_effect=RuntimeError("y")):
        r=m.maybe_run_maintenance(cfg)
    state=m.read_json(tmp/"state"/"maintenance.json",{})
    assert "last_success_date" not in state
    # next attempt same day must retry and succeed
    with patch.object(m,"ROOT",tmp),patch.object(m,"run_backtest",return_value=(None,{})),patch.object(m,"run_audit",return_value={"trust":"MEDIUM"}):
        r=m.maybe_run_maintenance(cfg)
    state=m.read_json(tmp/"state"/"maintenance.json",{})
    assert state.get("last_success_date")
print("MAINTENANCE RETRY TEST PASS")
