from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math

HIGH_RISK={"health","legal","physical_safety","large_financial_commitment"}

def clean(value: str, name: str, required: bool=True, max_len: int=4000) -> str:
    value=str(value or "").strip()
    if required and not value:
        raise ValueError(f"{name} required")
    if len(value)>max_len:
        raise ValueError(f"{name} too long")
    return value

@dataclass(frozen=True)
class DecisionInput:
    problem: str
    facts: tuple[str,...]
    interpretation: str
    prediction: str
    confidence: float
    max_loss: str
    stop_line: str
    reversible_action: str
    risk_category: str="normal"

    def validate(self) -> "DecisionInput":
        clean(self.problem,"problem")
        if not self.facts or any(not clean(x,"fact") for x in self.facts):
            raise ValueError("at least one fact required")
        clean(self.interpretation,"interpretation")
        clean(self.prediction,"prediction")
        if isinstance(self.confidence,bool) or not isinstance(self.confidence,(int,float)) or not math.isfinite(float(self.confidence)) or not 0<=float(self.confidence)<=1:
            raise ValueError("confidence must be finite in [0,1]")
        clean(self.max_loss,"max_loss")
        clean(self.stop_line,"stop_line")
        clean(self.reversible_action,"reversible_action")
        if self.risk_category not in HIGH_RISK|{"normal"}:
            raise ValueError("unsupported risk_category")
        return self

@dataclass(frozen=True)
class TrainingResult:
    record_id: str
    created_at: str
    problem: str
    facts: tuple[str,...]
    interpretation: str
    five_why: tuple[dict,...]
    reversal: dict
    prediction: str
    confidence: float
    max_loss: str
    stop_line: str
    reversible_action: str
    risk_category: str
    escalation_required: bool
    effectiveness_claim: str="NOT VERIFIED"

    def to_dict(self)->dict:
        return asdict(self)

def new_record_id(problem: str) -> str:
    import hashlib
    stamp=datetime.now(timezone.utc).isoformat()
    return hashlib.sha256((stamp+"|"+problem).encode("utf-8")).hexdigest()[:24]
