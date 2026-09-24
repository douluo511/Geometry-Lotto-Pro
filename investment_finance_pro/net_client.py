from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

class NetClient:
    def __init__(self, connect_timeout=6.0, read_timeout=30.0, max_attempts=3, backoff_base=0.4):
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = max(1, min(int(max_attempts), 4))
        self.backoff_base = float(backoff_base)
        self.last_receipt = {}

    def _get_bytes(self, url: str, accept: str):
        if not url.startswith("https://"):
            raise ValueError("HTTPS required")
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.get(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InvestmentFinancePro/0.2",
                        "Accept": accept,
                    },
                    allow_redirects=True,
                )
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < self.max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt
                    time.sleep(min(delay, 5.0))
                    continue
                response.raise_for_status()
                raw = bytes(response.content)
                if not raw or len(raw) > 10_000_000:
                    raise ValueError("invalid response size")
                ctype = (response.headers.get("Content-Type") or "").lower()
                self.last_receipt = {
                    "url": str(response.url),
                    "http_status": int(response.status_code),
                    "content_type": ctype,
                    "payload_hash": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "attempts": attempt,
                }
                return raw, dict(self.last_receipt)
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                last = exc
                code = getattr(getattr(exc, "response", None), "status_code", 0)
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or code in (408, 429, 500, 502, 503, 504)
                if attempt >= self.max_attempts or not retryable:
                    raise
                time.sleep(self.backoff_base * (2 ** (attempt - 1)) + 0.01 * attempt)
        raise RuntimeError(str(last))

    def _get_json(self, url: str):
        raw, receipt = self._get_bytes(url, "application/json,text/plain;q=0.9,*/*;q=0.1")
        ctype = receipt.get("content_type", "")
        if "json" not in ctype and not raw.lstrip().startswith((b"{", b"[")):
            raise ValueError(f"expected JSON, got {ctype}")
        return json.loads(raw.decode("utf-8-sig")), receipt

    @staticmethod
    def _parse_yahoo_chart(payload: dict, symbol: str):
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise ValueError(f"Yahoo error for {symbol}: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise ValueError(f"Yahoo empty result for {symbol}")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        adjusted = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
        rows = []
        for i, ts in enumerate(timestamps):
            try:
                raw_close = quote.get("close", [])[i]
                close = adjusted[i] if i < len(adjusted) and adjusted[i] is not None else raw_close
                if close is None or float(close) <= 0:
                    continue
                rows.append({
                    "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat(),
                    "open": float(quote.get("open", [])[i] or close),
                    "high": float(quote.get("high", [])[i] or close),
                    "low": float(quote.get("low", [])[i] or close),
                    "close": float(close),
                    "volume": int(quote.get("volume", [])[i] or 0),
                })
            except (IndexError, TypeError, ValueError):
                continue
        rows.sort(key=lambda row: row["date"])
        if len(rows) < 30:
            raise ValueError(f"{symbol}: Yahoo history too short ({len(rows)})")
        return rows

    def fetch_market_history(self, symbol: str):
        errors = []
        safe = urllib.parse.quote(symbol, safe="")
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = (
                f"https://{host}/v8/finance/chart/{safe}"
                "?range=6mo&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
            )
            try:
                payload, receipt = self._get_json(url)
                return self._parse_yahoo_chart(payload, symbol), f"YahooChart:{host}", receipt
            except Exception as exc:
                errors.append(f"{host}={type(exc).__name__}: {exc}")
        raise RuntimeError(" | ".join(errors))

    def fetch_fred_series(self, series_id: str):
        start = (datetime.now(timezone.utc).date() - timedelta(days=550)).isoformat()
        url = (
            "https://fred.stlouisfed.org/graph/fredgraph.csv?"
            + urllib.parse.urlencode({"id": series_id, "cosd": start})
        )
        raw, receipt = self._get_bytes(url, "text/csv,application/csv,text/plain;q=0.9,*/*;q=0.1")
        text = raw.decode("utf-8-sig", errors="replace")
        values = []
        for row in csv.DictReader(io.StringIO(text)):
            value_key = series_id if series_id in row else next((k for k in row if k not in {"DATE", "observation_date"}), None)
            if not value_key:
                continue
            try:
                value = float(row[value_key])
                if math.isfinite(value):
                    values.append((row.get("DATE") or row.get("observation_date") or "", value))
            except (TypeError, ValueError):
                continue
        if not values:
            raise ValueError(f"FRED {series_id}: no numeric observations")
        day, value = values[-1]
        return {"series": series_id, "date": day, "value": value}, receipt
