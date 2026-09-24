from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Observation:
    label: str
    detail: str
    strength: float = 0.5


@dataclass(frozen=True)
class Evidence:
    text: str
    direction: str
    weight: float


@dataclass
class Hypothesis:
    key: str
    name: str
    explanation: str
    score: float = 0.0
    confidence: float = 0.0
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class AnalysisResult:
    observations: List[Observation]
    hypotheses: List[Hypothesis]
    five_whys: List[str]
    reverse_validation: List[str]
    consistency_notes: List[str]
    guidance: List[str]
    overall_confidence: str
    disclaimer: str


@dataclass(frozen=True)
class SourceRecord:
    url: str
    fetched_at: str
    http_status: int
    sha256: str
    bytes_count: int


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message: str
    version: str
    source: SourceRecord | None = None
