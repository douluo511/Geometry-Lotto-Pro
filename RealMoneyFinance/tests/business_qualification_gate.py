from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile

from app.business_validation import CostAssumptions, qualify_research
from app.domain import DailyBar
from app.netclient import NetClient
from app.source_corporate_actions import fetch_share_bonus_events, verify_corporate_action_lineage
from app.source_eastmoney import fetch_daily_bars as fetch_daily_bars_eastmoney
from app.source_market import fetch_daily_bars_failover
from app.source_universe import SSE_UNIVERSE_URL, UNIVERSE_URLS, build_prospective_universe_precommit, fetch_current_shanghai_universe_precommit
from app.source_tencent_full import fetch_daily_bars_tencent_full
from app.source_yahoo import fetch_daily_bars_yahoo
from app.source_cost_rules import fetch_official_cost_rules
from app.source_official_cash import fetch_official_cash_documents
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
    prospective = _prospective_survivorship_contract()
    return {
        "status": "PASS",
        "method_gates": got["method_gates"],
        "business_gates": got["gates"],
        "prospective_survivorship_contract": prospective,
    }


def _prospective_survivorship_contract() -> dict:
    entries = [
        {"symbol": f"{600000 + i:06d}", "name": f"fixture-{i:03d}"}
        for i in range(500)
    ]
    kwargs = {
        "asof_date": "2026-10-05",
        "retrieved_at_unix": 1791172800.0,
        "source_payload_sha256s": ["b" * 64],
        "code_source_sha": "a" * 40,
        "declared_total": 500,
        "min_symbols": 500,
    }
    first = build_prospective_universe_precommit(entries, **kwargs)
    second = build_prospective_universe_precommit(list(reversed(entries)), **kwargs)
    if first["precommit_sha256"] != second["precommit_sha256"]:
        raise AssertionError("prospective universe canonical hash depends on input order")
    changed_payload = build_prospective_universe_precommit(
        entries,
        **{**kwargs, "source_payload_sha256s": ["c" * 64]},
    )
    if first["precommit_sha256"] == changed_payload["precommit_sha256"]:
        raise AssertionError("prospective precommit must bind exact source payload hashes")
    changed_time = build_prospective_universe_precommit(
        entries,
        **{**kwargs, "retrieved_at_unix": kwargs["retrieved_at_unix"] + 1.0},
    )
    if first["precommit_sha256"] == changed_time["precommit_sha256"]:
        raise AssertionError("prospective precommit must bind exact retrieval time")
    if first["historical_survivorship_gate"] != "NOT VERIFIED":
        raise AssertionError("prospective snapshot must not promote historical survivorship gate")
    if first["policy"]["no_outcome_selection"] is not True:
        raise AssertionError("prospective universe must forbid outcome-based selection")
    try:
        build_prospective_universe_precommit(
            entries[:1],
            asof_date="2026-10-05",
            retrieved_at_unix=1791172800.0,
            source_payload_sha256s=["b" * 64],
            code_source_sha="a" * 40,
            declared_total=1,
            min_symbols=500,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("narrow one-symbol universe must fail the broad-universe precommit contract")

    class FailoverClient:
        def __init__(self, partial: bool = False):
            self.partial = partial
            self.calls = []

        def get_json(self, url, params, **kwargs):
            self.calls.append(url)
            if url == UNIVERSE_URLS[0]:
                raise RuntimeError("fixture primary host failure")
            rows = [
                {"f12": item["symbol"], "f13": 1, "f14": item["name"]}
                for item in (entries[:1] if self.partial else entries)
            ]
            return (
                {"data": {"total": 500, "diff": rows}},
                SimpleNamespace(
                    payload_sha256="c" * 64,
                    retrieved_at_unix=1791172800.0,
                    url=url,
                ),
            )

    class OfficialFallbackClient:
        def __init__(self, partial: bool = False):
            self.partial = partial
            self.calls = []

        def get_json(self, url, params, **kwargs):
            self.calls.append((url, dict(params)))
            if url in UNIVERSE_URLS:
                raise RuntimeError("fixture Eastmoney source failure")
            if url != SSE_UNIVERSE_URL:
                raise RuntimeError(f"unexpected fixture URL: {url}")
            stock_type = str(params.get("STOCK_TYPE"))
            if stock_type == "1":
                rows = [
                    {"A_STOCK_CODE": f"{600000 + i:06d}", "SEC_NAME_CN": f"main-{i:03d}"}
                    for i in range(250)
                ]
                digest = "d" * 64
            elif stock_type == "8":
                rows = [
                    {"A_STOCK_CODE": f"{688000 + i:06d}", "SEC_NAME_CN": f"star-{i:03d}"}
                    for i in range(250)
                ]
                digest = "e" * 64
            else:
                raise RuntimeError(f"unexpected stock type: {stock_type}")
            if self.partial:
                rows = rows[:1]
            return (
                {"result": rows},
                SimpleNamespace(
                    payload_sha256=digest,
                    retrieved_at_unix=1791172800.0,
                    url=url,
                ),
            )

    class DriftingTotalClient:
        def __init__(self):
            self.calls = []

        def get_json(self, url, params, **kwargs):
            self.calls.append((url, dict(params)))
            if url in UNIVERSE_URLS:
                page = int(params.get("pn", "1"))
                start = (page - 1) * 500
                rows = [
                    {
                        "f12": f"{600000 + i:06d}",
                        "f13": 1,
                        "f14": f"eastmoney-{i:04d}",
                    }
                    for i in range(start, start + 500)
                ]
                total = 1000 if page == 1 else 900
                return (
                    {"data": {"total": total, "diff": rows}},
                    SimpleNamespace(
                        payload_sha256=("1" if page == 1 else "2") * 64,
                        retrieved_at_unix=1791172800.0 + page,
                        url=url,
                    ),
                )
            if url != SSE_UNIVERSE_URL:
                raise RuntimeError(f"unexpected fixture URL: {url}")
            stock_type = str(params.get("STOCK_TYPE"))
            if stock_type == "1":
                rows = [
                    {
                        "A_STOCK_CODE": f"{600000 + i:06d}",
                        "SEC_NAME_CN": f"main-{i:03d}",
                    }
                    for i in range(250)
                ]
                digest = "3" * 64
            elif stock_type == "8":
                rows = [
                    {
                        "A_STOCK_CODE": f"{688000 + i:06d}",
                        "SEC_NAME_CN": f"star-{i:03d}",
                    }
                    for i in range(250)
                ]
                digest = "4" * 64
            else:
                raise RuntimeError(f"unexpected stock type: {stock_type}")
            return (
                {"result": rows},
                SimpleNamespace(
                    payload_sha256=digest,
                    retrieved_at_unix=1791172803.0,
                    url=url,
                ),
            )

    previous_source_sha = os.environ.get("SOURCE_SHA")
    os.environ["SOURCE_SHA"] = "a" * 40
    try:
        live_shape = fetch_current_shanghai_universe_precommit(
            FailoverClient(),
            page_size=500,
            max_pages=2,
            min_symbols=500,
        )
        if live_shape["status"] != "PASS" or live_shape["host_failover_used"] is not True:
            raise AssertionError("secondary-host fixture did not prove explicit failover")
        if UNIVERSE_URLS[1] not in live_shape["selected_source_urls"]:
            raise AssertionError("fallback host was not bound into precommit evidence")
        if live_shape["historical_survivorship_gate"] != "NOT VERIFIED":
            raise AssertionError("host failover must not promote historical survivorship gate")
        try:
            fetch_current_shanghai_universe_precommit(
                FailoverClient(partial=True),
                page_size=500,
                max_pages=1,
                min_symbols=500,
            )
        except (RuntimeError, ValueError):
            pass
        else:
            raise AssertionError("partial fallback universe must fail closed")

        official_shape = fetch_current_shanghai_universe_precommit(
            OfficialFallbackClient(),
            page_size=500,
            max_pages=1,
            min_symbols=500,
        )
        if official_shape["source_provider"] != "sse_official_current_shanghai_equity_universe":
            raise AssertionError("official SSE fallback provider was not bound into evidence")
        if official_shape["symbol_count"] != 500:
            raise AssertionError("official SSE main+STAR fixture did not produce the frozen broad universe")
        if SSE_UNIVERSE_URL not in official_shape["selected_source_urls"]:
            raise AssertionError("official SSE URL was not bound into precommit evidence")
        if official_shape["source_filter"] != "STOCK_TYPE=1,8;COMPANY_STATUS=2,4,5,7,8":
            raise AssertionError("official SSE evidence must bind its own board/status filter")
        if len(official_shape["source_payload_sha256s"]) != 2:
            raise AssertionError("official SSE precommit must bind both raw board payload hashes")
        if official_shape["historical_survivorship_gate"] != "NOT VERIFIED":
            raise AssertionError("official current universe must not backfill historical survivorship")
        drifting_shape = fetch_current_shanghai_universe_precommit(
            DriftingTotalClient(),
            page_size=500,
            max_pages=3,
            min_symbols=500,
        )
        if drifting_shape["source_provider"] != "sse_official_current_shanghai_equity_universe":
            raise AssertionError(
                "pagination-total drift must restart from the official SSE provider"
            )
        if drifting_shape["symbol_count"] != 500:
            raise AssertionError(
                "SSE restart after pagination drift did not produce the frozen broad universe"
            )
        if drifting_shape["host_failover_used"] is not True:
            raise AssertionError(
                "pagination-total drift must be recorded as an explicit provider failure"
            )
        if drifting_shape["historical_survivorship_gate"] != "NOT VERIFIED":
            raise AssertionError(
                "pagination-drift failover must not promote historical survivorship"
            )
        if not any(
            item.get("failure_kind") == "pagination_total_changed"
            for item in drifting_shape["host_attempts"]
        ):
            raise AssertionError(
                "pagination-total drift reason was not retained in precommit evidence"
            )

        try:
            fetch_current_shanghai_universe_precommit(
                OfficialFallbackClient(partial=True),
                page_size=500,
                max_pages=1,
                min_symbols=500,
            )
        except (RuntimeError, ValueError):
            pass
        else:
            raise AssertionError("partial official SSE universe must fail closed")
    finally:
        if previous_source_sha is None:
            os.environ.pop("SOURCE_SHA", None)
        else:
            os.environ["SOURCE_SHA"] = previous_source_sha

    return {
        "status": "PASS",
        "precommit_sha256": first["precommit_sha256"],
        "symbol_count": first["symbol_count"],
        "historical_survivorship_gate": first["historical_survivorship_gate"],
        "host_failover_contract": "PASS",
        "official_sse_fallback_contract": "PASS",
    }


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

def _corporate_action_lineage(client: NetClient, research_rows, research_meta) -> dict:
    try:
        if research_meta.get("provider") != "tencent_public_full_kline" or research_meta.get("price_adjustment") != "qfq":
            return {"status":"NOT VERIFIED", "point_in_time_lineage":"NOT VERIFIED",
                    "reason":"actual research provider lacks independently bound Tencent qfq content"}
        qfq_rows, qfq_meta = research_rows, research_meta
        raw_rows, raw_meta = fetch_daily_bars_tencent_full(client, "600000", QUALIFICATION_HISTORY_ROWS, adjustment="raw")
        events, event_meta = fetch_share_bonus_events(client, "600000", 100)
        event_meta["official_cash_action_evidence"]=fetch_official_cash_documents(client)
        evidence=verify_corporate_action_lineage(qfq_rows,raw_rows,events,qfq_meta,raw_meta,event_meta)
        evidence["official_cash_action_evidence"]=event_meta["official_cash_action_evidence"]
        return evidence
    except Exception as exc:
        return {
            "status": "NOT VERIFIED",
            "point_in_time_lineage": "NOT VERIFIED",
            "reason": "corporate-action real-network evidence could not be completed",
            "error": repr(exc),
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
        corporate_action_evidence = _corporate_action_lineage(client, bars, meta)
        got = qualify_research(
            bars,
            meta,
            CostAssumptions(),
            benchmark_rows=benchmark_rows,
            benchmark_meta=benchmark_meta,
            corporate_action_evidence=corporate_action_evidence,
        )
        got["corporate_action_real_network_evidence"] = corporate_action_evidence
        got["benchmark_fetch_error"] = benchmark_error
        try:
            prospective_universe = fetch_current_shanghai_universe_precommit(client)
        except Exception as exc:
            prospective_universe = {
                "status": "NOT VERIFIED",
                "scope": "PROSPECTIVE_PRECOMMIT_ONLY",
                "historical_survivorship_gate": "NOT VERIFIED",
                "reason": "current broad-universe precommit could not be completed",
                "error": repr(exc),
            }
        got["survivorship_prospective_precommit"] = prospective_universe
        if prospective_universe.get("status") == "PASS":
            got["qualification_gaps"]["survivorship_selection_control"] = (
                "A broad current Shanghai-equity universe is now immutably precommitted for "
                "prospective evaluation with source-payload and exact-commit binding, but the "
                "historical pre-asof research period is still not survivorship-safe and remains "
                "NOT VERIFIED."
            )
        if got["gates"].get("survivorship_selection_control") == "PASS":
            raise AssertionError(
                "prospective precommit alone must not promote historical survivorship qualification"
            )
        try:
            official_cost_rules = fetch_official_cost_rules(client)
        except Exception as exc:
            official_cost_rules = {
                "status": "NOT VERIFIED",
                "error": repr(exc),
                "scope": (
                    "official regulatory fee/tax calibration unavailable; broker commission and "
                    "observed execution slippage remain separately NOT VERIFIED"
                ),
            }
        got["official_cost_rule_evidence"] = official_cost_rules
        got["cost_calibration_components"] = {
            "official_exchange_fee_and_stamp_tax": (
                "PASS" if official_cost_rules.get("status") == "PASS" else "NOT VERIFIED"
            ),
            "broker_commission": "NOT VERIFIED",
            "observed_execution_slippage": "NOT VERIFIED",
        }
        if official_cost_rules.get("status") == "PASS":
            got["qualification_gaps"]["cost_slippage_model"] = (
                "Official exchange handling fee and securities stamp-tax schedule are verified "
                "from current authoritative pages, but broker commission and observed execution "
                "slippage remain NOT VERIFIED."
            )
        if got["gates"].get("cost_slippage_model") == "PASS":
            raise AssertionError("regulatory fee evidence alone must not promote full cost/slippage calibration")
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

