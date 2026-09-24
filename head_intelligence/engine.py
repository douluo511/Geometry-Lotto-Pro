from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from head_intelligence.contracts import NetClientContract, StorageContract
from head_intelligence.domain import InformationItem, Source, SourceHealth, UpdateReport
from head_intelligence.evidence import EvidenceEngine
from head_intelligence.net_client import NetClient
from head_intelligence.storage import AtomicStorage


APP_NAME = "HeadIntelligence"
SNAPSHOT_FILE = "latest_snapshot.json"

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
    def __init__(
        self,
        data_dir: Path | None = None,
        sources: list[Source] | None = None,
        net_client: NetClientContract | None = None,
        storage: StorageContract | None = None,
        evidence: EvidenceEngine | None = None,
    ):
        if storage is None:
            if data_dir is None:
                local = os.environ.get("LOCALAPPDATA")
                base = Path(local) if local else Path.home()
                data_dir = base / APP_NAME
            storage = AtomicStorage(Path(data_dir))
        self.storage = storage
        self.data_dir = storage.data_dir
        self.sources = sources or list(DEFAULT_SOURCES)
        self.net_client = net_client or NetClient()
        self.evidence = evidence or EvidenceEngine()

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
                    source_health.append(health.to_dict())
                except Exception as exc:
                    msg = f"{source.name}: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    source_health.append(
                        SourceHealth(
                            source_id=source.id,
                            name=source.name,
                            status="FAIL",
                            items=0,
                            error=msg,
                        ).to_dict()
                    )

        deduped = self.evidence.deduplicate(fetched)
        ranked = sorted(deduped, key=lambda x: x.score, reverse=True)
        now = datetime.now(timezone.utc).isoformat()
        snapshot_seed = "|".join(item.content_hash for item in ranked) + "|" + now
        snapshot_id = hashlib.sha256(snapshot_seed.encode("utf-8")).hexdigest()[:16]

        any_source_pass = any(h.get("status") == "PASS" for h in source_health)
        status = "PASS" if ranked and any_source_pass else "FAIL"

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

        # Hard rule: a failed update never overwrites the last known-good snapshot.
        if status == "PASS":
            self.storage.save_json_atomic(SNAPSHOT_FILE, report.to_dict())
        return report

    def health_check(self) -> dict:
        snapshot_path = self.data_dir / SNAPSHOT_FILE
        snapshot_readable = True
        if snapshot_path.exists() and self.storage.read_json(SNAPSHOT_FILE) is None:
            snapshot_readable = False

        checks = {
            "data_dir_exists": self.data_dir.exists(),
            "data_dir_writable": os.access(self.data_dir, os.W_OK),
            "sources_configured": bool([s for s in self.sources if s.enabled]),
            "snapshot_readable": snapshot_readable,
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "data_dir": str(self.data_dir),
        }

    def load_latest_snapshot(self) -> dict | None:
        return self.storage.read_json(SNAPSHOT_FILE)

    def self_test(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        fixture = [
            self._make_item(
                source=DEFAULT_SOURCES[0],
                title="Federal Reserve announces test release",
                link="https://example.test/a",
                published_at=now,
                summary="Official test item.",
            ),
            self._make_item(
                source=DEFAULT_SOURCES[0],
                title="Federal Reserve announces test release",
                link="https://example.test/a2",
                published_at=now,
                summary="Duplicate title.",
            ),
        ]
        deduped = self.evidence.deduplicate(fixture)
        probe = {"probe": "atomic-storage", "at": now}
        self.storage.save_json_atomic("self_test_probe.json", probe)
        round_trip = self.storage.read_json("self_test_probe.json") == probe
        health = self.health_check()
        checks = {
            "deduplication": len(deduped) == 1,
            "ranking_nonnegative": bool(deduped) and deduped[0].score >= 0,
            "storage_round_trip": round_trip,
            "health": health["status"] == "PASS",
        }
        result = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "health": health,
        }
        self.storage.save_json_atomic("self_test.json", result)
        return result

    def _fetch_source(self, source: Source, limit: int) -> tuple[list[InformationItem], SourceHealth]:
        started = time.perf_counter()
        document = self.net_client.fetch(source)
        self.storage.save_raw(document)

        parsed = feedparser.parse(document.payload)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(f"RSS parse failed: {getattr(parsed, 'bozo_exception', 'unknown')}")

        items: list[InformationItem] = []
        for entry in parsed.entries[:limit]:
            title = self.evidence.clean_text(entry.get("title", ""))
            link = str(entry.get("link", "")).strip()
            summary = self.evidence.clean_text(entry.get("summary", entry.get("description", "")))
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

        health = SourceHealth(
            source_id=source.id,
            name=source.name,
            status="PASS" if items else "FAIL",
            items=len(items),
            http_status=document.http_status,
            raw_hash=document.payload_hash,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
        return items, health

    def _make_item(
        self,
        source: Source,
        title: str,
        link: str,
        published_at: str,
        summary: str,
    ) -> InformationItem:
        normalized_title = self.evidence.normalize_title(title)
        content_hash = hashlib.sha256(
            f"{source.id}|{normalized_title}|{link}|{published_at}".encode("utf-8")
        ).hexdigest()
        freshness = self.evidence.freshness_score(published_at)
        relevance = self.evidence.decision_relevance(title + " " + summary)
        novelty = 1.0
        score = self.evidence.rank_score(source, freshness, relevance, novelty)
        return InformationItem(
            source_id=source.id,
            source_name=source.name,
            title=title,
            link=link,
            published_at=published_at,
            summary=summary[:900],
            content_hash=content_hash,
            source_quality=max(0.0, min(1.0, source.quality)),
            freshness=freshness,
            novelty=novelty,
            decision_relevance=relevance,
            score=score,
            evidence_status="PRIMARY_SOURCE",
        )

    @staticmethod
    def _entry_time(entry) -> str:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
        return datetime.now(timezone.utc).isoformat()
