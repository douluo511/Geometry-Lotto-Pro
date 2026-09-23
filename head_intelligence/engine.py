from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests

from head_intelligence.models import InformationItem, Source, UpdateReport


APP_NAME = "HeadIntelligence"
USER_AGENT = "HeadIntelligence/0.1 (+https://github.com/douluo511/Geometry-Lotto-Pro)"

DEFAULT_SOURCES = [
    Source(
        id="federal_reserve_press",
        name="Federal Reserve Board - Press Releases",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        quality=1.0,
    ),
    Source(
        id="sec_press",
        name="U.S. SEC - Press Releases",
        url="https://www.sec.gov/news/pressreleases.rss",
        quality=1.0,
    ),
]


class InformationEngine:
    def __init__(self, data_dir: Path | None = None, sources: list[Source] | None = None):
        if data_dir is None:
            local = os.environ.get("LOCALAPPDATA")
            base = Path(local) if local else Path.home()
            data_dir = base / APP_NAME
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.data_dir / "latest_snapshot.json"
        self.sources = sources or list(DEFAULT_SOURCES)

    def one_click_update(self, limit_per_source: int = 40) -> UpdateReport:
        enabled = [s for s in self.sources if s.enabled]
        source_health: list[dict] = []
        fetched: list[InformationItem] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=max(1, min(8, len(enabled)))) as pool:
            futures = {pool.submit(self._fetch_source, source, limit_per_source): source for source in enabled}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    items, health = future.result()
                    fetched.extend(items)
                    source_health.append(health)
                except Exception as exc:
                    msg = f"{source.name}: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    source_health.append({
                        "source_id": source.id,
                        "name": source.name,
                        "status": "FAIL",
                        "items": 0,
                        "error": msg,
                    })

        deduped = self._deduplicate(fetched)
        ranked = sorted(deduped, key=lambda x: x.score, reverse=True)
        now = datetime.now(timezone.utc).isoformat()
        snapshot_seed = "|".join(item.content_hash for item in ranked) + "|" + now
        snapshot_id = hashlib.sha256(snapshot_seed.encode("utf-8")).hexdigest()[:16]
        status = "PASS" if ranked and any(h.get("status") == "PASS" for h in source_health) else "FAIL"

        report = UpdateReport(
            status=status,
            generated_at=now,
            snapshot_id=snapshot_id,
            source_health=sorted(source_health, key=lambda x: x.get("source_id", "")),
            items=ranked,
            raw_count=len(fetched),
            deduped_count=len(ranked),
            errors=errors,
        )
        if status == "PASS":
            self._atomic_write_json(self.snapshot_path, report.to_dict())
        return report

    def health_check(self) -> dict:
        checks = {
            "data_dir_exists": self.data_dir.exists(),
            "data_dir_writable": os.access(self.data_dir, os.W_OK),
            "sources_configured": bool([s for s in self.sources if s.enabled]),
            "snapshot_readable": True,
        }
        if self.snapshot_path.exists():
            try:
                json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                checks["snapshot_readable"] = False
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "data_dir": str(self.data_dir),
        }

    def load_latest_snapshot(self) -> dict | None:
        if not self.snapshot_path.exists():
            return None
        try:
            return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def self_test(self) -> dict:
        fixture = [
            self._make_item(
                source=DEFAULT_SOURCES[0],
                title="Federal Reserve announces test release",
                link="https://example.test/a",
                published_at=datetime.now(timezone.utc).isoformat(),
                summary="Official test item.",
            ),
            self._make_item(
                source=DEFAULT_SOURCES[0],
                title="Federal Reserve announces test release",
                link="https://example.test/a2",
                published_at=datetime.now(timezone.utc).isoformat(),
                summary="Duplicate title.",
            ),
        ]
        deduped = self._deduplicate(fixture)
        ok = len(deduped) == 1 and deduped[0].score >= 0 and self.health_check()["status"] == "PASS"
        result = {
            "status": "PASS" if ok else "FAIL",
            "deduplication": len(deduped) == 1,
            "health": self.health_check(),
        }
        self._atomic_write_json(self.data_dir / "self_test.json", result)
        return result

    def _fetch_source(self, source: Source, limit: int) -> tuple[list[InformationItem], dict]:
        started = time.perf_counter()
        response = requests.get(
            source.url,
            timeout=(8, 20),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        response.raise_for_status()
        raw_hash = hashlib.sha256(response.content).hexdigest()
        raw_path = self.raw_dir / f"{source.id}_{raw_hash[:12]}.xml"
        if not raw_path.exists():
            raw_path.write_bytes(response.content)

        parsed = feedparser.parse(response.content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(f"RSS parse failed: {getattr(parsed, 'bozo_exception', 'unknown')}")

        items: list[InformationItem] = []
        for entry in parsed.entries[:limit]:
            title = self._clean_text(entry.get("title", ""))
            link = str(entry.get("link", "")).strip()
            summary = self._clean_text(entry.get("summary", entry.get("description", "")))
            published_at = self._entry_time(entry)
            if not title:
                continue
            items.append(
                self._make_item(
                    source=source,
                    title=title,
                    link=link,
                    published_at=published_at,
                    summary=summary,
                )
            )

        return items, {
            "source_id": source.id,
            "name": source.name,
            "status": "PASS" if items else "FAIL",
            "items": len(items),
            "http_status": response.status_code,
            "raw_hash": raw_hash,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }

    def _make_item(self, source: Source, title: str, link: str, published_at: str, summary: str) -> InformationItem:
        normalized_title = self._normalize_title(title)
        content_hash = hashlib.sha256(
            f"{source.id}|{normalized_title}|{link}|{published_at}".encode("utf-8")
        ).hexdigest()
        freshness = self._freshness_score(published_at)
        novelty = 1.0
        relevance = self._decision_relevance(title + " " + summary)
        score = round(
            100.0 * (
                0.38 * self._clamp(source.quality)
                + 0.24 * freshness
                + 0.18 * novelty
                + 0.20 * relevance
            ),
            2,
        )
        return InformationItem(
            source_id=source.id,
            source_name=source.name,
            title=title,
            link=link,
            published_at=published_at,
            summary=summary[:900],
            content_hash=content_hash,
            source_quality=self._clamp(source.quality),
            freshness=freshness,
            novelty=novelty,
            decision_relevance=relevance,
            score=score,
        )

    def _deduplicate(self, items: Iterable[InformationItem]) -> list[InformationItem]:
        best_by_title: dict[str, InformationItem] = {}
        for item in items:
            key = self._normalize_title(item.title)
            current = best_by_title.get(key)
            if current is None or item.score > current.score:
                best_by_title[key] = item
        return list(best_by_title.values())

    @staticmethod
    def _normalize_title(text: str) -> str:
        text = html.unescape(text).lower()
        text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _clean_text(text: str) -> str:
        text = html.unescape(str(text))
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _entry_time(entry) -> str:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _freshness_score(published_at: str) -> float:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = max(
                0.0,
                (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400,
            )
            return round(math.exp(-days / 14.0), 4)
        except Exception:
            return 0.25

    @staticmethod
    def _decision_relevance(text: str) -> float:
        keywords = {
            "rate", "rates", "policy", "regulation", "rule", "enforcement",
            "market", "capital", "bank", "inflation", "employment", "fraud",
            "trading", "securities", "liquidity", "risk", "interest",
            "政策", "利率", "监管", "市场", "资本", "风险", "通胀", "就业",
        }
        normalized = text.lower()
        hits = sum(1 for word in keywords if word in normalized)
        return round(min(1.0, 0.25 + hits * 0.11), 4)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
