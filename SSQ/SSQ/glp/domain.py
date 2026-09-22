from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(frozen=True)
class Draw:
    issue: str
    draw_date: str
    front: tuple[int, ...]
    back: tuple[int, ...]
    def validate(self) -> None:
        if len(self.issue) != 7 or not self.issue.isdigit() or not self.issue.startswith('20'):
            raise ValueError(f'非法双色球期号: {self.issue}')
        if len(self.front) != 6 or tuple(sorted(self.front)) != self.front or len(set(self.front)) != 6:
            raise ValueError(f'红球非法: {self.front}')
        if len(self.back) != 1 or len(set(self.back)) != 1:
            raise ValueError(f'蓝球非法: {self.back}')
        if not all(1 <= n <= 33 for n in self.front):
            raise ValueError(f'红球越界: {self.front}')
        if not all(1 <= n <= 16 for n in self.back):
            raise ValueError(f'蓝球越界: {self.back}')
    def to_dict(self) -> dict[str, Any]:
        return {'issue': self.issue, 'draw_date': self.draw_date, 'front': list(self.front), 'back': list(self.back)}
    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> 'Draw':
        obj=cls(str(value['issue']), str(value['draw_date']), tuple(int(x) for x in value['front']), tuple(int(x) for x in value['back']))
        obj.validate(); return obj

@dataclass(frozen=True)
class SourceReceipt:
    source: str; fetched_at: str; http_status: int; raw_sha256: str; draw_count: int; latest_issue: str; status: str; detail: str=''

@dataclass(frozen=True)
class CanonicalDataset:
    draws: list[Draw]; canonical_hash: str; receipts: list[SourceReceipt]; crosscheck_count: int; crosscheck_status: str

@dataclass(frozen=True)
class Ranking:
    numbers: tuple[int, ...]
    scores: tuple[float, ...]
    feature_scores: dict[str, list[float]] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]:
        return {'numbers': list(self.numbers), 'scores': list(self.scores), 'feature_scores': self.feature_scores}

@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    target_issue: str
    target_date: str
    created_at: str
    front: list[int]
    back: list[int]
    canonical_hash: str
    front_ranking: Ranking
    back_ranking: Ranking
    dan_state: str
    edge_state: str
    research_dan_front: tuple[int, ...]
    research_dan_back: tuple[int, ...]
    model_hash: str
    selector_hash: str
    score_hash: str
    freeze_hash: str=''
    note: str=''
    def to_dict(self) -> dict[str, Any]:
        return {
            'prediction_id': self.prediction_id, 'target_issue': self.target_issue, 'target_date': self.target_date,
            'created_at': self.created_at, 'front': list(self.front), 'back': list(self.back),
            'canonical_hash': self.canonical_hash, 'front_ranking': self.front_ranking.to_dict(),
            'back_ranking': self.back_ranking.to_dict(), 'dan_state': self.dan_state, 'edge_state': self.edge_state,
            'research_dan_front': list(self.research_dan_front), 'research_dan_back': list(self.research_dan_back),
            'model_hash': self.model_hash, 'selector_hash': self.selector_hash, 'score_hash': self.score_hash,
            'freeze_hash': self.freeze_hash, 'note': self.note,
        }
