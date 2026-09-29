from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from datetime import datetime, timezone
from typing import Callable

import requests

from domain import SourceReceipt

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

class NetClient:
    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_attempts: int = 3,
        backoff_base: float = 0.35,
        max_retry_after: float = 5.0,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ):
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.backoff_base = float(backoff_base)
        if self.backoff_base < 0:
            raise ValueError("backoff_base must be non-negative")
        self.max_retry_after = max(0.0, float(max_retry_after))
        self.session = session
        self.sleeper = sleeper
        self.rng = rng or random.Random()

    def _delay(self, attempt: int, response=None) -> float:
        retry_after = None
        if response is not None:
            retry_after = getattr(response, "headers", {}).get("Retry-After")
        if retry_after is not None:
            try:
                value = float(str(retry_after).strip())
                if value >= 0:
                    return min(value, self.max_retry_after)
            except ValueError:
                pass
        base = self.backoff_base * (2 ** (attempt - 1))
        jitter = self.rng.random() * max(0.001, self.backoff_base * 0.25)
        return base + jitter

    @staticmethod
    def _attach(exc: Exception, ledger: list[dict]) -> Exception:
        try:
            setattr(exc, "glp_attempts", tuple(dict(x) for x in ledger))
        except Exception:
            pass
        return exc

    def get_bytes(self, url: str, *, source_id: str | None = None) -> tuple[bytes, SourceReceipt]:
        url = str(url)
        if not url.startswith("https://"):
            raise ValueError("only HTTPS sources are allowed")
        getter = self.session.get if self.session is not None else requests.get
        ledger: list[dict] = []

        for attempt in range(1, self.max_attempts + 1):
            try:
                r = getter(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    headers={"User-Agent": "EnglishRootIntelligence/0.4"},
                    allow_redirects=True,
                )
                status = int(getattr(r, "status_code", 0) or 0)
                final_url = str(getattr(r, "url", "") or url)
                if not final_url.startswith("https://"):
                    ledger.append({
                        "attempt": attempt, "outcome": "FINAL_INSECURE_REDIRECT",
                        "status_code": status, "error_type": None, "retry_delay": 0.0, "url": final_url,
                    })
                    raise self._attach(requests.RequestException("HTTPS request redirected to non-HTTPS URL"), ledger)

                if status in RETRYABLE_STATUS and attempt < self.max_attempts:
                    delay = self._delay(attempt, response=r)
                    ledger.append({
                        "attempt": attempt, "outcome": "RETRY_HTTP",
                        "status_code": status, "error_type": None, "retry_delay": delay, "url": url,
                    })
                    self.sleeper(delay)
                    continue

                if status < 200 or status >= 300:
                    ledger.append({
                        "attempt": attempt,
                        "outcome": "FINAL_RETRYABLE_HTTP" if status in RETRYABLE_STATUS else "FINAL_HTTP",
                        "status_code": status, "error_type": "HTTPError", "retry_delay": 0.0, "url": url,
                    })
                    err = requests.HTTPError(f"HTTP {status}", response=r)
                    raise self._attach(err, ledger)

                ctype = (r.headers.get("Content-Type") or "").lower()
                if not any(x in ctype for x in ("json", "text/plain", "octet-stream")):
                    ledger.append({
                        "attempt": attempt, "outcome": "FINAL_CONTENT_TYPE",
                        "status_code": status, "error_type": "ValueError", "retry_delay": 0.0, "url": url,
                    })
                    raise self._attach(ValueError(f"unexpected content type: {ctype or 'missing'}"), ledger)

                raw = bytes(r.content)
                if not raw or len(raw) > 5_000_000:
                    ledger.append({
                        "attempt": attempt, "outcome": "FINAL_SIZE",
                        "status_code": status, "error_type": "ValueError", "retry_delay": 0.0, "url": url,
                    })
                    raise self._attach(ValueError("invalid response size"), ledger)

                ledger.append({
                    "attempt": attempt, "outcome": "HTTP_RESPONSE",
                    "status_code": status, "error_type": None, "retry_delay": 0.0, "url": url,
                })
                rec = SourceReceipt(
                    source_id=source_id or url,
                    url=url,
                    final_url=final_url,
                    status_code=status,
                    content_type=ctype,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    byte_count=len(raw),
                    attempts=attempt,
                    attempt_ledger=tuple(dict(x) for x in ledger),
                    raw_b64=base64.b64encode(raw).decode("ascii"),
                )
                return raw, rec

            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_attempts:
                    ledger.append({
                        "attempt": attempt, "outcome": "FINAL_EXCEPTION",
                        "status_code": None, "error_type": type(exc).__name__, "retry_delay": 0.0, "url": url,
                    })
                    raise self._attach(exc, ledger)
                delay = self._delay(attempt)
                ledger.append({
                    "attempt": attempt, "outcome": "RETRY_EXCEPTION",
                    "status_code": None, "error_type": type(exc).__name__, "retry_delay": delay, "url": url,
                })
                self.sleeper(delay)

        raise RuntimeError("GET exhausted retry loop")

    def get_json(self, url: str, *, source_id: str | None = None):
        raw, rec = self.get_bytes(url, source_id=source_id)
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            err = ValueError(f"invalid JSON payload: {exc}")
            try:
                setattr(err, "glp_attempts", rec.attempt_ledger)
            except Exception:
                pass
            raise err
        return value, rec
