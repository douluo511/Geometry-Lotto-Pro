from __future__ import annotations

import base64
import hashlib
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

@dataclass(frozen=True)
class SourceReceipt:
    source_id: str
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    byte_count: int
    sha256: str
    fetched_at: str
    attempts: tuple[dict[str, Any], ...]
    raw_b64: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class NetClient:
    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
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
        retry_after = None if response is None else getattr(response, "headers", {}).get("Retry-After")
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
    def _attach(exc: Exception, attempts: list[dict[str, Any]]) -> Exception:
        try:
            setattr(exc, "glp_attempts", tuple(dict(x) for x in attempts))
        except Exception:
            pass
        return exc

    def get_bytes(self, url: str, *, source_id: str) -> tuple[bytes, SourceReceipt]:
        url = str(url)
        if not url.startswith("https://"):
            raise ValueError("production sources must use HTTPS")
        getter = self.session.get if self.session is not None else requests.get
        ledger: list[dict[str, Any]] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = getter(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    headers={"User-Agent": "GuoxueZhice/0.2"},
                    allow_redirects=True,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                final_url = str(getattr(response, "url", "") or url)
                if not final_url.startswith("https://"):
                    ledger.append({"attempt":attempt,"outcome":"FINAL_INSECURE_REDIRECT","status_code":status,"error_type":None,"retry_delay":0.0,"url":final_url})
                    raise self._attach(requests.RequestException("HTTPS downgraded to non-HTTPS"), ledger)
                if status in RETRYABLE_STATUS and attempt < self.max_attempts:
                    delay = self._delay(attempt, response)
                    ledger.append({"attempt":attempt,"outcome":"RETRY_HTTP","status_code":status,"error_type":None,"retry_delay":delay,"url":url})
                    self.sleeper(delay)
                    continue
                if not 200 <= status < 300:
                    ledger.append({"attempt":attempt,"outcome":"FINAL_HTTP","status_code":status,"error_type":"HTTPError","retry_delay":0.0,"url":url})
                    raise self._attach(requests.HTTPError(f"HTTP {status}", response=response), ledger)
                raw = bytes(response.content)
                if not raw or len(raw) > 8 * 1024 * 1024:
                    ledger.append({"attempt":attempt,"outcome":"FINAL_SIZE","status_code":status,"error_type":"ValueError","retry_delay":0.0,"url":url})
                    raise self._attach(ValueError("invalid response size"), ledger)
                ctype = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
                if not any(x in ctype for x in ("json","text/plain","octet-stream")):
                    ledger.append({"attempt":attempt,"outcome":"FINAL_CONTENT_TYPE","status_code":status,"error_type":"ValueError","retry_delay":0.0,"url":url})
                    raise self._attach(ValueError(f"unexpected content type: {ctype or 'missing'}"), ledger)
                ledger.append({"attempt":attempt,"outcome":"HTTP_RESPONSE","status_code":status,"error_type":None,"retry_delay":0.0,"url":url})
                return raw, SourceReceipt(
                    source_id=source_id,
                    requested_url=url,
                    final_url=final_url,
                    http_status=status,
                    content_type=ctype,
                    byte_count=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    attempts=tuple(dict(x) for x in ledger),
                    raw_b64=base64.b64encode(raw).decode("ascii"),
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_attempts:
                    ledger.append({"attempt":attempt,"outcome":"FINAL_EXCEPTION","status_code":None,"error_type":type(exc).__name__,"retry_delay":0.0,"url":url})
                    raise self._attach(exc, ledger)
                delay = self._delay(attempt)
                ledger.append({"attempt":attempt,"outcome":"RETRY_EXCEPTION","status_code":None,"error_type":type(exc).__name__,"retry_delay":delay,"url":url})
                self.sleeper(delay)
        raise RuntimeError("GET retry loop exhausted")
