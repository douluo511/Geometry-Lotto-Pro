from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Draw:
    issue: str
    draw_date: str
    front: tuple[int, int, int, int, int]
    back: tuple[int, int]

    def validate(self) -> None:
        if type(self.issue) is not str or len(self.issue) != 5 or not self.issue.isascii() or not self.issue.isdigit():
            raise ValueError(f"非法期号: {self.issue}")
        if type(self.draw_date) is not str or len(self.draw_date) != 10:
            raise ValueError(f"开奖日期非法: {self.draw_date}")
        try:
            parsed_date = date.fromisoformat(self.draw_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"开奖日期非法: {self.draw_date}") from exc
        if parsed_date.isoformat() != self.draw_date:
            raise ValueError(f"开奖日期非法: {self.draw_date}")
        if type(self.front) is not tuple or type(self.back) is not tuple:
            raise ValueError("开奖号码容器必须为 tuple")
        if not all(type(n) is int for n in self.front):
            raise ValueError(f"前区号码类型非法: {self.front}")
        if not all(type(n) is int for n in self.back):
            raise ValueError(f"后区号码类型非法: {self.back}")
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
        if type(value) is not dict:
            raise ValueError("Draw payload 必须为 object")
        required = ("issue", "draw_date", "front", "back")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"Draw payload 缺少字段: {missing}")
        if type(value["issue"]) is not str:
            raise ValueError("issue 必须是字符串，禁止隐式转换")
        if type(value["draw_date"]) is not str:
            raise ValueError("draw_date 必须是字符串，禁止隐式转换")
        if type(value["front"]) not in {list, tuple}:
            raise ValueError("front 必须是数组")
        if type(value["back"]) not in {list, tuple}:
            raise ValueError("back 必须是数组")
        if not all(type(x) is int for x in value["front"]):
            raise ValueError("front 号码必须是整数，禁止 bool/float/string 隐式转换")
        if not all(type(x) is int for x in value["back"]):
            raise ValueError("back 号码必须是整数，禁止 bool/float/string 隐式转换")
        obj = cls(
            issue=value["issue"],
            draw_date=value["draw_date"],
            front=tuple(value["front"]),
            back=tuple(value["back"]),
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
