from __future__ import annotations
from datetime import datetime,timezone
import hashlib
from .domain import PipelineDefinition

def evaluate(p:PipelineDefinition)->dict:
    p.validate()
    contribution=p.expected_revenue-p.variable_cost
    statuses={
      "pipeline_definition":"PASS",
      "connector_contracts":"PASS",
      "cost_time_accounting":"PASS",
      "risk_reversibility":"PASS",
      "evidence_lineage":"PASS",
      "real_customer_action":"PASS" if p.real_customer_actions>0 else "NOT VERIFIED",
      "real_payment":"PASS" if p.real_payments>0 else "NOT VERIFIED",
      "positive_unit_economics":"PASS" if p.real_payments>0 and contribution>0 else ("FAIL" if p.real_payments>0 and contribution<=0 else "NOT VERIFIED"),
      "repeatability":"PASS" if p.repeated_payments>0 else "NOT VERIFIED",
      "owner_labor_reduction":"NOT VERIFIED",
      "operational_resilience":"NOT VERIFIED"
    }
    record_id=hashlib.sha256((datetime.now(timezone.utc).isoformat()+p.pipeline_id).encode()).hexdigest()[:24]
    return {
      "status":"PASS","record_id":record_id,"pipeline":p.to_dict(),"contribution_before_fixed":contribution,
      "business_gate_statuses":statuses,
      "production_income_verified":statuses["real_payment"]=="PASS" and statuses["positive_unit_economics"]=="PASS",
      "scale_authorized":all(statuses[x]=="PASS" for x in ("real_payment","positive_unit_economics","repeatability","owner_labor_reduction","operational_resilience")),
      "projection_is_not_income":True
    }

def dashboard(rows:list[dict])->dict:
    return {
      "status":"PASS",
      "pipeline_count":len(rows),
      "production_income_verified_count":sum(bool(x.get("production_income_verified")) for x in rows),
      "scale_authorized_count":sum(bool(x.get("scale_authorized")) for x in rows),
      "projected_revenue":sum(float((x.get("pipeline") or {}).get("expected_revenue",0)) for x in rows),
      "real_payment_total":sum(int((x.get("pipeline") or {}).get("real_payments",0)) for x in rows),
      "warning":"Projected revenue is not real income."
    }
