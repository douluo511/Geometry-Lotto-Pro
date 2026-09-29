from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Tuple

import requests

from contracts import validate_knowledge
from domain import SourceRecord


RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class NetError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    outcome: str
    status_code: int | None
    error_type: str | None
    retry_delay: float
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


class NetClient:
    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 12.0,
        retries: int = 2,
        max_bytes: int = 2_000_000,
        backoff_base: float = 0.25,
        max_retry_after: float = 5.0,
        session: requests.Session | None = None,
        sleeper=time.sleep,
        rng: random.Random | None = None,
    ):
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.retries = max(0, min(int(retries), 3))
        self.max_bytes = int(max_bytes)
        self.backoff_base = float(backoff_base)
        self.max_retry_after = max(0.0, float(max_retry_after))
        self.session = session
        self.sleeper = sleeper
        self.rng = rng or random.Random()
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.backoff_base < 0:
            raise ValueError("backoff_base must be non-negative")

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

    def get_json(
        self,
        url: str,
        validator: Callable[[Dict], None] = validate_knowledge,
        *,
        source_id: str = "",
    ) -> Tuple[Dict, SourceRecord]:
        if not str(url).lower().startswith("https://"):
            raise NetError("HTTPS is required")

        getter = self.session.get if self.session is not None else requests.get
        attempts: list[AttemptRecord] = []
        max_attempts = self.retries + 1

        for attempt in range(1, max_attempts + 1):
            response = None
            try:
                response = getter(
                    url,
                    headers={
                        "User-Agent": "Psychology-Insight-Pro/0.4.0",
                        "Accept": "application/json,text/plain;q=0.9",
                    },
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                    stream=True,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                if status in RETRYABLE_STATUS and attempt < max_attempts:
                    delay = self._delay(attempt, response)
                    attempts.append(AttemptRecord(attempt, "RETRY_HTTP", status, None, delay, url))
                    try:
                        response.close()
                    except Exception:
                        pass
                    self.sleeper(delay)
                    continue
                if status < 200 or status >= 300:
                    attempts.append(AttemptRecord(attempt, "FINAL_HTTP", status, None, 0.0, url))
                    raise NetError(f"HTTP {status}")

                ctype = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
                if "json" not in ctype and "text/plain" not in ctype:
                    raise NetError(f"unexpected content-type: {ctype or 'missing'}")

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise NetError("response too large")
                    chunks.append(bytes(chunk))
                raw = b"".join(chunks)
                if not raw:
                    raise NetError("empty response")

                digest = hashlib.sha256(raw).hexdigest()
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise NetError("invalid UTF-8 JSON") from exc
                validator(payload)
                attempts.append(AttemptRecord(attempt, "HTTP_RESPONSE", status, None, 0.0, url))
                source = SourceRecord(
                    url=url,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    http_status=status,
                    sha256=digest,
                    bytes_count=len(raw),
                    content_type=ctype,
                    source_id=source_id or url,
                    attempts=tuple(x.to_dict() for x in attempts),
                    raw_b64=base64.b64encode(raw).decode("ascii"),
                )
                return payload, source
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= max_attempts:
                    attempts.append(AttemptRecord(attempt, "FINAL_EXCEPTION", None, type(exc).__name__, 0.0, url))
                    error = NetError(f"network request failed: {type(exc).__name__}: {exc}")
                    error.attempts = tuple(x.to_dict() for x in attempts)
                    raise error from exc
                delay = self._delay(attempt)
                attempts.append(AttemptRecord(attempt, "RETRY_EXCEPTION", None, type(exc).__name__, delay, url))
                self.sleeper(delay)
            except NetError as exc:
                if not hasattr(exc, "attempts"):
                    status = int(getattr(response, "status_code", 0) or 0) if response is not None else None
                    if not attempts or attempts[-1].attempt != attempt:
                        attempts.append(AttemptRecord(attempt, "FINAL_VALIDATION", status, type(exc).__name__, 0.0, url))
                    exc.attempts = tuple(x.to_dict() for x in attempts)
                raise
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        raise NetError("request exhausted without response")
