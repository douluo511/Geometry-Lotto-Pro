from __future__ import annotations

import html
import math
import re
from datetime import datetime, timezone
from typing import Iterable

from head_intelligence.domain import InformationItem, Source


class EvidenceEngine:
    DECISION_KEYWORDS = {
        "rate", "rates", "policy", "regulation", "rule", "enforcement",
        "market", "capital", "bank", "inflation", "employment", "fraud",
        "trading", "securities", "liquidity", "risk", "interest",
        "政策", "利率", "监管", "市场", "资本", "风险", "通胀", "就业",
    }

    def normalize_title(self, text: str) -> str:
        text = html.unescape(text).lower()
        text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def clean_text(self, text: str) -> str:
        text = html.unescape(str(text))
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def deduplicate(self, items: Iterable[InformationItem]) -> list[InformationItem]:
        best: dict[str, InformationItem] = {}
        for item in items:
            key = self.normalize_title(item.title)
            current = best.get(key)
            if current is None or item.score > current.score:
                best[key] = item
        return list(best.values())

    def freshness_score(self, published_at: str) -> float:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = max(
                0.0,
                (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400,
            )
            return round(math.exp(-age_days / 14.0), 4)
        except Exception:
            return 0.25

    def decision_relevance(self, text: str) -> float:
        normalized = text.lower()
        hits = sum(1 for word in self.DECISION_KEYWORDS if word in normalized)
        return round(min(1.0, 0.25 + hits * 0.11), 4)

    def rank_score(self, source: Source, freshness: float, relevance: float, novelty: float = 1.0) -> float:
        quality = max(0.0, min(1.0, float(source.quality)))
        return round(
            100.0 * (
                0.38 * quality
                + 0.24 * freshness
                + 0.18 * novelty
                + 0.20 * relevance
            ),
            2,
        )
