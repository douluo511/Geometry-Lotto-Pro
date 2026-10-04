from __future__ import annotations

from .netclient import NetClient
from .source_eastmoney import fetch_daily_bars as fetch_eastmoney
from .source_tencent import fetch_daily_bars_tencent


def _latest_close(rows):
    return (rows[-1].trade_date, float(rows[-1].close)) if rows else (None, None)


def fetch_daily_bars_failover(client: NetClient, symbol: str, limit: int = 120):
    attempts = []
    successes = []

    for provider, fn in [
        ("eastmoney_public_l1", fetch_eastmoney),
        ("tencent_public_kline", fetch_daily_bars_tencent),
    ]:
        try:
            rows, meta = fn(client, symbol, limit)
            successes.append((provider, rows, meta))
            attempts.append({"provider": provider, "status": "PASS", "row_count": len(rows)})
        except Exception as exc:
            attempts.append({"provider": provider, "status": "FAIL", "error": repr(exc)})

    if not successes:
        raise RuntimeError("all configured production market-data providers failed")

    chosen_provider, rows, meta = successes[0]
    cross_source = {
        "status": "NOT VERIFIED",
        "reason": "only one production provider succeeded",
    }

    if len(successes) >= 2:
        _, rows2, meta2 = successes[1]
        d1, c1 = _latest_close(rows)
        d2, c2 = _latest_close(rows2)
        if d1 == d2 and c1 and c2:
            rel = abs(c1 - c2) / max(abs(c1), abs(c2), 1e-9)
            if rel <= 0.02:
                cross_source = {
                    "status": "PASS",
                    "latest_date": d1,
                    "relative_close_difference": rel,
                    "providers": [meta["provider"], meta2["provider"]],
                }
            else:
                cross_source = {
                    "status": "FAIL",
                    "reason": "latest close differs by more than 2%",
                    "latest_date_primary": d1,
                    "latest_date_secondary": d2,
                    "close_primary": c1,
                    "close_secondary": c2,
                    "relative_close_difference": rel,
                }
        else:
            cross_source = {
                "status": "FAIL",
                "reason": "latest trade date mismatch or missing close",
                "latest_date_primary": d1,
                "latest_date_secondary": d2,
            }

    meta = dict(meta)
    meta["provider_attempts"] = attempts
    meta["cross_source_validation"] = cross_source
    meta["selected_provider"] = chosen_provider
    return rows, meta
