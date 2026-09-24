from __future__ import annotations

import time
import requests

class NetClient:
    """Bounded idempotent HTTPS GET client for official lottery sources."""

    def __init__(
        self,
        connect_timeout: float = 12.0,
        read_timeout: float = 30.0,
        max_attempts: int = 3,
        backoff_base: float = 0.35,
        session: requests.Session | None = None,
        sleeper=time.sleep,
    ):
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.backoff_base = float(backoff_base)
        self.session = session
        self.sleeper = sleeper

    def get(self, url: str, *, params=None, headers=None, timeout=None, allow_redirects=True):
        if not str(url).startswith("https://"):
            raise ValueError("production sources must use HTTPS")
        timeout_value = timeout or (self.connect_timeout, self.read_timeout)
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                getter = self.session.get if self.session is not None else requests.get
                response = getter(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout_value,
                    allow_redirects=allow_redirects,
                )
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < self.max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and str(retry_after).isdigit():
                        delay = min(float(retry_after), 5.0)
                    else:
                        delay = self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt
                    self.sleeper(delay)
                    continue
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                if attempt >= self.max_attempts:
                    raise
                self.sleeper(self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt)
        if last:
            raise last
        raise RuntimeError("GET failed without response")
