from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import requests

from head_intelligence.domain import RawDocument, Source


@dataclass(frozen=True)
class NetworkPolicy:
    connect_timeout: float = 8.0
    read_timeout: float = 20.0
    max_attempts: int = 3
    base_backoff: float = 0.35
    max_payload_bytes: int = 8 * 1024 * 1024
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class NetClient:
    def __init__(
        self,
        policy: NetworkPolicy | None = None,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ):
        self.policy = policy or NetworkPolicy()
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.random_fn = random_fn

    def fetch(self, source: Source) -> RawDocument:
        last_error: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                response = self.session.get(
                    source.url,
                    timeout=(self.policy.connect_timeout, self.policy.read_timeout),
                    headers={
                        "User-Agent": "HeadIntelligence/0.2 (+https://github.com/douluo511/Geometry-Lotto-Pro)",
                        "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    },
                )
                if response.status_code in self.policy.retry_statuses and attempt < self.policy.max_attempts:
                    self._backoff(attempt)
                    continue
                response.raise_for_status()
                payload = bytes(response.content)
                if not payload:
                    raise ValueError("empty payload")
                if len(payload) > self.policy.max_payload_bytes:
                    raise ValueError("payload too large")
                content_type = (response.headers.get("Content-Type") or "").lower()
                if content_type and not any(x in content_type for x in ("xml", "rss", "atom", "text")):
                    raise ValueError(f"unexpected content type: {content_type}")
                return RawDocument(
                    source_id=source.id,
                    source_name=source.name,
                    url=source.url,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    http_status=response.status_code,
                    content_type=content_type,
                    payload_hash=hashlib.sha256(payload).hexdigest(),
                    payload=payload,
                )
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.policy.max_attempts:
                    break
                self._backoff(attempt)
        assert last_error is not None
        raise last_error

    def _backoff(self, attempt: int) -> None:
        jitter = 0.5 + self.random_fn()
        self.sleeper(self.policy.base_backoff * (2 ** (attempt - 1)) * jitter)
