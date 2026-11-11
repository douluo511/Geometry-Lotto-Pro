from __future__ import annotations
from dataclasses import dataclass, asdict

ALLOWED_STYLES={"ambient","pop","cinematic","lofi","electronic"}
ALLOWED_KEYS={"C","D","E","F","G","A","B"}

@dataclass(frozen=True)
class CompositionRequest:
    title:str="New Track"
    style:str="ambient"
    key:str="C"
    bpm:int=90
    duration_seconds:int=8
    seed:int=42

    def validate(self)->"CompositionRequest":
        if not self.title.strip():
            raise ValueError("title required")
        if self.style not in ALLOWED_STYLES:
            raise ValueError("unsupported style")
        if self.key not in ALLOWED_KEYS:
            raise ValueError("unsupported key")
        if not (40<=int(self.bpm)<=220):
            raise ValueError("bpm out of range")
        if not (2<=int(self.duration_seconds)<=120):
            raise ValueError("duration out of range")
        if not isinstance(self.seed,int):
            raise ValueError("seed must be int")
        return self

    def to_dict(self)->dict:
        return asdict(self)
