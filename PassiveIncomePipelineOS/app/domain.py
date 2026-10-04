from __future__ import annotations
from dataclasses import asdict,dataclass
import math,re

def clean(v,name,required=True,max_len=3000):
    v=str(v or "").strip()
    if required and not v: raise ValueError(f"{name} required")
    if len(v)>max_len: raise ValueError(f"{name} too long")
    return v

def amount(v,name):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) or float(v)<0:
        raise ValueError(f"{name} must be finite nonnegative")
    return float(v)

@dataclass(frozen=True)
class PipelineDefinition:
    pipeline_id:str
    name:str
    value_proposition:str
    connector_url:str
    expected_revenue:float
    variable_cost:float
    owner_minutes:float
    max_loss:float
    enabled:bool=False
    real_customer_actions:int=0
    real_payments:int=0
    repeated_payments:int=0

    def validate(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}",clean(self.pipeline_id,"pipeline_id")):
            raise ValueError("invalid pipeline_id")
        for x in ("name","value_proposition","connector_url"):clean(getattr(self,x),x)
        if not self.connector_url.startswith("https://"):raise ValueError("HTTPS connector required")
        for x in ("expected_revenue","variable_cost","owner_minutes","max_loss"):amount(getattr(self,x),x)
        for x in ("real_customer_actions","real_payments","repeated_payments"):
            if type(getattr(self,x)) is not int or getattr(self,x)<0:raise ValueError(x)
        if self.repeated_payments>self.real_payments:raise ValueError("repeat > payments")
        return self
    def to_dict(self):return asdict(self)
