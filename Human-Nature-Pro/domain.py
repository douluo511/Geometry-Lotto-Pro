from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Case:
    text: str

@dataclass(frozen=True)
class Goal:
    text: str

@dataclass(frozen=True)
class Observation:
    text: str
    kind: str = "observed"

@dataclass(frozen=True)
class EvidenceItem:
    text: str
    direction: str
    weight: float = 0.0

@dataclass
class HumanState:
    values: dict[str, Any] = field(default_factory=dict)

@dataclass
class Hypothesis:
    name: str
    score: float
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)

@dataclass
class Strategy:
    name: str
    action: str
    metrics: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class Risk:
    name: str
    level: str
    mitigation: str

@dataclass
class AnalysisResult:
    payload: dict[str, Any]

@dataclass(frozen=True)
class UpdateResult:
    status: str
    knowledge_version: str
    source: dict[str, Any]

@dataclass(frozen=True)
class RepairResult:
    status: str
    action: str
    path: str

@dataclass(frozen=True)
class AuditRecord:
    type: str
    status: str
    timestamp: str
    details: dict[str, Any]
