
from __future__ import annotations
from datetime import date
from .config import ROOT
from .utils import read_json,write_json,now_iso
from .backtest import run_backtest
from .audit import run_audit

def maybe_run_maintenance(cfg,logger=None,force=False):
    state=read_json(ROOT/"state"/"maintenance.json",{}) or {}
    due=True
    last_success=state.get("last_success_date")
    if last_success and not force:
        try:
            delta=(date.today()-date.fromisoformat(last_success)).days
            due=delta>=int(cfg["automation"].get("maintenance_every_days",5))
        except Exception:
            due=True
    result={"due":due,"backtest":None,"audit":None}
    if not due:return result

    requested=[]
    if cfg["automation"].get("auto_backtest",True):
        requested.append("backtest")
        try:
            _,s=run_backtest();result["backtest"]="PASS"
        except Exception as e:
            result["backtest"]=f"FAIL: {e}"
            if logger:logger.warning("自动回测未完成，下次运行会重试: %s",e)

    if cfg["automation"].get("auto_audit",True):
        requested.append("audit")
        try:
            r=run_audit();result["audit"]=r.get("trust","UNKNOWN")
        except Exception as e:
            result["audit"]=f"FAIL: {e}"
            if logger:logger.warning("自动审计未完成，下次运行会重试: %s",e)

    success=True
    for name in requested:
        val=result.get(name)
        if val is None or str(val).startswith("FAIL"):
            success=False

    new_state={
      "last_attempt_date":date.today().isoformat(),
      "updated_at":now_iso(),
      "result":result
    }
    if success:
        new_state["last_success_date"]=date.today().isoformat()
    elif last_success:
        new_state["last_success_date"]=last_success
    write_json(ROOT/"state"/"maintenance.json",new_state)
    return result
