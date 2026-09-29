from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

import requests

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    outcome: str
    status_code: int | None
    error_type: str | None
    retry_delay: float
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NetClient:
    """Auditable bounded HTTPS GET transport for official DLT sources."""

    def __init__(
        self,
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
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

    def get(self, url: str, *, params=None, headers=None, timeout=None, allow_redirects=True):
        url = str(url)
        if not url.startswith("https://"):
            raise ValueError("production source must use HTTPS")
        timeout_value = timeout or (self.connect_timeout, self.read_timeout)
        if (
            not isinstance(timeout_value, tuple)
            or len(timeout_value) != 2
            or float(timeout_value[0]) <= 0
            or float(timeout_value[1]) <= 0
        ):
            raise ValueError("timeout must be positive (connect, read) tuple")

        getter = self.session.get if self.session is not None else requests.get
        attempts: list[AttemptRecord] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = getter(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout_value,
                    allow_redirects=allow_redirects,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                if status in RETRYABLE_STATUS and attempt < self.max_attempts:
                    delay = self._delay(attempt, response)
                    attempts.append(AttemptRecord(attempt, "RETRY_HTTP", status, None, delay, url))
                    self.sleeper(delay)
                    continue
                attempts.append(AttemptRecord(
                    attempt,
                    "FINAL_RETRYABLE_HTTP" if status in RETRYABLE_STATUS else "HTTP_RESPONSE",
                    status,
                    None,
                    0.0,
                    url,
                ))
                try:
                    response.glp_attempts = tuple(x.to_dict() for x in attempts)
                except Exception:
                    pass
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_attempts:
                    attempts.append(AttemptRecord(attempt, "FINAL_EXCEPTION", None, type(exc).__name__, 0.0, url))
                    try:
                        exc.glp_attempts = tuple(x.to_dict() for x in attempts)
                    except Exception:
                        pass
                    raise
                delay = self._delay(attempt)
                attempts.append(AttemptRecord(attempt, "RETRY_EXCEPTION", None, type(exc).__name__, delay, url))
                self.sleeper(delay)

        raise RuntimeError("GET retry loop exhausted")
