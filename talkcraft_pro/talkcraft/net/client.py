from __future__ import annotations

import base64
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests


RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


@dataclass
class NetResult:
    ok: bool
    requested_url: str
    final_url: str
    status: int
    content_type: str
    sha256: str
    size: int
    elapsed_ms: int
    body_b64: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def url(self) -> str:
        return self.final_url or self.requested_url


class NetClient:
    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_attempts: int = 3,
        max_bytes: int = 1_500_000,
        user_agent: str = "TalkCraftPro/1.1",
        session: requests.Session | None = None,
        sleeper=time.sleep,
        rng: random.Random | None = None,
    ):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("timeouts_must_be_positive")
        if max_attempts < 1:
            raise ValueError("max_attempts_must_be_at_least_1")
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = int(max_attempts)
        self.max_bytes = int(max_bytes)
        self.ua = user_agent
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.rng = rng or random.Random()

    @staticmethod
    def _https(url: str) -> bool:
        return urlparse(url).scheme.lower() == "https"

    def _delay(self, attempt: int) -> float:
        return (0.35 * (2 ** max(0, attempt - 1))) + self.rng.uniform(0.0, 0.15)

    def get(self, url: str) -> NetResult:
        if not self._https(url):
            raise ValueError("https_required")

        started = time.time()
        attempts: list[dict[str, Any]] = []
        last_error = ""

        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.session.get(
                    url,
                    headers={
                        "User-Agent": self.ua,
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                    stream=True,
                ) as r:
                    final_url = str(r.url)
                    status = int(r.status_code)
                    if not self._https(final_url):
                        attempts.append({
                            "attempt": attempt,
                            "outcome": "FINAL_INSECURE_REDIRECT",
                            "status_code": status,
                            "error_type": None,
                            "retry_delay": 0.0,
                            "requested_url": url,
                            "final_url": final_url,
                        })
                        last_error = "insecure_redirect"
                        break

                    if status in RETRY_STATUSES and attempt < self.max_attempts:
                        delay = self._delay(attempt)
                        attempts.append({
                            "attempt": attempt,
                            "outcome": "RETRY_HTTP",
                            "status_code": status,
                            "error_type": None,
                            "retry_delay": delay,
                            "requested_url": url,
                            "final_url": final_url,
                        })
                        self.sleeper(delay)
                        continue

                    if status < 200 or status >= 300:
                        attempts.append({
                            "attempt": attempt,
                            "outcome": "FINAL_HTTP",
                            "status_code": status,
                            "error_type": None,
                            "retry_delay": 0.0,
                            "requested_url": url,
                            "final_url": final_url,
                        })
                        last_error = f"http_{status}"
                        break

                    content_type = (r.headers.get("content-type") or "").lower()
                    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        attempts.append({
                            "attempt": attempt,
                            "outcome": "FINAL_CONTENT_TYPE",
                            "status_code": status,
                            "error_type": None,
                            "retry_delay": 0.0,
                            "requested_url": url,
                            "final_url": final_url,
                        })
                        last_error = f"unexpected_content_type:{content_type}"
                        break

                    buf = bytearray()
                    for chunk in r.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        buf.extend(chunk)
                        if len(buf) > self.max_bytes:
                            raise ValueError("payload_too_large")

                    body = bytes(buf)
                    attempts.append({
                        "attempt": attempt,
                        "outcome": "HTTP_RESPONSE",
                        "status_code": status,
                        "error_type": None,
                        "retry_delay": 0.0,
                        "requested_url": url,
                        "final_url": final_url,
                    })
                    return NetResult(
                        ok=True,
                        requested_url=url,
                        final_url=final_url,
                        status=status,
                        content_type=content_type,
                        sha256=hashlib.sha256(body).hexdigest(),
                        size=len(body),
                        elapsed_ms=int((time.time() - started) * 1000),
                        body_b64=base64.b64encode(body).decode("ascii"),
                        attempts=attempts,
                        error="",
                    )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                if attempt < self.max_attempts:
                    delay = self._delay(attempt)
                    attempts.append({
                        "attempt": attempt,
                        "outcome": "RETRY_EXCEPTION",
                        "status_code": None,
                        "error_type": type(exc).__name__,
                        "retry_delay": delay,
                        "requested_url": url,
                        "final_url": None,
                    })
                    self.sleeper(delay)
                    continue
                attempts.append({
                    "attempt": attempt,
                    "outcome": "FINAL_EXCEPTION",
                    "status_code": None,
                    "error_type": type(exc).__name__,
                    "retry_delay": 0.0,
                    "requested_url": url,
                    "final_url": None,
                })
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                attempts.append({
                    "attempt": attempt,
                    "outcome": "FINAL_EXCEPTION",
                    "status_code": None,
                    "error_type": type(exc).__name__,
                    "retry_delay": 0.0,
                    "requested_url": url,
                    "final_url": None,
                })
                break

        return NetResult(
            ok=False,
            requested_url=url,
            final_url="",
            status=0,
            content_type="",
            sha256="",
            size=0,
            elapsed_ms=int((time.time() - started) * 1000),
            body_b64="",
            attempts=attempts,
            error=last_error or "network_failed",
        )
