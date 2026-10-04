from __future__ import annotations
from dataclasses import asdict,dataclass
import math

DIMENSIONS=("history","power","economics","execution","philosophy")
HIGH_RISK={"health","investment","politics","law"}

def clean(v,name,required=True,max_len=4000):
    v=str(v or "").strip()
    if required and not v:raise ValueError(f"{name} required")
    if len(v)>max_len:raise ValueError(f"{name} too long")
    return v

@dataclass(frozen=True)
class DecisionCard:
    problem:str
    goal:str
    facts:tuple[str,...]
    unknowns:tuple[str,...]
    interpretation:str
    dimensions:dict
    prediction:str
    confidence:float
    worst_case:str
    reversible:bool
    next_action:str
    stop_condition:str
    risk_domain:str="normal"

    def validate(self):
        for n in ("problem","goal","interpretation","prediction","worst_case","next_action","stop_condition"):clean(getattr(self,n),n)
        if not self.facts or any(not clean(x,"fact") for x in self.facts):raise ValueError("facts required")
        if not isinstance(self.dimensions,dict) or set(self.dimensions)!=set(DIMENSIONS):raise ValueError("five dimensions required")
        for k,v in self.dimensions.items():clean(v,k)
        if isinstance(self.confidence,bool) or not isinstance(self.confidence,(int,float)) or not math.isfinite(float(self.confidence)) or not 0<=float(self.confidence)<=1:raise ValueError("confidence")
        if self.risk_domain not in HIGH_RISK|{"normal"}:raise ValueError("risk_domain")
        return self
    def to_dict(self):return asdict(self)
