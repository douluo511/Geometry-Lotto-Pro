from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import tempfile

from app.business_validation import CostAssumptions, qualify_research
from app.domain import DailyBar
from app.netclient import NetClient
from app.source_market import fetch_daily_bars_failover


def synthetic_contract() -> dict:
    rows = []
    start = date(2025, 1, 1)
    close = 10.0
    for i in range(220):
        drift = 0.001 + (0.002 if i % 17 < 8 else -0.001)
        open_p = close
        close = close * (1.0 + drift)
        rows.append(DailyBar(
            symbol="600000",
            trade_date=(start + timedelta(days=i)).isoformat(),
            open=open_p,
            close=close,
            high=max(open_p, close) * 1.01,
            low=min(open_p, close) * 0.99,
            volume=1_000_000 + (i % 20) * 25_000,
            amount=(1_000_000 + (i % 20) * 25_000) * close,
            pct_change=drift * 100.0,
            turnover_rate=0.01 + (i % 20) * 0.0002,
            provider="synthetic_contract_only",
            raw_sha256="a" * 64,
        ))
    got = qualify_research(rows, {"provider": "synthetic_contract_only", "price_adjustment": "qfq"})
    required = [
        "cost_slippage_model", "liquidity_capacity", "corporate_action_adjustment",
        "leakage_safe_time_split", "oos_walk_forward", "bootstrap", "ablation",
        "stability", "multiple_testing_correction",
    ]
    for key in required:
        if got["gates"].get(key) != "PASS":
            raise AssertionError(f"synthetic methodological control did not PASS: {key}={got['gates'].get(key)}")
    if got["gates"]["survivorship_selection_control"] != "NOT VERIFIED":
        raise AssertionError("single-symbol selection must not claim survivorship-safe universe")
    if got["capital_deployment_ready"] is not False:
        raise AssertionError("business qualification must not enable capital deployment")
    return {"status": "PASS", "gates": got["gates"]}


def real_network_qualification() -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = NetClient(root / "network.jsonl", max_attempts=3)
        bars, meta = fetch_daily_bars_failover(client, "600000", 260)
        got = qualify_research(bars, meta, CostAssumptions())
        if got["status"] != "PASS":
            raise AssertionError("qualification execution did not PASS")
        if got["capital_deployment_ready"] is not False:
            raise AssertionError("real business gate must remain capital-deployment fail-closed")
        return got


def main() -> int:
    try:
        evidence = {
            "status": "PASS",
            "synthetic_method_contract": synthetic_contract(),
            "real_market_research_qualification": real_network_qualification(),
        }
    except Exception as exc:
        evidence = {"status": "FAIL", "error": repr(exc)}
        Path("business_qualification_evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        print(json.dumps(evidence, ensure_ascii=True))
        raise
    Path("business_qualification_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
