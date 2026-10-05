from __future__ import annotations
import hashlib, json
from .domain import DecisionInput, DecisionRecord

HIGH_RISK=("health","medical","investment","securities","law","legal","politics","政治","法律","投资","健康","医疗")

def analyze(inp:DecisionInput)->DecisionRecord:
    inp.validate()
    text=" ".join([inp.question,*inp.facts,*inp.interpretations]).lower()
    warnings=[]
    if any(k in text for k in HIGH_RISK):
        warnings.append("HIGH_RISK_BOUNDARY: general decision training only; verify with first-party or licensed professional sources.")
    if len(inp.interpretations)>len(inp.facts)*2:
        warnings.append("INTERPRETATION_HEAVY: interpretations materially outnumber facts.")
    if inp.evidence_grade in {"D","UNKNOWN"}:
        warnings.append("LOW_EVIDENCE: prefer a reversible small action; do not escalate stakes.")
    rid=hashlib.sha256(json.dumps(inp.__dict__,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()[:24]
    return DecisionRecord.now(rid,inp,"PASS",warnings)

def reversal_score(inp:DecisionInput)->dict:
    inp.validate()
    return {
        "status":"PASS",
        "falsifying_signal_count":len(inp.falsifying_signals),
        "has_stop_condition":bool(inp.stop_condition.strip()),
        "rule":"A belief enters an important decision only when observable disconfirming signals and a stop condition exist."
    }
