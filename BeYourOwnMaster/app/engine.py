from __future__ import annotations

from datetime import datetime, timezone
from .domain import DecisionInput, TrainingResult, HIGH_RISK, new_record_id, clean

def five_why(hypotheses: list[dict]) -> tuple[dict,...]:
    if not hypotheses:
        raise ValueError("at least one 5 Why hypothesis required")
    if len(hypotheses)>5:
        raise ValueError("maximum five layers")
    out=[]
    for i,item in enumerate(hypotheses,1):
        hypothesis=clean(item.get("hypothesis",""),f"why{i}.hypothesis")
        evidence=clean(item.get("evidence",""),f"why{i}.evidence",required=False)
        status="SUPPORTED" if evidence else "NOT VERIFIED"
        out.append({"level":i,"hypothesis":hypothesis,"evidence":evidence,"status":status,"causal_proof":False})
        if not evidence:
            break
    return tuple(out)

def reversal(original: str, strongest_counterexample: str, falsifier: str, alternative: str) -> dict:
    original=clean(original,"original")
    strongest_counterexample=clean(strongest_counterexample,"strongest_counterexample")
    falsifier=clean(falsifier,"falsifier")
    alternative=clean(alternative,"alternative")
    return {
        "original":original,
        "reverse_claim":f"NOT({original})",
        "strongest_counterexample":strongest_counterexample,
        "falsifier":falsifier,
        "alternative_explanation":alternative,
        "status":"PASS"
    }

def train(decision: DecisionInput, hypotheses: list[dict], counterexample: str, falsifier: str, alternative: str) -> TrainingResult:
    decision.validate()
    whys=five_why(hypotheses)
    rev=reversal(decision.interpretation,counterexample,falsifier,alternative)
    return TrainingResult(
        record_id=new_record_id(decision.problem),
        created_at=datetime.now(timezone.utc).isoformat(),
        problem=decision.problem,
        facts=decision.facts,
        interpretation=decision.interpretation,
        five_why=whys,
        reversal=rev,
        prediction=decision.prediction,
        confidence=float(decision.confidence),
        max_loss=decision.max_loss,
        stop_line=decision.stop_line,
        reversible_action=decision.reversible_action,
        risk_category=decision.risk_category,
        escalation_required=decision.risk_category in HIGH_RISK,
    )

def process_metrics(records: list[dict]) -> dict:
    total=len(records)
    prereg=sum(bool(r.get("prediction") and r.get("stop_line")) for r in records)
    reversals=sum(bool((r.get("reversal") or {}).get("falsifier")) for r in records)
    escalations=sum(bool(r.get("escalation_required")) for r in records)
    return {
        "status":"PASS",
        "record_count":total,
        "pre_registered_rate":prereg/total if total else 0.0,
        "reversal_rate":reversals/total if total else 0.0,
        "high_risk_escalation_count":escalations,
        "thirty_day_effectiveness":"NOT VERIFIED",
        "ninety_day_effectiveness":"NOT VERIFIED",
        "reason":"elapsed real-world evidence is required; software execution cannot substitute"
    }
