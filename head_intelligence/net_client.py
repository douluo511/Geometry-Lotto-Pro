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
    retry_statuses: tuple[int, ...] = (408, 429, 500, 502, 503, 504)


class NetClient:
    """Strict fail-closed HTTPS client with ordered same-source fallbacks."""

    def __init__(
        self,
        policy: NetworkPolicy | None = None,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ):
        self.policy = policy or NetworkPolicy()
        if self.policy.connect_timeout <= 0 or self.policy.read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.policy.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.random_fn = random_fn

    def fetch(self, source: Source) -> RawDocument:
        urls = [source.url, *source.fallback_urls]
        if not urls:
            raise ValueError("source has no URL")

        attempts: list[dict] = []
        endpoint_errors: list[str] = []
        last_error: Exception | None = None

        for endpoint_index, url in enumerate(urls, 1):
            if not str(url).startswith("https://"):
                raise ValueError(f"production source must use HTTPS: {url}")

            for attempt in range(1, self.policy.max_attempts + 1):
                try:
                    response = self.session.get(
                        url,
                        timeout=(self.policy.connect_timeout, self.policy.read_timeout),
                        headers={
                            "User-Agent": "HeadIntelligence/0.4 (+https://github.com/douluo511/Geometry-Lotto-Pro)",
                            "Accept": "application/rss+xml, application/xml, text/xml, */*",
                        },
                        allow_redirects=True,
                    )
                    status = int(getattr(response, "status_code", 0) or 0)
                    final_url = str(getattr(response, "url", "") or url)
                    if not final_url.startswith("https://"):
                        attempts.append({
                            "endpoint_index": endpoint_index,
                            "attempt": attempt,
                            "requested_url": url,
                            "final_url": final_url,
                            "status_code": status,
                            "outcome": "FINAL_INSECURE_REDIRECT",
                            "retry_delay": 0.0,
                        })
                        raise ValueError(f"HTTPS request redirected to non-HTTPS URL: {final_url}")

                    if status in self.policy.retry_statuses and attempt < self.policy.max_attempts:
                        delay = self._backoff(attempt)
                        attempts.append({
                            "endpoint_index": endpoint_index,
                            "attempt": attempt,
                            "requested_url": url,
                            "final_url": final_url,
                            "status_code": status,
                            "outcome": "RETRY_HTTP",
                            "retry_delay": delay,
                        })
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

                    attempts.append({
                        "endpoint_index": endpoint_index,
                        "attempt": attempt,
                        "requested_url": url,
                        "final_url": final_url,
                        "status_code": status,
                        "outcome": "HTTP_RESPONSE",
                        "retry_delay": 0.0,
                    })
                    return RawDocument(
                        source_id=source.id,
                        source_name=source.name,
                        url=url,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        http_status=status,
                        content_type=content_type,
                        payload_hash=hashlib.sha256(payload).hexdigest(),
                        payload=payload,
                        requested_url=url,
                        final_url=final_url,
                        attempts=list(attempts),
                    )
                except (requests.Timeout, requests.ConnectionError) as exc:
                    last_error = exc
                    if attempt < self.policy.max_attempts:
                        delay = self._backoff(attempt)
                        attempts.append({
                            "endpoint_index": endpoint_index,
                            "attempt": attempt,
                            "requested_url": url,
                            "final_url": url,
                            "status_code": None,
                            "outcome": "RETRY_EXCEPTION",
                            "error_type": type(exc).__name__,
                            "retry_delay": delay,
                        })
                        continue
                    attempts.append({
                        "endpoint_index": endpoint_index,
                        "attempt": attempt,
                        "requested_url": url,
                        "final_url": url,
                        "status_code": None,
                        "outcome": "FINAL_EXCEPTION",
                        "error_type": type(exc).__name__,
                        "retry_delay": 0.0,
                    })
                    break
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    if not attempts or attempts[-1].get("attempt") != attempt or attempts[-1].get("endpoint_index") != endpoint_index:
                        attempts.append({
                            "endpoint_index": endpoint_index,
                            "attempt": attempt,
                            "requested_url": url,
                            "final_url": str(getattr(locals().get("response", None), "url", "") or url),
                            "status_code": int(getattr(locals().get("response", None), "status_code", 0) or 0) or None,
                            "outcome": "FINAL_EXCEPTION",
                            "error_type": type(exc).__name__,
                            "retry_delay": 0.0,
                        })
                    break

            endpoint_errors.append(f"{url}: {type(last_error).__name__ if last_error else 'Unknown'}: {last_error}")

        if len(urls) == 1 and last_error is not None:
            try:
                setattr(last_error, "glp_attempts", tuple(attempts))
            except Exception:
                pass
            raise last_error

        exc = RuntimeError("all source endpoints failed: " + " | ".join(endpoint_errors))
        setattr(exc, "glp_attempts", tuple(attempts))
        raise exc

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + self.random_fn()
        delay = self.policy.base_backoff * (2 ** (attempt - 1)) * jitter
        self.sleeper(delay)
        return delay
