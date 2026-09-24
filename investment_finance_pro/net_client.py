from __future__ import annotations
import hashlib
import time
from datetime import datetime, timezone
import requests
import legacy_backend as legacy

class NetClient:
    def __init__(self, connect_timeout=5.0, read_timeout=15.0, max_attempts=3, backoff_base=0.35):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.backoff_base = backoff_base

    def get_text(self, url: str) -> str:
        if not url.startswith("https://"):
            raise ValueError("HTTPS required")
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = requests.get(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    headers={"User-Agent": "Investment-Finance-Pro/0.2"},
                )
                if r.status_code in (429, 500, 502, 503, 504) and attempt < self.max_attempts:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt)
                    continue
                r.raise_for_status()
                ctype = (r.headers.get("Content-Type") or "").lower()
                if not any(x in ctype for x in ("json", "csv", "text/plain", "text/csv", "octet-stream")):
                    raise ValueError(f"unexpected content type: {ctype}")
                raw = r.content
                if not raw or len(raw) > 10_000_000:
                    raise ValueError("invalid response size")
                self.last_receipt = {
                    "url": url,
                    "http_status": r.status_code,
                    "content_type": ctype,
                    "payload_hash": hashlib.sha256(raw).hexdigest(),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "attempts": attempt,
                }
                return raw.decode("utf-8-sig")
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                last = exc
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError))
                if isinstance(exc, requests.HTTPError) and getattr(exc.response, "status_code", 0) in (429, 500, 502, 503, 504):
                    retryable = True
                if attempt >= self.max_attempts or not retryable:
                    raise
                time.sleep(self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt)
        raise RuntimeError(str(last))

    def _through_legacy_parser(self, fn, *args):
        original = legacy.fetch_text
        legacy.fetch_text = self.get_text
        try:
            value = fn(*args)
            receipt = dict(getattr(self, "last_receipt", {}))
            if not receipt:
                raise RuntimeError("missing network receipt")
            return value, receipt
        finally:
            legacy.fetch_text = original

    def fetch_market_history(self, symbol: str):
        errors = []
        try:
            rows, receipt = self._through_legacy_parser(legacy.fetch_yahoo_history, symbol)
            return rows, "YahooChart", receipt
        except Exception as exc:
            errors.append("YahooChart=" + str(exc))
        try:
            rows, receipt = self._through_legacy_parser(legacy.fetch_stooq_history, symbol)
            return rows, "Stooq", receipt
        except Exception as exc:
            errors.append("Stooq=" + str(exc))
        raise RuntimeError(" | ".join(errors))

    def fetch_fred_series(self, series_id: str):
        value, receipt = self._through_legacy_parser(legacy.fetch_fred_series, series_id)
        return value, receipt
