from __future__ import annotations

from pathlib import Path
import json
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

from app.domain import DailyBar
from app.engine import analyze_observable_activity, reverse_validation
from app.source_eastmoney import fetch_daily_bars
from app.source_market import _select_success
from app.source_tencent import fetch_daily_bars_tencent
from app.source_tencent_full import fetch_daily_bars_tencent_full
from app.source_yahoo import fetch_daily_bars_yahoo
from app.storage import Storage


class FakeClient:
    def get_json(self, url, params, headers=None):
        assert headers and headers.get("Referer") == "https://quote.eastmoney.com/"
        meta = SimpleNamespace(
            status=200,
            payload_sha256="a" * 64,
            retrieved_at_unix=1.0,
            url=url,
        )
        rows = []
        start = date(2026, 7, 1)
        for i in range(40):
            day = (start + timedelta(days=i)).isoformat()
            rows.append(f"{day},10,10.1,10.2,9.9,{1000+i},{100000+i*1000},1,1.0,0.1,{2.0+i/100}")
        return {"data": {"klines": rows}}, meta



class FakeTencentClient:
    def get_json(self, url, params, headers=None, allow_mislabeled_json=False):
        meta = SimpleNamespace(
            status=200,
            payload_sha256="b" * 64,
            retrieved_at_unix=2.0,
            url=url,
            content_type="text/html; charset=utf-8",
            content_type_policy="provider-mislabeled-strict-json-body",
        )
        rows = []
        start = date(2026, 7, 1)
        for i in range(40):
            day = (start + timedelta(days=i)).isoformat()
            rows.append([day, "10", "10.1", "10.2", "9.9", str(1000+i), {"meta": i}])
        return {"data": {"sh600000": {"qfqday": rows}}}, meta


class FakeTencentFullClient:
    def get_jsonp_object(self, url, params, expected_variable, headers=None):
        meta = SimpleNamespace(
            status=200,
            payload_sha256="d" * 64,
            retrieved_at_unix=4.0,
            url=url,
            content_type="application/javascript; charset=utf-8",
            content_type_policy="strict-assignment-json",
        )
        rows = []
        start = date(2026, 7, 1)
        for i in range(40):
            day = (start + timedelta(days=i)).isoformat()
            rows.append([
                day, "10", "10.1", "10.2", "9.9", str(1000+i),
                "unused", "2.5", str(20+i),
            ])
        key = "qfqday" if "qfq" in expected_variable else "day"
        return {"data": {"sh600000": {key: rows}}}, meta


class FakeYahooClient:
    def get_json(self, url, params, headers=None):
        meta = SimpleNamespace(
            status=200,
            payload_sha256="c" * 64,
            retrieved_at_unix=3.0,
            url=url,
            content_type="application/json; charset=utf-8",
            content_type_policy="header-json",
        )
        base = 1780000000
        timestamps = [base + i * 86400 for i in range(40)]
        quote = {
            "open": [10 + i / 100 for i in range(40)],
            "close": [10.1 + i / 100 for i in range(40)],
            "high": [10.2 + i / 100 for i in range(40)],
            "low": [9.9 + i / 100 for i in range(40)],
            "volume": [1000 + i for i in range(40)],
        }
        return {"chart": {"result": [{"timestamp": timestamps, "indicators": {"quote": [quote]}}], "error": None}}, meta

def main() -> int:
    bars, meta = fetch_daily_bars(FakeClient(), "600000", 40)
    assert len(bars) == 40
    assert meta["provider"] == "eastmoney_public_l1"

    tencent_bars, tmeta = fetch_daily_bars_tencent(FakeTencentClient(), "600000", 40)
    assert len(tencent_bars) == 40
    assert all(x.amount == 0.0 for x in tencent_bars)
    assert all(x.raw_sha256 == "b" * 64 for x in tencent_bars)
    assert tmeta["provider"] == "tencent_public_kline"

    tfull_bars, tfull_meta = fetch_daily_bars_tencent_full(FakeTencentFullClient(), "600000", 40)
    assert len(tfull_bars) == 40
    assert all(x.amount > 0 for x in tfull_bars)
    assert all(x.turnover_rate is not None and x.turnover_rate > 0 for x in tfull_bars)
    assert all(x.volume > 0 for x in tfull_bars)
    assert all(x.raw_sha256 == "d" * 64 for x in tfull_bars)
    assert tfull_meta["provider"] == "tencent_public_full_kline"
    assert tfull_meta["price_adjustment"] == "qfq"
    assert tfull_meta["unit_contract"] == "volume=shares; turnover_rate=fraction; amount=CNY"

    raw_full_bars, raw_full_meta = fetch_daily_bars_tencent_full(
        FakeTencentFullClient(), "600000", 40, adjustment="raw"
    )
    assert len(raw_full_bars) == 40
    assert raw_full_meta["price_adjustment"] == "unadjusted"
    assert raw_full_meta["requested_adjustment"] == "none"

    yahoo_bars, ymeta = fetch_daily_bars_yahoo(FakeYahooClient(), "600000", 40)
    assert len(yahoo_bars) == 40
    assert all(x.amount == 0.0 for x in yahoo_bars)
    assert all(x.raw_sha256 == "c" * 64 for x in yahoo_bars)
    assert ymeta["provider"] == "yahoo_public_chart"

    short_qfq = ("tencent_public_kline", tencent_bars * 8, {**tmeta, "price_adjustment": "qfq"})
    long_unadjusted = ("yahoo_public_chart", yahoo_bars * 20, {**ymeta, "price_adjustment": "unadjusted"})
    selected = _select_success([short_qfq, long_unadjusted], 800)
    assert selected[0] == "yahoo_public_chart", "requested history coverage must outrank adjustment preference"

    long_qfq = ("tencent_public_kline", tencent_bars * 20, {**tmeta, "price_adjustment": "qfq"})
    selected = _select_success([long_qfq, long_unadjusted], 800)
    assert selected[0] == "tencent_public_kline", "qfq must win only after requested coverage is met"

    equal_eastmoney = ("eastmoney_public_l1", bars * 20, {**meta, "price_adjustment": "qfq"})
    selected = _select_success([long_qfq, equal_eastmoney], 800)
    assert selected[0] == "eastmoney_public_l1", "fixed provider order must resolve equal evidence deterministically"

    obs = analyze_observable_activity(bars)
    assert obs.true_capital_identity == "UNAVAILABLE_FROM_PUBLIC_LEVEL1"
    rv = reverse_validation(obs)
    assert rv["production_identity_claim_allowed"] is False

    with tempfile.TemporaryDirectory() as td:
        s = Storage(Path(td))
        assert s.integrity_check() == "ok"
        assert s.upsert_bars(bars) == 40
        loaded = s.load_bars("600000")
        assert len(loaded) == 40
        s.save_observation(obs)

    evidence = {
        "status": "PASS",
        "contract": "public L1 stays non-identity-grade",
        "storage": "PASS",
        "engine_boundary": "PASS",
        "failover_selection_policy": "coverage_then_adjustment_then_rows_then_fixed_provider_order",
    }
    Path("contract_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
