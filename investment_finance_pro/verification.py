from __future__ import annotations

import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import app


def _write(report: dict[str, Any], path: str) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def contract_test() -> dict[str, Any]:
    required_callables = {
        "one_click_update": 0,
        "repair_system": 0,
        "deterministic_self_test": 0,
        "network_smoke_test": 0,
        "compute_metrics": 1,
        "rank_research": 1,
    }
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    for name, arg_count in required_callables.items():
        fn = getattr(app, name, None)
        exists = callable(fn)
        checks[f"callable:{name}"] = exists
        if exists:
            sig = inspect.signature(fn)
            required = [
                p for p in sig.parameters.values()
                if p.default is inspect._empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
            checks[f"arity:{name}"] = len(required) == arg_count
            details[name] = str(sig)

    sample_rows = []
    price = 100.0
    for i in range(90):
        price *= 1.001
        sample_rows.append({
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1_000_000 + i,
        })
    metrics = app.compute_metrics(sample_rows)
    ranking = app.rank_research({"TEST": metrics})
    required_metric_keys = {
        "date", "close", "change_1d", "momentum_20d",
        "volatility_20d_ann", "max_drawdown_60d", "rows",
    }
    required_rank_keys = {
        "symbol", "close", "change_1d", "momentum_20d",
        "volatility_20d_ann", "max_drawdown_60d", "score", "status",
    }
    checks["metrics_schema"] = required_metric_keys.issubset(metrics.keys())
    checks["ranking_schema"] = bool(ranking) and required_rank_keys.issubset(ranking[0].keys())
    checks["unvalidated_guard"] = bool(ranking) and ranking[0]["status"] == "UNVALIDATED_RESEARCH_RANK"

    status = "PASS" if all(checks.values()) else "FAIL"
    return {"type": "contract_test", "status": status, "checks": checks, "details": details}


def fault_injection_test() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    original_market = app.fetch_market_history
    original_fred = app.fetch_fred_series
    original_cache_path = app.cache_path

    with tempfile.TemporaryDirectory() as td:
        temp_cache = Path(td) / "snapshot.json"
        app.cache_path = lambda: temp_cache

        try:
            app.fetch_market_history = lambda symbol: (_ for _ in ()).throw(RuntimeError("injected market failure"))
            app.fetch_fred_series = lambda series_id: (_ for _ in ()).throw(RuntimeError("injected macro failure"))
            failed = app.one_click_update()
            checks["all_provider_failure_is_FAILED"] = failed.get("update_state") == "FAILED"
            checks["failure_not_disguised_as_live_success"] = all(not p.get("ok") for p in failed.get("providers", []))

            def synthetic_market(symbol: str):
                rows = []
                price = 100.0
                for i in range(90):
                    price *= 1.001
                    rows.append({
                        "date": f"2026-02-{(i % 28) + 1:02d}",
                        "open": price, "high": price * 1.01, "low": price * 0.99,
                        "close": price, "volume": 1_000_000 + i,
                    })
                return rows, "InjectedMarket"

            app.fetch_market_history = synthetic_market
            app.fetch_fred_series = lambda series_id: (_ for _ in ()).throw(RuntimeError("injected macro failure"))
            partial = app.one_click_update()
            checks["partial_source_failure_is_PARTIAL"] = partial.get("update_state") == "PARTIAL"
            checks["partial_keeps_UNVALIDATED"] = partial.get("model_status") == "UNVALIDATED"

            temp_cache.write_text("{not-json", encoding="utf-8")
            repaired = app.repair_system()
            checks["corrupt_cache_explicitly_repaired"] = repaired.get("overall") == "PASS" and any(
                x.get("status") == "REPAIRED" for x in repaired.get("checks", [])
            )
        finally:
            app.fetch_market_history = original_market
            app.fetch_fred_series = original_fred
            app.cache_path = original_cache_path

    status = "PASS" if all(checks.values()) else "FAIL"
    return {"type": "fault_injection", "status": status, "checks": checks}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-test", action="store_true")
    parser.add_argument("--fault-injection", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    if args.contract_test:
        report = contract_test()
    elif args.fault_injection:
        report = fault_injection_test()
    else:
        raise SystemExit("Choose one verification mode")

    _write(report, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
