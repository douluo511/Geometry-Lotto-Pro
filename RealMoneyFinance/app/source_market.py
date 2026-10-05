from __future__ import annotations

from .freshness import qualify_source_freshness
from .netclient import NetClient
from .source_eastmoney import fetch_daily_bars as fetch_eastmoney
from .source_tencent import fetch_daily_bars_tencent
from .source_tencent_full import fetch_daily_bars_tencent_full
from .source_yahoo import fetch_daily_bars_yahoo


def _latest_close(rows):
    return (rows[-1].trade_date, float(rows[-1].close)) if rows else (None, None)


_PROVIDER_PRIORITY = {
    "tencent_public_full_kline": 4,
    "eastmoney_public_l1": 3,
    "tencent_public_kline": 2,
    "yahoo_public_chart": 1,
}

_PROVIDER_FAMILY = {
    "tencent_public_full_kline": "tencent",
    "tencent_public_kline": "tencent",
    "eastmoney_public_l1": "eastmoney",
    "yahoo_public_chart": "yahoo",
}


def _select_success(successes, requested_limit: int):
    """Select acquisition evidence without consulting returns, labels or model output."""
    requested = max(30, int(requested_limit))
    if not successes:
        raise ValueError("no successful providers to select")
    def rank(item):
        provider, rows, meta = item
        adjustment = str((meta or {}).get("price_adjustment", "")).lower()
        return (
            len(rows) >= requested,
            adjustment == "qfq",
            len(rows),
            _PROVIDER_PRIORITY.get(provider, 0),
        )
    return max(successes, key=rank)


def fetch_daily_bars_failover(client: NetClient, symbol: str, limit: int = 120):
    attempts = []
    successes = []

    for provider, fn in [
        ("eastmoney_public_l1", fetch_eastmoney),
        ("tencent_public_full_kline", fetch_daily_bars_tencent_full),
        ("tencent_public_kline", fetch_daily_bars_tencent),
        ("yahoo_public_chart", fetch_daily_bars_yahoo),
    ]:
        try:
            rows, meta = fn(client, symbol, limit)
            successes.append((provider, rows, meta))
            attempts.append({"provider": provider, "status": "PASS", "row_count": len(rows)})
        except Exception as exc:
            attempts.append({"provider": provider, "status": "FAIL", "error": repr(exc)})

    if not successes:
        raise RuntimeError(
            "all configured production market-data providers failed: "
            + __import__("json").dumps(attempts, ensure_ascii=True, sort_keys=True)
        )

    chosen_provider, rows, meta = _select_success(successes, limit)
    cross_source = {
        "status": "NOT VERIFIED",
        "reason": "only one production provider succeeded",
    }

    if len(successes) >= 2:
        chosen_family = _PROVIDER_FAMILY.get(chosen_provider, chosen_provider)
        remaining = [
            item for item in successes
            if _PROVIDER_FAMILY.get(item[0], item[0]) != chosen_family
        ]
        if not remaining:
            remaining = []
        if remaining:
            _, rows2, meta2 = _select_success(remaining, limit)
        if remaining:
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
        else:
            cross_source = {
                "status": "NOT VERIFIED",
                "reason": "no independently operated second production provider succeeded",
            }

    source_freshness = qualify_source_freshness(
        rows[-1].trade_date,
        cross_source,
        retrieved_at_unix=meta.get("retrieved_at_unix"),
    )
    if source_freshness["status"] != "PASS":
        raise RuntimeError(
            "production source freshness is not PASS: "
            + __import__("json").dumps(source_freshness, ensure_ascii=True, sort_keys=True)
        )

    meta = dict(meta)
    meta["source_freshness"] = source_freshness
    # This marker is issued only after a real provider succeeded, cross-source
    # freshness was evaluated and the source was accepted in this live call.
    meta["qualification_scope"] = "production_real_network"
    meta["provider_attempts"] = attempts
    meta["cross_source_validation"] = cross_source
    meta["selected_provider"] = chosen_provider
    meta["selection_policy"] = {
        "requested_rows": max(30, int(limit)),
        "coverage_first": True,
        "prefer_qfq_after_coverage": True,
        "then_row_count": True,
        "provider_priority_tiebreak": ["eastmoney_public_l1", "tencent_public_kline", "yahoo_public_chart"],
        "outcome_fields_used": False,
    }
    return rows, meta
