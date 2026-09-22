from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Draw:
    issue: str
    draw_date: str
    front: tuple[int, int, int, int, int]
    back: tuple[int, int]

    def validate(self) -> None:
        if len(self.issue) != 5 or not self.issue.isdigit():
            raise ValueError(f"非法期号: {self.issue}")
        if len(self.front) != 5 or tuple(sorted(self.front)) != self.front or len(set(self.front)) != 5:
            raise ValueError(f"前区号码非法: {self.front}")
        if len(self.back) != 2 or tuple(sorted(self.back)) != self.back or len(set(self.back)) != 2:
            raise ValueError(f"后区号码非法: {self.back}")
        if not all(1 <= n <= 35 for n in self.front):
            raise ValueError(f"前区越界: {self.front}")
        if not all(1 <= n <= 12 for n in self.back):
            raise ValueError(f"后区越界: {self.back}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["front"] = list(self.front)
        d["back"] = list(self.back)
        return d

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Draw":
        obj = cls(
            issue=str(value["issue"]),
            draw_date=str(value["draw_date"]),
            front=tuple(int(x) for x in value["front"]),
            back=tuple(int(x) for x in value["back"]),
        )
        obj.validate()
        return obj


@dataclass(frozen=True)
class SourceReceipt:
    source: str
    fetched_at: str
    http_status: int
    raw_sha256: str
    draw_count: int
    latest_issue: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class CanonicalDataset:
    draws: list[Draw]
    canonical_hash: str
    receipts: list[SourceReceipt]
    crosscheck_count: int
    crosscheck_status: str


@dataclass(frozen=True)
class Ranking:
    numbers: list[int]
    scores: dict[int, float]
    feature_scores: dict[str, dict[int, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    target_issue: str
    target_date: str
    created_at: str
    front: list[int]
    back: list[int]
    front_ranking: list[int]
    back_ranking: list[int]
    dan_state: str
    edge_state: str
    research_dan_front: list[int]
    research_dan_back: list[int]
    canonical_hash: str
    model_hash: str
    selector_hash: str
    score_hash: str
    freeze_hash: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
