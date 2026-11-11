from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from .domain import ExperimentInput

def assess(x:ExperimentInput)->dict:
    x.validate()
    contribution=x.price-x.variable_cost-x.acquisition_cost
    payment=x.real_payments>0
    repeated=x.repeat_payments>0
    unit="PASS" if payment and contribution>0 else ("FAIL" if payment and contribution<=0 else "NOT VERIFIED")
    statuses={
      "logic_root_cause":"PASS",
      "reversal_red_team":"PASS",
      "real_demand_behavior":"PASS" if payment else "NOT VERIFIED",
      "real_payment":"PASS" if payment else "NOT VERIFIED",
      "unit_economics":unit,
      "cash_survivability":"NOT VERIFIED",
      "repeatability":"PASS" if repeated else "NOT VERIFIED",
      "systemization":"NOT VERIFIED",
      "asset_accumulation":"NOT VERIFIED",
      "scale_stress":"NOT VERIFIED",
      "stop_conditions":"PASS",
      "operating_rhythm":"PASS"
    }
    rid=hashlib.sha256((datetime.now(timezone.utc).isoformat()+x.project).encode()).hexdigest()[:24]
    return {
      "status":"PASS","record_id":rid,"created_at":datetime.now(timezone.utc).isoformat(),
      "input":x.to_dict(),"contribution_margin_before_fixed":contribution,
      "business_gate_statuses":statuses,
      "scale_authorized":all(statuses[k]=="PASS" for k in ("real_payment","unit_economics","repeatability","systemization","scale_stress")),
      "profit_guarantee":False,
      "decision":"TEST_OR_STOP" if not payment else ("CONTINUE_SMALL" if unit=="PASS" else "STOP_OR_REPAIR")
    }

def portfolio_metrics(records:list[dict])->dict:
    n=len(records); paid=sum((r.get("input") or {}).get("real_payments",0)>0 for r in records)
    repeated=sum((r.get("input") or {}).get("repeat_payments",0)>0 for r in records)
    return {"status":"PASS","projects":n,"paid_projects":paid,"repeat_projects":repeated,"scale_ready_projects":sum(bool(r.get("scale_authorized")) for r in records)}
