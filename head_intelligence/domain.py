from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    source_type: str = "official_rss"
    quality: float = 1.0
    enabled: bool = True


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    source_name: str
    url: str
    fetched_at: str
    http_status: int
    content_type: str
    payload_hash: str
    payload: bytes


@dataclass
class InformationItem:
    source_id: str
    source_name: str
    title: str
    link: str
    published_at: str
    summary: str
    content_hash: str
    source_quality: float
    freshness: float
    novelty: float
    decision_relevance: float
    score: float
    evidence_status: str = "PRIMARY_SOURCE"
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    name: str
    status: str
    items: int
    http_status: int | None = None
    raw_hash: str = ""
    elapsed_ms: int | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UpdateReport:
    status: str
    generated_at: str
    snapshot_id: str
    source_health: list[dict[str, Any]]
    items: list[InformationItem]
    raw_count: int
    deduped_count: int
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = [item.to_dict() for item in self.items]
        return data
