from __future__ import annotations
from dataclasses import asdict, dataclass
import math

def text(v,name,required=True,max_len=3000):
    v=str(v or "").strip()
    if required and not v: raise ValueError(f"{name} required")
    if len(v)>max_len: raise ValueError(f"{name} too long")
    return v

def finite_nonneg(v,name):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) or float(v)<0:
        raise ValueError(f"{name} must be finite nonnegative")
    return float(v)

@dataclass(frozen=True)
class ExperimentInput:
    project:str
    customer_problem:str
    payer:str
    hypothesis:str
    strongest_failure_case:str
    max_loss:float
    timebox_days:int
    price:float
    variable_cost:float
    acquisition_cost:float
    owner_hours:float
    real_payments:int=0
    repeat_payments:int=0

    def validate(self):
        for name in ("project","customer_problem","payer","hypothesis","strongest_failure_case"):
            text(getattr(self,name),name)
        finite_nonneg(self.max_loss,"max_loss"); finite_nonneg(self.price,"price"); finite_nonneg(self.variable_cost,"variable_cost"); finite_nonneg(self.acquisition_cost,"acquisition_cost"); finite_nonneg(self.owner_hours,"owner_hours")
        if type(self.timebox_days) is not int or self.timebox_days<=0: raise ValueError("timebox_days must be positive int")
        if type(self.real_payments) is not int or self.real_payments<0: raise ValueError("real_payments")
        if type(self.repeat_payments) is not int or self.repeat_payments<0 or self.repeat_payments>self.real_payments: raise ValueError("repeat_payments")
        return self

    def to_dict(self): return asdict(self)
