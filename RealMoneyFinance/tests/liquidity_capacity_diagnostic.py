from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path

from app.netclient import NetClient
from app.source_market import fetch_daily_bars_failover
from app.source_yahoo import fetch_daily_bars_yahoo

ROWS = 1200
MAX_PARTICIPATION = 0.05
SCENARIOS_CNY = [100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]


def quantile(values, q):
    xs = sorted(float(x) for x in values)
    if not xs:
        raise ValueError("empty values")
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = NetClient(root / "network.jsonl", max_attempts=3)
        rows, meta = fetch_daily_bars_failover(client, "600000", ROWS)
        benchmark, bmeta = fetch_daily_bars_yahoo(client, "000001", ROWS, ticker_override="000001.SS")

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

    report = {
        "schema": "rmf-liquidity-capacity-diagnostic-v1",
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
        "evidence_boundary": {
            "amount_based_participation_capacity": "SUPPORTED",
            "daily_missing_date_no_trade_candidates": "SUPPORTED",
            "historical_bid_ask_spread": "NOT VERIFIED",
            "observed_market_impact": "NOT VERIFIED",
            "broker_execution_slippage": "NOT VERIFIED",
            "limit_up_down_fillability": "NOT VERIFIED",
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
