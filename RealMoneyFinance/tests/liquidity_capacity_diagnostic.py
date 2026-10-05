from __future__ import annotations

import hashlib
import json
import math
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.netclient import NetClient
from app.source_market import fetch_daily_bars_failover
from app.source_yahoo import fetch_daily_bars_yahoo

ROWS = 1200
MAX_PARTICIPATION = 0.05
SCENARIOS_CNY = [100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]

QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
QUOTE_UT = "fa5fd1943c7b386f172d6893dbfba10b"
QUOTE_FIELDS = ",".join([
    "f11", "f12", "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20",
    "f31", "f32", "f33", "f34", "f35", "f36", "f37", "f38", "f39", "f40",
    "f43", "f47", "f48", "f51", "f52", "f57", "f58", "f60", "f86", "f170",
])


def quantile(values, q):
    xs = sorted(float(x) for x in values)
    if not xs:
        raise ValueError("empty values")
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def _number(data, key):
    value = data.get(key)
    if value in (None, "", "-"):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def fetch_current_l1_snapshot(client: NetClient, symbol: str) -> dict:
    code = "".join(ch for ch in str(symbol) if ch.isdigit())
    if len(code) != 6:
        raise ValueError("symbol must contain exactly 6 digits")
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    obj, meta = client.get_json(
        QUOTE_URL,
        {
            "secid": f"{market}.{code}",
            "fltt": "2",
            "invt": "2",
            "ut": QUOTE_UT,
            "fields": QUOTE_FIELDS,
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    data = obj.get("data")
    if not isinstance(data, dict):
        raise ValueError("Eastmoney quote response missing data object")
    if str(data.get("f57") or "") != code:
        raise ValueError("Eastmoney quote symbol identity mismatch")

    bid1 = _number(data, "f19")
    bid1_volume = _number(data, "f20")
    ask1 = _number(data, "f39")
    ask1_volume = _number(data, "f40")
    last = _number(data, "f43")
    previous_close = _number(data, "f60")
    limit_up = _number(data, "f51")
    limit_down = _number(data, "f52")

    spread_bps = None
    order_book_status = "NOT VERIFIED"
    order_book_reason = "non-positive or incomplete top-of-book quote"
    if (
        bid1 is not None and ask1 is not None
        and bid1_volume is not None and ask1_volume is not None
        and bid1 > 0 and ask1 > 0 and ask1 >= bid1
        and bid1_volume > 0 and ask1_volume > 0
    ):
        mid = (bid1 + ask1) / 2.0
        spread_bps = (ask1 - bid1) / mid * 10000.0
        order_book_status = "SUPPORTED"
        order_book_reason = "non-zero public L1 best bid/ask snapshot observed"

    limit_price_status = "NOT VERIFIED"
    if (
        limit_up is not None and limit_down is not None
        and limit_up > 0 and limit_down > 0 and limit_up > limit_down
    ):
        limit_price_status = "SUPPORTED"

    return {
        "diagnostic_execution_status": "PASS",
        "provider": "eastmoney_public_l1_quote",
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "symbol": code,
        "name": data.get("f58"),
        "quote_time_raw": data.get("f86"),
        "last": last,
        "previous_close": previous_close,
        "pct_change": _number(data, "f170"),
        "turnover_volume": _number(data, "f47"),
        "turnover_amount_cny": _number(data, "f48"),
        "bid1": bid1,
        "bid1_volume": bid1_volume,
        "ask1": ask1,
        "ask1_volume": ask1_volume,
        "spread_bps": spread_bps,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "current_order_book_evidence": order_book_status,
        "current_order_book_reason": order_book_reason,
        "current_limit_price_evidence": limit_price_status,
        "scope": (
            "single retrieval-time public L1 snapshot only; does not establish historical spread, "
            "observed market impact, broker execution slippage, queue position, or limit fillability"
        ),
    }


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = NetClient(root / "network.jsonl", max_attempts=3)
        rows, meta = fetch_daily_bars_failover(client, "600000", ROWS)
        benchmark, bmeta = fetch_daily_bars_yahoo(
            client, "000001", ROWS, ticker_override="000001.SS"
        )
        try:
            l1_snapshot = fetch_current_l1_snapshot(client, "600000")
        except Exception as exc:
            l1_snapshot = {
                "diagnostic_execution_status": "NOT VERIFIED",
                "current_order_book_evidence": "NOT VERIFIED",
                "current_limit_price_evidence": "NOT VERIFIED",
                "error": repr(exc),
                "scope": (
                    "current public L1 snapshot unavailable; historical spread, market impact, "
                    "broker slippage and limit fillability remain NOT VERIFIED"
                ),
            }

    if len(rows) < 1000:
        raise RuntimeError(f"insufficient real-market rows: {len(rows)}")
    amounts = [float(r.amount or 0.0) for r in rows]
    if sum(1 for x in amounts if x > 0) / len(amounts) < 0.95:
        raise RuntimeError("daily amount coverage below diagnostic floor")

    capacities = [x * MAX_PARTICIPATION for x in amounts if x > 0]
    primary_dates = {r.trade_date for r in rows}
    benchmark_dates = {r.trade_date for r in benchmark}
    candidate_no_trade_dates = sorted(benchmark_dates - primary_dates)

    scenario = {}
    for notional in SCENARIOS_CNY:
        feasible = sum(1 for cap in capacities if cap >= notional)
        scenario[str(notional)] = {
            "notional_cny": notional,
            "feasible_days": feasible,
            "observed_days": len(capacities),
            "feasible_rate": feasible / len(capacities),
        }

    canonical = json.dumps(
        [{"date": r.trade_date, "amount": float(r.amount or 0.0)} for r in rows],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    current_spread = l1_snapshot.get("current_order_book_evidence", "NOT VERIFIED")
    current_limits = l1_snapshot.get("current_limit_price_evidence", "NOT VERIFIED")

    report = {
        "schema": "rmf-liquidity-capacity-diagnostic-v2",
        "status": "PASS",
        "symbol": "600000",
        "source_provider": meta.get("provider"),
        "source_price_adjustment": meta.get("price_adjustment"),
        "source_rows": len(rows),
        "source_asof": rows[-1].trade_date,
        "source_payload_sha256": meta.get("payload_sha256"),
        "benchmark_provider": bmeta.get("provider"),
        "benchmark_rows": len(benchmark),
        "max_participation_rate": MAX_PARTICIPATION,
        "amount_positive_coverage": sum(1 for x in amounts if x > 0) / len(amounts),
        "capacity_cny": {
            "min": min(capacities),
            "p10": quantile(capacities, 0.10),
            "p25": quantile(capacities, 0.25),
            "median": quantile(capacities, 0.50),
            "p90": quantile(capacities, 0.90),
            "max": max(capacities),
        },
        "order_notional_scenarios": scenario,
        "benchmark_trade_dates_missing_in_symbol_history": candidate_no_trade_dates,
        "candidate_no_trade_date_count": len(candidate_no_trade_dates),
        "daily_amount_series_sha256": hashlib.sha256(canonical).hexdigest(),
        "current_public_l1_snapshot": l1_snapshot,
        "evidence_boundary": {
            "amount_based_participation_capacity": "SUPPORTED",
            "daily_missing_date_no_trade_candidates": "SUPPORTED",
            "current_bid_ask_spread_snapshot": current_spread,
            "current_limit_price_snapshot": current_limits,
            "historical_bid_ask_spread": "NOT VERIFIED",
            "observed_market_impact": "NOT VERIFIED",
            "broker_execution_slippage": "NOT VERIFIED",
            "limit_up_down_fillability": "NOT VERIFIED",
            "full_cost_slippage_calibration_gate": "NOT VERIFIED",
            "full_liquidity_capacity_gate": "NOT VERIFIED",
            "capital_deployment_ready": False,
            "final_gate": "FAIL",
        },
    }
    Path("rmf_liquidity_capacity_diagnostic.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
