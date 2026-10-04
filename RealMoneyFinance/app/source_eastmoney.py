from __future__ import annotations

from .domain import DailyBar
from .netclient import NetClient


KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _secid(symbol: str) -> str:
    code = "".join(ch for ch in str(symbol) if ch.isdigit())
    if len(code) != 6:
        raise ValueError("symbol must contain exactly 6 digits")
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market}.{code}"


def fetch_daily_bars(client: NetClient, symbol: str, limit: int = 120) -> tuple[list[DailyBar], dict]:
    params = {
        "secid": _secid(symbol),
        "klt": "101",
        "fqt": "1",
        "lmt": str(max(30, min(int(limit), 500))),
        "end": "20500101",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    obj, meta = client.get_json(
        KLINE_URL,
        params,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    data = obj.get("data")
    if not isinstance(data, dict):
        raise ValueError("Eastmoney response missing data object")
    klines = data.get("klines")
    if not isinstance(klines, list) or len(klines) < 30:
        raise ValueError("Eastmoney response has insufficient kline rows")

    rows: list[DailyBar] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            raise ValueError("kline schema changed or row is incomplete")
        turnover = None
        try:
            turnover = float(parts[10])
        except Exception:
            turnover = None
        rows.append(DailyBar(
            symbol="".join(ch for ch in str(symbol) if ch.isdigit()),
            trade_date=parts[0],
            open=float(parts[1]),
            close=float(parts[2]),
            high=float(parts[3]),
            low=float(parts[4]),
            volume=float(parts[5]),
            amount=float(parts[6]),
            pct_change=float(parts[8]),
            turnover_rate=turnover,
            provider="eastmoney_public_l1",
            raw_sha256=meta.payload_sha256,
        ))
    rows.sort(key=lambda x: x.trade_date)
    return rows, {
        "provider": "eastmoney_public_l1",
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(rows),
        "price_adjustment": "qfq",
    }
