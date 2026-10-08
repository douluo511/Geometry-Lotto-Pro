from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import patch
import json
from pathlib import Path

from app.freshness import qualify_source_freshness, select_completed_market_rows
from app.domain import DailyBar
from app.source_eastmoney import fetch_daily_bars
from app.source_tencent import fetch_daily_bars_tencent
from app.source_tencent_full import fetch_daily_bars_tencent_full
from app.source_yahoo import fetch_daily_bars_yahoo
from tests.contract_gate import FakeClient, FakeTencentClient, FakeTencentFullClient, FakeYahooClient



def completed_session_selection_contract() -> dict:
    cross = {"status": "PASS", "providers": ["provider_a", "provider_b"]}
    def history(ending):
        last = date.fromisoformat(ending)
        return [DailyBar("600000", (last - timedelta(days=29-i)).isoformat(),
                         10, 10.1, 10.2, 9.9, 1000, 100000, 1.0, .01,
                         "contract_fixture", "a"*64) for i in range(30)]
    before_open = datetime(2026, 10, 8, 0, 50, tzinfo=timezone.utc)
    intraday = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)
    before_margin = datetime(2026, 10, 8, 7, 29, tzinfo=timezone.utc)
    margin = datetime(2026, 10, 8, 7, 30, tzinfo=timezone.utc)
    after_close = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    unfinished = replace(history("2026-09-30")[-1], trade_date="2026-10-08")
    cases = {}
    for label, now in (("before_open", before_open), ("intraday", intraday), ("before_margin", before_margin)):
        chosen, detail = select_completed_market_rows([*history("2026-09-30"), unfinished], now=now)
        assert chosen[-1].trade_date == "2026-09-30"
        assert detail["discarded_unfinished_dates"] == ["2026-10-08"]
        assert detail["raw_row_count"] == 31 and detail["completed_row_count"] == 30
        assert all(row.raw_sha256 == "a"*64 for row in chosen)
        qualified = qualify_source_freshness(chosen[-1].trade_date, cross,
            retrieved_at_unix=now.timestamp(), now=now)
        assert qualified["status"] == "PASS"
        cases[label] = detail
    for label, now in (("at_margin", margin), ("after_close", after_close)):
        chosen, detail = select_completed_market_rows([*history("2026-09-30"), unfinished], now=now)
        assert chosen[-1].trade_date == "2026-10-08"
        assert detail["discarded_unfinished_dates"] == []
        cases[label] = detail
    def must_reject(rows, now, expected_text):
        try:
            select_completed_market_rows(rows, now=now)
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError("invalid/stale/future provider rows must be rejected")
    must_reject(history("2026-09-29"), intraday, "missing the latest completed")
    must_reject(history("2026-09-30"), after_close, "missing the latest completed")
    must_reject([*history("2026-09-30"), replace(unfinished, trade_date="2026-10-09")], intraday, "outside today's unfinished")
    must_reject([*history("2026-09-30"), replace(unfinished, trade_date="2026-10-07")], intraday, "outside today's unfinished")
    holiday = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
    must_reject([*history("2026-09-30"), replace(unfinished, trade_date="2026-10-04")], holiday, "outside today's unfinished")
    must_reject([*history("2026-09-30"), replace(unfinished, open=float("nan"))], intraday, "non-finite")

    class EastIntraday(FakeClient):
        def get_json(self, *args, **kwargs):
            obj, meta = super().get_json(*args, **kwargs)
            obj["data"]["klines"].append("2026-10-08,10,10.1,10.2,9.9,1000,100000,1,1,0.1,2")
            return obj, meta
    class TencentIntraday(FakeTencentClient):
        def get_json(self, *args, **kwargs):
            obj, meta = super().get_json(*args, **kwargs)
            obj["data"]["sh600000"]["qfqday"].append(["2026-10-08","10","10.1","10.2","9.9","1000"])
            return obj, meta
    class FullIntraday(FakeTencentFullClient):
        def get_jsonp_object(self, *args, **kwargs):
            obj, meta = super().get_jsonp_object(*args, **kwargs)
            key = "qfqday" if "qfq" in args[2] else "day"
            obj["data"]["sh600000"][key].append(["2026-10-08","10","10.1","10.2","9.9","1000","unused","2.5","20"])
            return obj, meta
    class YahooIntraday(FakeYahooClient):
        def get_json(self, *args, **kwargs):
            obj, meta = super().get_json(*args, **kwargs)
            result = obj["chart"]["result"][0]
            result["timestamp"].append(int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp()))
            for field, value in {"open":10,"close":10.1,"high":10.2,"low":9.9,"volume":1000}.items():
                result["indicators"]["quote"][0][field].append(value)
            return obj, meta
    adapter_cases = {}
    with patch("app.freshness.datetime") as clock:
        clock.now.return_value = intraday
        for label, fetch, client, kwargs in (
            ("eastmoney", fetch_daily_bars, EastIntraday(), {}),
            ("tencent", fetch_daily_bars_tencent, TencentIntraday(), {}),
            ("tencent_full_qfq", fetch_daily_bars_tencent_full, FullIntraday(), {}),
            ("tencent_full_raw", fetch_daily_bars_tencent_full, FullIntraday(), {"adjustment":"raw"}),
            ("yahoo", fetch_daily_bars_yahoo, YahooIntraday(), {}),
            ("benchmark", fetch_daily_bars_yahoo, YahooIntraday(), {"ticker_override":"000001.SS"}),
        ):
            rows, meta = fetch(client, "600000", 40, **kwargs)
            assert rows[-1].trade_date == "2026-09-30"
            assert meta["completed_session_selection"]["discarded_unfinished_dates"] == ["2026-10-08"]
            assert meta["completed_session_selection"]["raw_row_count"] == 41
            assert rows[-1].raw_sha256 == meta["payload_sha256"]
            adapter_cases[label] = meta["completed_session_selection"]
    return {"status":"PASS", "time_boundary_cases":cases, "adapter_cases":adapter_cases,
            "stale_missing_future_nonfinite_rejection_cases":6,
            "scope":"offline selection contracts; real-network freshness still requires exact completed date"}


def main() -> int:
    cross = {"status": "PASS", "providers": ["provider_a", "provider_b"]}

    holiday_now = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)
    valid = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert valid["status"] == "PASS"
    assert valid["expected_completed_session"] == "2026-09-30"

    stale = qualify_source_freshness(
        "2026-09-29",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert stale["status"] == "FAIL"
    assert stale["reason"] == "market date does not equal latest completed SSE session"

    pre_reopen_close = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
    pre = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=pre_reopen_close.timestamp() - 60,
        now=pre_reopen_close,
    )
    assert pre["status"] == "PASS"
    assert pre["expected_completed_session"] == "2026-09-30"

    post_reopen_close = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    reopened = qualify_source_freshness(
        "2026-10-08",
        cross,
        retrieved_at_unix=post_reopen_close.timestamp() - 60,
        now=post_reopen_close,
    )
    assert reopened["status"] == "PASS"
    assert reopened["expected_completed_session"] == "2026-10-08"

    one_source = qualify_source_freshness(
        "2026-09-30",
        {"status": "NOT VERIFIED", "providers": ["provider_a"]},
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert one_source["status"] == "NOT VERIFIED"

    old_receipt = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 1800,
        now=holiday_now,
    )
    assert old_receipt["status"] == "FAIL"

    invalid_receipts = []
    for value in (float("nan"), float("inf"), -float("inf"), "invalid", True):
        rejected = qualify_source_freshness(
            "2026-09-30", cross, retrieved_at_unix=value, now=holiday_now,
        )
        assert rejected["status"] == "FAIL"
        assert rejected["reason"] == "invalid production retrieval timestamp"
        invalid_receipts.append(rejected)

    future_year = datetime(2027, 1, 2, 5, 0, tzinfo=timezone.utc)
    unsupported_calendar = qualify_source_freshness(
        "2026-12-31",
        cross,
        retrieved_at_unix=future_year.timestamp() - 60,
        now=future_year,
    )
    assert unsupported_calendar["status"] == "NOT VERIFIED"

    malformed = qualify_source_freshness(
        "not-a-date",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert malformed["status"] == "FAIL"

    evidence = {
        "status": "PASS",
        "completed_session_selection_contract": completed_session_selection_contract(),
        "authority": valid["authoritative_schedule_reference"],
        "cases": {
            "national_day_holiday_latest_completed_session": valid,
            "stale_market_date": stale,
            "reopen_before_daily_bar_settles": pre,
            "reopen_after_daily_bar_settles": reopened,
            "one_source": one_source,
            "old_receipt": old_receipt,
            "invalid_receipts_fail_closed": invalid_receipts,
            "unsupported_calendar_year": unsupported_calendar,
            "malformed": malformed,
        },
    }
    Path("source_freshness_contract_evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

