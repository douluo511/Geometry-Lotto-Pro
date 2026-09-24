from __future__ import annotations
import datetime as dt
import json
import time
from typing import Any, Iterable
import requests
from domain import sha256_bytes

class NetworkError(RuntimeError):
    pass

class NetClient:
    def __init__(self, connect_timeout=5.0, read_timeout=15.0, max_attempts=3, session=None, sleep_fn=time.sleep):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if not 1 <= max_attempts <= 4:
            raise ValueError("max_attempts out of range")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "GuoxueZhice/0.2 audited updater"})
        self._sleep = sleep_fn

    def _pause(self, attempt: int) -> None:
        self._sleep(0.35 * (2 ** attempt) + 0.05 * (attempt + 1))

    def get_bytes(self, url: str, allowed_content_types: Iterable[str] | None = None) -> tuple[bytes, dict[str, Any]]:
        if not url.startswith("https://"):
            raise NetworkError("only https sources are allowed")
        allowed = tuple(allowed_content_types or ())
        last_error = None
        for attempt in range(self.max_attempts):
            try:
                response = self.session.get(url, timeout=(self.connect_timeout, self.read_timeout), allow_redirects=True)
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    if attempt + 1 >= self.max_attempts:
                        raise NetworkError(f"retryable HTTP {response.status_code} exhausted")
                    self._pause(attempt)
                    continue
                response.raise_for_status()
                ctype = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if allowed and not any(ctype == item or ctype.startswith(item) for item in allowed):
                    raise NetworkError(f"unexpected content-type: {ctype or 'missing'}")
                raw = response.content
                if not raw:
                    raise NetworkError("empty payload")
                return raw, {
                    "source": response.url,
                    "requested_url": url,
                    "http_status": response.status_code,
                    "content_type": ctype,
                    "payload_sha256": sha256_bytes(raw),
                    "bytes": len(raw),
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "attempt": attempt + 1,
                }
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    break
                self._pause(attempt)
            except requests.RequestException as exc:
                raise NetworkError(f"non-retryable network error: {exc}") from exc
        raise NetworkError(f"network attempts exhausted: {last_error}")

    def get_json(self, url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        raw, meta = self.get_bytes(url, ("application/json", "text/plain", "application/octet-stream"))
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise NetworkError(f"invalid JSON payload: {exc}") from exc
        if not isinstance(value, dict):
            raise NetworkError("JSON root must be an object")
        return value, meta
