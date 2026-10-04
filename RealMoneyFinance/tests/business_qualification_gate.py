from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import tempfile

from app.business_validation import CostAssumptions, qualify_research
from app.domain import DailyBar
from app.netclient import NetClient
from app.source_eastmoney import fetch_daily_bars as fetch_daily_bars_eastmoney
from app.source_market import fetch_daily_bars_failover
from app.source_tencent_full import fetch_daily_bars_tencent_full
from app.source_yahoo import fetch_daily_bars_yahoo
from tests.business_failclosed_contract import run_contract

QUALIFICATION_HISTORY_ROWS = 1200


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
        "cost_slippage_model",
        "leakage_safe_time_split", "oos_walk_forward", "bootstrap", "ablation",
        "stability", "multiple_testing_correction",
    ]
    for key in required:
        if got["method_gates"].get(key) != "PASS":
            raise AssertionError(f"synthetic methodological control did not PASS: {key}={got['method_gates'].get(key)}")
    # Synthetic data may prove methodological mechanics such as dependence-aware
    # bootstrap or frozen search-family correction, but it must never promote
    # evidence-dependent production gates or full business qualification.
    for key in (
        "cost_slippage_model", "liquidity_capacity", "corporate_action_adjustment",
        "leakage_safe_time_split", "survivorship_selection_control", "ablation",
        "stability", "oos_walk_forward",
    ):
        if got["gates"].get(key) == "PASS":
            raise AssertionError(f"synthetic data must not promote production business gate: {key}")
    if got["business_qualification_status"] == "PASS":
        raise AssertionError("synthetic method execution cannot promote full business qualification")
    if got["gates"]["survivorship_selection_control"] != "NOT VERIFIED":
        raise AssertionError("single-symbol selection must not claim survivorship-safe universe")
    if got["capital_deployment_ready"] is not False:
        raise AssertionError("business qualification must not enable capital deployment")
    return {"status": "PASS", "method_gates": got["method_gates"], "business_gates": got["gates"]}


def _field_complete_ablation_replication(client: NetClient, reference_rows: list[DailyBar]) -> dict:
    """Use only real field-complete providers; every mismatch remains fail-closed."""
    attempts = []
    for provider_name, fetcher in (
        ("eastmoney_public_l1", fetch_daily_bars_eastmoney),
        ("tencent_public_full_kline", fetch_daily_bars_tencent_full),
    ):
        try:
            rows, meta = fetcher(client, "600000", 260)
        except Exception as exc:
            attempts.append({
                "provider": provider_name,
                "status": "FAIL",
                "reason": "field-complete production fetch failed",
                "error": repr(exc),
            })
            continue
        if not rows or not reference_rows:
            attempts.append({
                "provider": provider_name,
                "status": "NOT VERIFIED",
                "reason": "field-complete or reference rows missing",
            })
            continue

        latest = rows[-1]
        reference = reference_rows[-1]
        if latest.trade_date != reference.trade_date:
            attempts.append({
                "provider": provider_name,
                "status": "NOT VERIFIED",
                "reason": "field-complete source as-of date does not match primary qualification date",
                "field_complete_asof": latest.trade_date,
                "reference_asof": reference.trade_date,
            })
            continue
        rel = abs(float(latest.close) - float(reference.close)) / max(
            abs(float(latest.close)), abs(float(reference.close)), 1e-9
        )
        if rel > 0.02:
            attempts.append({
                "provider": provider_name,
                "status": "NOT VERIFIED",
                "reason": "field-complete source close differs from primary by more than 2%",
                "relative_close_difference": rel,
            })
            continue

        amount_ok = all(float(row.amount or 0.0) > 0 for row in rows)
        turnover_ok = all(
            row.turnover_rate is not None and float(row.turnover_rate) > 0 for row in rows
        )
        volume_ok = all(float(row.volume or 0.0) > 0 for row in rows)
        if not (amount_ok and turnover_ok and volume_ok):
            attempts.append({
                "provider": provider_name,
                "status": "NOT VERIFIED",
                "reason": "field-complete source lacks required amount/turnover/volume coverage",
                "amount_complete": amount_ok,
                "turnover_complete": turnover_ok,
                "volume_complete": volume_ok,
            })
            continue

        scoped_meta = dict(meta)
        scoped_meta["qualification_scope"] = "production_real_network"
        dedicated = qualify_research(rows, scoped_meta, CostAssumptions())
        gate = dedicated.get("gates", {}).get("ablation", "NOT VERIFIED")
        result = {
            "status": "PASS" if gate == "PASS" else "NOT VERIFIED",
            "provider": meta.get("provider"),
            "payload_sha256": meta.get("payload_sha256"),
            "asof": latest.trade_date,
            "rows": len(rows),
            "relative_close_difference": rel,
            "price_adjustment": meta.get("price_adjustment"),
            "amount_complete": amount_ok,
            "turnover_complete": turnover_ok,
            "volume_complete": volume_ok,
            "ablation_gate": gate,
            "ablation_results": dedicated.get("ablation_results", {}),
            "provider_attempts": attempts + [{
                "provider": provider_name,
                "status": "PASS" if gate == "PASS" else "NOT VERIFIED",
            }],
        }
        return result

    return {
        "status": "NOT VERIFIED",
        "reason": "no production provider produced verified field-complete ablation evidence",
        "provider_attempts": attempts,
    }

def real_network_qualification() -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = NetClient(root / "network.jsonl", max_attempts=3)
        bars, meta = fetch_daily_bars_failover(client, "600000", QUALIFICATION_HISTORY_ROWS)
        benchmark_rows = []
        benchmark_meta = {
            "qualification_scope": "NOT VERIFIED",
            "instrument_role": "benchmark_sse_composite",
        }
        benchmark_error = None
        try:
            benchmark_rows, benchmark_meta = fetch_daily_bars_yahoo(
                client, "000001", QUALIFICATION_HISTORY_ROWS, ticker_override="000001.SS"
            )
            benchmark_meta = dict(benchmark_meta)
            if benchmark_rows and benchmark_rows[-1].trade_date == bars[-1].trade_date:
                benchmark_meta["qualification_scope"] = "production_real_network_benchmark"
            else:
                benchmark_meta["qualification_scope"] = "NOT VERIFIED"
                benchmark_error = "benchmark as-of date does not match primary qualification date"
        except Exception as exc:
            benchmark_error = repr(exc)
        got = qualify_research(
            bars,
            meta,
            CostAssumptions(),
            benchmark_rows=benchmark_rows,
            benchmark_meta=benchmark_meta,
        )
        got["benchmark_fetch_error"] = benchmark_error
        field_complete_ablation = _field_complete_ablation_replication(client, bars)
        got["field_complete_ablation_replication"] = field_complete_ablation
        if field_complete_ablation.get("status") == "PASS":
            got["gates"]["ablation"] = "PASS"
            got["qualification_gaps"].pop("ablation", None)
        if got["status"] != "PASS":
            raise AssertionError("qualification execution did not PASS")
        if got["capital_deployment_ready"] is not False:
            raise AssertionError("real business gate must remain capital-deployment fail-closed")
        return got


def main() -> int:
    try:
        evidence = {
            "status": "PASS",
            "business_boundary_contract": run_contract(),
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

