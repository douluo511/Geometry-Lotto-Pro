from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class MarketSeries:
    symbol: str
    rows: list[dict[str, Any]]
    provider: str
    source: dict[str, Any]

@dataclass(frozen=True)
class MacroPoint:
    series_id: str
    value: dict[str, Any]
    source: dict[str, Any]

@dataclass
class ResearchSnapshot:
    update_state: str
    metrics: dict[str, dict[str, Any]]
    ranking: list[dict[str, Any]]
    macro: dict[str, Any]
    providers: list[dict[str, Any]] = field(default_factory=list)

@dataclass(frozen=True)
class GateResult:
    gate_name: str
    status: str
    evidence: dict[str, Any]
