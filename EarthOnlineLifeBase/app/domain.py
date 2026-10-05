from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

EVIDENCE_GRADES = {"A","B","C","D","UNKNOWN"}
DIMENSIONS = ("history","power","economics","execution","philosophy")

@dataclass
class DecisionInput:
    question: str
    facts: list[str]
    interpretations: list[str]
    unknowns: list[str]
    evidence_grade: str
    dimensions: dict[str,str]
    five_why: list[str]
    reversal_hypothesis: str
    falsifying_signals: list[str]
    options: list[dict[str,Any]]
    small_action: str
    stop_condition: str

    def validate(self) -> None:
        if not self.question.strip(): raise ValueError("question required")
        if not self.facts: raise ValueError("at least one fact required")
        if self.evidence_grade not in EVIDENCE_GRADES: raise ValueError("invalid evidence grade")
        if set(self.dimensions) != set(DIMENSIONS): raise ValueError("all five dimensions required")
        if len([x for x in self.five_why if str(x).strip()]) < 3: raise ValueError("at least three Why layers required")
        if not self.reversal_hypothesis.strip() or not self.falsifying_signals:
            raise ValueError("reversal validation required")
        if not self.options or not self.small_action.strip() or not self.stop_condition.strip():
            raise ValueError("options/action/stop condition required")

@dataclass
class DecisionRecord:
    record_id: str
    created_at: str
    input: dict[str,Any]
    status: str
    warnings: list[str] = field(default_factory=list)
    review: dict[str,Any] | None = None

    @classmethod
    def now(cls, record_id: str, inp: DecisionInput, status: str, warnings: list[str]):
        return cls(record_id, datetime.now(timezone.utc).isoformat(), asdict(inp), status, warnings)
