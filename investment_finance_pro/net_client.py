from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import random
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

class NetClient:
    RETRY_STATUSES = (408, 429, 500, 502, 503, 504)

    @staticmethod
    def _require_fresh_date(day: str, max_age_days: int, label: str) -> None:
        try:
            parsed=datetime.fromisoformat(str(day)[:10]).date()
        except Exception as exc:
            raise ValueError(f"{label}: invalid date {day!r}") from exc
        today=datetime.now(timezone.utc).date()
        age=(today-parsed).days
        if age < -2 or age > int(max_age_days):
            raise ValueError(f"{label}: stale/future date {parsed.isoformat()} age_days={age}")

    def __init__(
        self,
        connect_timeout=6.0,
        read_timeout=30.0,
        max_attempts=3,
        backoff_base=0.4,
        session=None,
        sleeper=time.sleep,
        rng=None,
    ):
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = int(max_attempts)
        self.backoff_base = float(backoff_base)
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_attempts < 1 or self.max_attempts > 4:
            raise ValueError("max_attempts must be between 1 and 4")
        if self.backoff_base < 0:
            raise ValueError("backoff_base must be nonnegative")
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.rng = rng or random.Random()
        self.last_receipt = {}

    def _retry_delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after and str(retry_after).isdigit():
            return min(float(retry_after), 5.0)
        return min(self.backoff_base * (2 ** (attempt - 1)) * (0.5 + self.rng.random()), 5.0)

    def _get_bytes(self, url: str, accept: str):
        if not str(url).startswith("https://"):
            raise ValueError("HTTPS required")
        ledger = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InvestmentFinancePro/0.4",
                        "Accept": accept,
                    },
                    allow_redirects=True,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                final_url = str(getattr(response, "url", "") or url)
                if not final_url.startswith("https://"):
                    ledger.append({
                        "attempt": attempt, "outcome": "FINAL_INSECURE_REDIRECT",
                        "status_code": status, "error_type": None,
                        "retry_delay": 0.0, "url": final_url,
                    })
                    exc = ValueError(f"HTTPS request redirected to non-HTTPS URL: {final_url}")
                    setattr(exc, "glp_attempts", tuple(ledger))
                    raise exc

                if status in self.RETRY_STATUSES and attempt < self.max_attempts:
                    delay = self._retry_delay(attempt, response.headers.get("Retry-After"))
                    ledger.append({
                        "attempt": attempt, "outcome": "RETRY_HTTP",
                        "status_code": status, "error_type": None,
                        "retry_delay": delay, "url": final_url,
                    })
                    self.sleeper(delay)
                    continue

                response.raise_for_status()
                raw = bytes(response.content)
                if not raw or len(raw) > 10_000_000:
                    raise ValueError("invalid response size")
                ctype = (response.headers.get("Content-Type") or "").lower()
                ledger.append({
                    "attempt": attempt, "outcome": "HTTP_RESPONSE",
                    "status_code": status, "error_type": None,
                    "retry_delay": 0.0, "url": final_url,
                })
                self.last_receipt = {
                    "requested_url": url,
                    "final_url": final_url,
                    "http_status": status,
                    "content_type": ctype,
                    "payload_hash": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "attempts": list(ledger),
                    "body_b64": base64.b64encode(raw).decode("ascii"),
                }
                return raw, dict(self.last_receipt)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < self.max_attempts:
                    delay = self._retry_delay(attempt)
                    ledger.append({
                        "attempt": attempt, "outcome": "RETRY_EXCEPTION",
                        "status_code": None, "error_type": type(exc).__name__,
                        "retry_delay": delay, "url": url,
                    })
                    self.sleeper(delay)
                    continue
                ledger.append({
                    "attempt": attempt, "outcome": "FINAL_EXCEPTION",
                    "status_code": None, "error_type": type(exc).__name__,
                    "retry_delay": 0.0, "url": url,
                })
                setattr(exc, "glp_attempts", tuple(ledger))
                raise
            except (requests.HTTPError, ValueError) as exc:
                if getattr(exc, "glp_attempts", None):
                    raise
                code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
                retryable = code in self.RETRY_STATUSES
                if retryable and attempt < self.max_attempts:
                    delay = self._retry_delay(attempt)
                    ledger.append({
                        "attempt": attempt, "outcome": "RETRY_EXCEPTION",
                        "status_code": code or None, "error_type": type(exc).__name__,
                        "retry_delay": delay, "url": url,
                    })
                    self.sleeper(delay)
                    continue
                ledger.append({
                    "attempt": attempt, "outcome": "FINAL_EXCEPTION",
                    "status_code": code or None, "error_type": type(exc).__name__,
                    "retry_delay": 0.0, "url": url,
                })
                setattr(exc, "glp_attempts", tuple(ledger))
                raise
        raise RuntimeError("network retry loop exhausted")

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

    def _fetch_yahoo_history(self, symbol: str):
        errors=[]
        safe=urllib.parse.quote(symbol,safe="")
        for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
            url=(
                f"https://{host}/v8/finance/chart/{safe}"
                "?range=6mo&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
            )
            try:
                payload,receipt=self._get_json(url)
                rows=self._parse_yahoo_chart(payload,symbol)
                self._require_fresh_date(rows[-1]["date"],10,f"Yahoo {symbol}")
                return rows,f"YahooChart:{host}",receipt
            except Exception as exc:
                errors.append(f"{host}={type(exc).__name__}: {exc}")
        raise RuntimeError(" | ".join(errors))

    def fetch_stooq_history(self, symbol: str):
        end=datetime.now(timezone.utc).date()
        start=end-timedelta(days=220)
        stooq_symbol=symbol.lower()+".us"
        url="https://stooq.com/q/d/l/?"+urllib.parse.urlencode({
            "s":stooq_symbol,"d1":start.strftime("%Y%m%d"),"d2":end.strftime("%Y%m%d"),"i":"d"
        })
        raw,receipt=self._get_bytes(url,"text/csv,application/csv,text/plain;q=0.9,*/*;q=0.1")
        rows=[]
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig",errors="replace"))):
            try:
                close=float(row["Close"])
                if not math.isfinite(close) or close<=0:
                    continue
                rows.append({
                    "date":row["Date"],
                    "open":float(row["Open"]),
                    "high":float(row["High"]),
                    "low":float(row["Low"]),
                    "close":close,
                    "volume":int(float(row["Volume"])) if row.get("Volume") else 0,
                })
            except (KeyError,TypeError,ValueError):
                continue
        rows.sort(key=lambda x:x["date"])
        if len(rows)<30:
            raise ValueError(f"{symbol}: Stooq history too short ({len(rows)})")
        self._require_fresh_date(rows[-1]["date"],10,f"Stooq {symbol}")
        return rows,"Stooq",receipt

    @staticmethod
    def _crosscheck_market(yahoo_rows, stooq_rows, symbol: str):
        y={r["date"]:float(r["close"]) for r in yahoo_rows}
        s={r["date"]:float(r["close"]) for r in stooq_rows}
        common=sorted(set(y)&set(s))
        if len(common)<20:
            raise ValueError(f"{symbol}: independent market overlap too small ({len(common)})")
        day=common[-1]
        a=y[day]; b=s[day]
        relative=abs(a-b)/max(abs(a),abs(b),1e-12)
        if relative>0.05:
            raise ValueError(f"{symbol}: Yahoo/Stooq conflict on {day}: {a} vs {b} rel={relative:.4f}")
        return {"status":"PASS","date":day,"yahoo_close":a,"stooq_close":b,"relative_diff":relative,"overlap":len(common)}

    def fetch_market_history(self, symbol: str):
        yahoo_error=None
        stooq_error=None
        yahoo=None
        stooq=None
        try:
            yahoo=self._fetch_yahoo_history(symbol)
        except Exception as exc:
            yahoo_error=f"{type(exc).__name__}: {exc}"
        try:
            stooq=self.fetch_stooq_history(symbol)
        except Exception as exc:
            stooq_error=f"{type(exc).__name__}: {exc}"

        if yahoo and stooq:
            yrows,yprovider,yreceipt=yahoo
            srows,sprovider,sreceipt=stooq
            cross=self._crosscheck_market(yrows,srows,symbol)
            receipt=dict(yreceipt)
            receipt["source_identity"]="YahooChart"
            receipt["crosscheck_status"]="PASS"
            receipt["crosscheck"]=cross
            receipt["crosscheck_source_identity"]="Stooq"
            receipt["crosscheck_receipt"]=sreceipt
            return yrows,yprovider+"+StooqCrosscheck",receipt
        if yahoo:
            rows,provider,receipt=yahoo
            receipt=dict(receipt)
            receipt["source_identity"]="YahooChart"
            receipt["crosscheck_status"]="UNAVAILABLE"
            receipt["crosscheck_error"]=stooq_error
            return rows,provider+"+SingleSource",receipt
        if stooq:
            rows,provider,receipt=stooq
            receipt=dict(receipt)
            receipt["source_identity"]="Stooq"
            receipt["crosscheck_status"]="UNAVAILABLE"
            receipt["crosscheck_error"]=yahoo_error
            return rows,provider+"+FallbackSingleSource",receipt
        raise RuntimeError(f"all independent market sources failed: yahoo={yahoo_error} | stooq={stooq_error}")

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
        self._require_fresh_date(day,14,f"FRED {series_id}")
        return {"series": series_id, "date": day, "value": value}, receipt


    def fetch_us_treasury_10y(self):
        year = datetime.now(timezone.utc).year
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?"
            + urllib.parse.urlencode({
                "data": "daily_treasury_yield_curve",
                "field_tdr_date_value": str(year),
            })
        )
        raw, receipt = self._get_bytes(url, "application/xml,text/xml,*/*;q=0.1")
        root = ET.fromstring(raw)
        observations = []
        for props in root.iter():
            local = props.tag.rsplit("}", 1)[-1]
            if local != "properties":
                continue
            row = {}
            for child in list(props):
                row[child.tag.rsplit("}", 1)[-1]] = (child.text or "").strip()
            day = row.get("NEW_DATE")
            value = row.get("BC_10YEAR")
            if not day or value in (None, ""):
                continue
            try:
                number = float(value)
            except ValueError:
                continue
            observations.append((day[:10], number))
        if not observations:
            raise ValueError("US Treasury: no 10-year observations")
        observations.sort(key=lambda x: x[0])
        day, value = observations[-1]
        self._require_fresh_date(day,14,"US Treasury 10Y")
        return {"series": "US_TREASURY_10Y", "date": day, "value": value}, receipt

    def fetch_sec_companyfacts(self, symbol: str, cik: int):
        url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
        raw,receipt=self._get_bytes(url,"application/json,*/*;q=0.1")
        payload=json.loads(raw.decode("utf-8-sig"))
        if str(payload.get("cik","")) not in {str(int(cik)),str(cik)}:
            raise ValueError("SEC CIK mismatch")
        facts=((payload.get("facts") or {}).get("us-gaap") or {})
        eps=facts.get("EarningsPerShareDiluted") or facts.get("EarningsPerShareBasic")
        if not isinstance(eps,dict): raise ValueError("SEC EPS fact missing")
        units=(eps.get("units") or {})
        rows=units.get("USD/shares") or units.get("USD / shares") or []
        annual=[x for x in rows if x.get("form")=="10-K" and x.get("fy") and x.get("val") is not None]
        if not annual: raise ValueError("SEC annual EPS missing")
        annual.sort(key=lambda x:(str(x.get("fy")),str(x.get("filed",""))))
        row=annual[-1]
        self._require_fresh_date(str(row.get("filed") or ""),550,f"SEC {symbol} 10-K")
        return {"symbol":symbol,"cik":int(cik),"fiscal_year":row.get("fy"),"annual_diluted_eps":float(row["val"]),"filed":row.get("filed"),"form":row.get("form")},receipt
