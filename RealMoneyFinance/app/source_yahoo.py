from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .domain import DailyBar
from .netclient import NetClient


CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


def _ticker(symbol: str) -> str:
    code = "".join(ch for ch in str(symbol) if ch.isdigit())
    if len(code) != 6:
        raise ValueError("symbol must contain exactly 6 digits")
    suffix = ".SS" if code.startswith(("5", "6", "9")) else ".SZ"
    return code + suffix


def fetch_daily_bars_yahoo(client: NetClient, symbol: str, limit: int = 120) -> tuple[list[DailyBar], dict]:
    ticker = _ticker(symbol)
    obj, meta = client.get_json(
        CHART_BASE + ticker,
        {
            "range": "2y",
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    chart = obj.get("chart")
    if not isinstance(chart, dict) or chart.get("error") not in (None, {}):
        raise ValueError(f"Yahoo chart error: {chart.get('error') if isinstance(chart, dict) else 'missing chart'}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("Yahoo response missing chart result")
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    if not isinstance(timestamps, list) or not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        raise ValueError("Yahoo response missing timestamp/quote arrays")
    quote = quotes[0]
    opens = quote.get("open")
    closes = quote.get("close")
    highs = quote.get("high")
    lows = quote.get("low")
    volumes = quote.get("volume")
    arrays = (opens, closes, highs, lows, volumes)
    if not all(isinstance(x, list) for x in arrays):
        raise ValueError("Yahoo quote schema changed")

    shanghai = timezone(timedelta(hours=8))
    code = ticker[:6]
    rows: list[DailyBar] = []
    for i, stamp in enumerate(timestamps):
        try:
            open_p = float(opens[i])
            close_p = float(closes[i])
            high_p = float(highs[i])
            low_p = float(lows[i])
            volume = float(volumes[i] or 0.0)
            if min(open_p, close_p, high_p, low_p) <= 0:
                continue
            trade_date = datetime.fromtimestamp(int(stamp), tz=shanghai).date().isoformat()
        except (IndexError, TypeError, ValueError, OSError, OverflowError):
            continue
        rows.append(DailyBar(
            symbol=code,
            trade_date=trade_date,
            open=open_p,
            close=close_p,
            high=high_p,
            low=low_p,
            volume=volume,
            amount=0.0,
            pct_change=((close_p / open_p) - 1.0) * 100.0,
            turnover_rate=None,
            provider="yahoo_public_chart",
            raw_sha256=meta.payload_sha256,
        ))
    rows.sort(key=lambda x: x.trade_date)
    rows = rows[-max(30, min(int(limit), 500)):]
    if len(rows) < 30:
        raise ValueError("Yahoo response has insufficient valid daily rows")
    return rows, {
        "provider": "yahoo_public_chart",
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(rows),
        "price_adjustment": "unadjusted",
        "content_type": meta.content_type,
        "content_type_policy": meta.content_type_policy,
    }
