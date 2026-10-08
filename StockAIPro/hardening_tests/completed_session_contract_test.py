from __future__ import annotations
import copy, json, os, sys, tempfile, unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd

PRODUCT = Path(__file__).resolve().parents[1]
VERSION = PRODUCT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(VERSION))
from stock_ai import completed_session as cs, data_source as ds, data_quality as dq, pipeline
CFG = json.loads((VERSION / "config.default.json").read_text(encoding="utf-8"))
INTRADAY = datetime(2026,10,8,2,0,tzinfo=timezone.utc)
AFTER_CLOSE = datetime(2026,10,8,7,30,tzinfo=timezone.utc)
CACHE_CLOCK = datetime(2026,9,24,10,0,tzinfo=timezone.utc)

def clock(value):
    class FixedClock:
        @staticmethod
        def now(tz=None):
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    return FixedClock

def dates_ending(rows=240, end="2026-09-24"):
    candidates = pd.bdate_range(end=end, periods=rows+60)
    accepted = [d for d in candidates if d.year != 2026 or cs.is_session(d.date(),"SZSE")]
    return pd.DatetimeIndex(accepted[-rows:])

def frame(dates, code="600000"):
    n = len(dates); prices = 10.0+np.arange(n)*0.001
    return pd.DataFrame({"date": dates, "code": [code]*n,
        "open": prices, "close": prices, "high": prices+0.1, "low": prices-0.1,
        "volume": [10000.0]*n, "amount": [100000.0]*n, "turnover_rate": [0.01]*n,
        "schema_version": [3]*n, "adjust_mode": ["hfq"]*n, "provider": ["eastmoney"]*n})

class Provider:
    def __init__(self, primary, fallback=None):
        self.primary, self.fallback = primary, fallback
        self.primary_calls, self.fallback_calls = 0, 0
    def stock_zh_a_hist(self, **kwargs):
        self.primary_calls += 1
        return self.primary.copy()
    def stock_zh_a_hist_tx(self, **kwargs):
        self.fallback_calls += 1
        if self.fallback is None:
            raise RuntimeError("fallback unavailable")
        return self.fallback.copy()
    def stock_zh_index_daily_em(self, **kwargs):
        self.primary_calls += 1
        return self.primary.copy()
    def stock_zh_index_daily_tx(self, **kwargs):
        self.fallback_calls += 1
        if self.fallback is None:
            raise RuntimeError("fallback unavailable")
        return self.fallback.copy()

class CompletedSessionContracts(unittest.TestCase):
    def test_three_independent_calendar_sources_and_security_mapping(self):
        self.assertEqual(set(cs.CALENDARS), {"SSE","SZSE","BSE"})
        urls = [v["url"] for v in cs.CALENDARS.values()]
        self.assertEqual(len(set(urls)),3)
        for code, market in (("600000","SSE"),("000001","SZSE"),("300308","SZSE"),("920001","BSE"),("430001","BSE"),("830001","BSE")):
            with self.subTest(code=code): self.assertEqual(cs.market_for_code(code),market)
        for bad in ("900001","bad","123","600000x"):
            with self.subTest(code=bad), self.assertRaises(cs.CompletedSessionUnavailable):
                cs.market_for_code(bad)

    def test_completed_session_boundaries_all_markets(self):
        cases = [
            ("2026-10-08T00:00:00+00:00","2026-09-30"),
            ("2026-10-08T02:00:00+00:00","2026-09-30"),
            ("2026-10-08T07:29:59+00:00","2026-09-30"),
            ("2026-10-08T07:30:00+00:00","2026-10-08"),
            ("2026-10-08T12:00:00+00:00","2026-10-08"),
            ("2026-10-01T12:00:00+00:00","2026-09-30"),
            ("2026-10-10T12:00:00+00:00","2026-10-09"),
            ("2026-09-25T12:00:00+00:00","2026-09-24"),
            ("2026-02-14T12:00:00+00:00","2026-02-13"),
        ]
        for market in cs.CALENDARS:
            for instant, expected in cases:
                with self.subTest(market=market,time=instant):
                    context = cs.completed_session_context(datetime.fromisoformat(instant),markets=(market,))
                    self.assertEqual(context["expected_completed_session"],expected)
                    self.assertEqual(context["status"],"PASS")
                    self.assertEqual(len(context["calendar_sha256"]),64)

    def test_unknown_calendar_year_or_timezone_is_not_verified(self):
        for instant, markets in ((datetime(2027,1,8,tzinfo=timezone.utc),("SSE",)),
                                 (datetime(2026,10,8),("SSE",)),(INTRADAY,("UNKNOWN",)),
                                 (INTRADAY,())):
            with self.subTest(markets=markets), self.assertRaises(cs.CompletedSessionUnavailable):
                cs.completed_session_context(instant,markets=markets)
        with patch.dict(cs.CALENDARS,{"SSE":cs.CALENDARS["SSE"]},clear=True), self.assertRaises(cs.CompletedSessionUnavailable):
            cs.completed_session_context(INTRADAY)

    def test_only_legal_intraday_today_is_discarded_and_raw_is_unchanged(self):
        raw = frame(["2026-09-30","2026-10-08"])
        before = raw.copy(deep=True)
        for market in cs.CALENDARS:
            accepted, receipt = cs.select_completed_daily_frame(raw,market=market,now=INTRADAY)
            self.assertEqual(accepted["date"].dt.strftime("%Y-%m-%d").tolist(),["2026-09-30"])
            self.assertEqual(receipt["discarded_unfinished_dates"],["2026-10-08"])
            self.assertTrue(receipt["latest_equals_oracle"])
        pd.testing.assert_frame_equal(raw,before)
        accepted, _ = cs.select_completed_daily_frame(raw,market="SSE",now=AFTER_CLOSE)
        self.assertEqual(len(accepted),2)

    def test_future_closed_missing_completed_and_today_only_are_rejected(self):
        for rows, now in ((["2026-09-30","2026-10-09"],INTRADAY),
                          (["2026-09-30","2026-10-01"],INTRADAY),
                          (["2026-09-25","2026-09-30"],INTRADAY),
                          (["2026-09-30","2026-10-10"],AFTER_CLOSE),
                          (["2026-09-30"],AFTER_CLOSE),
                          (["2026-10-08"],INTRADAY)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                cs.select_completed_daily_frame(frame(rows),market="SSE",now=now)

    def test_malformed_unfinished_numbers_dates_and_duplicates_are_rejected(self):
        for column, value in (("close",np.nan),("close",np.inf),("volume",-1),("amount",np.nan)):
            invalid = frame(["2026-09-30","2026-10-08"]); invalid.loc[1,column] = value
            with self.subTest(column=column,value=value), self.assertRaises(ValueError):
                cs.select_completed_daily_frame(invalid,market="SSE",now=INTRADAY)
        for values in (["2026-09-30","2026-09-30"],["2026-09-30","bad"],
                       ["2026-09-30","2026-10-08 10:00:00"],
                       [pd.Timestamp("2026-09-30"),pd.Timestamp("2026-10-08T00:00:00+08:00")]):
            with self.subTest(values=str(values)), self.assertRaises((ValueError,TypeError)):
                cs.select_completed_daily_frame(frame(values),market="SSE",now=INTRADAY)

    def test_normalizer_cannot_drop_nan_close_or_duplicate_to_conceal_failure(self):
        for raw in (frame(["2026-09-30","2026-09-30"]),
                    frame(["2026-09-30","2026-10-08"])):
            if raw["date"].iloc[-1] == "2026-10-08": raw.loc[1,"close"] = np.nan
            with self.assertRaises((ValueError,RuntimeError)):
                ds._normalize_hist(raw,"600000","hfq","eastmoney")

    def test_real_update_primary_and_fallback_apply_completion_before_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/"data"/"history").mkdir(parents=True)
            for code in ("600000","000001","920001"):
                provider = Provider(frame(["2026-09-30","2026-10-08"],code))
                with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(INTRADAY)):
                    selected = ds.update_symbol_history(code,CFG,provider=provider)
                persisted = pd.read_csv(root/"data"/"history"/(code+".csv"))
                self.assertEqual(pd.to_datetime(persisted["date"]).max().strftime("%Y-%m-%d"),"2026-09-30")
                self.assertEqual(len(selected),1)
                receipt = json.loads((root/"evidence"/"history_completed_sessions"/(code+".json")).read_text())
                self.assertEqual(receipt["source_selection"]["discarded_unfinished_dates"],["2026-10-08"])
            provider = Provider(frame(["2026-09-30","2026-10-09"]),
                                frame(["2026-09-30","2026-10-08"]))
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(INTRADAY)):
                selected = ds.update_symbol_history("600001",CFG,provider=provider)
            self.assertEqual(provider.primary_calls,1); self.assertEqual(provider.fallback_calls,1)
            self.assertEqual(selected["provider"].iloc[-1],"tencent")

    def test_all_invalid_sources_preserve_cache_and_never_count_live_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/"data"/"history").mkdir(parents=True)
            target = root/"data"/"history"/"600000.csv"
            frame(["2026-09-30"]).to_csv(target,index=False)
            original = target.read_bytes()
            provider = Provider(frame(["2026-09-30","2026-10-09"]),frame(["2026-09-30"]))
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(AFTER_CLOSE)), patch.object(ds,"_ak",return_value=provider):
                status = ds.update_live_histories(pd.DataFrame({"code":["600000"]}),CFG)
            self.assertEqual(status["ok"],0); self.assertEqual(len(status["failed"]),1)
            self.assertEqual(target.read_bytes(),original)
            self.assertFalse((root/"evidence"/"history_completed_sessions"/"600000.json").exists())

    def test_index_source_also_rejects_future_and_requires_exact_calendar_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider = Provider(frame(["2026-09-30","2026-10-09"]),
                                frame(["2026-09-30","2026-10-08"]))
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(INTRADAY)), patch.object(ds,"_ak",return_value=provider):
                self.assertEqual(ds.fetch_expected_trade_date(),"2026-09-30")
            receipt = json.loads((root/"evidence"/"completed_session_oracle.json").read_text())
            self.assertEqual(receipt["benchmark_provider"],"tencent")
            self.assertEqual(receipt["status"],"PASS")
            stale = Provider(frame(["2026-09-30"]),frame(["2026-09-30"]))
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(AFTER_CLOSE)), patch.object(ds,"_ak",return_value=stale):
                self.assertIsNone(ds.fetch_expected_trade_date())
            self.assertEqual(json.loads((root/"evidence"/"completed_session_oracle.json").read_text())["status"],"NOT VERIFIED")

    def test_missing_oracle_never_queries_source_or_certifies_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); master = pd.DataFrame({"code":["000001"],"status":["current"]})
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(datetime(2027,1,8,tzinfo=timezone.utc))), patch.object(ds,"_ak",return_value=object()) as provider, patch.object(ds,"_run_history_batch") as batch:
                self.assertIsNone(ds.fetch_expected_trade_date())
                provider.assert_not_called()
                coverage = ds.qualify_research_pool_coverage(master,CFG)
                self.assertEqual(coverage["qualification_status"],"NOT VERIFIED")
                self.assertEqual(coverage["covered_symbols"],0)
                batch.assert_not_called()

    def test_current_cache_exactness_and_explicit_delisted_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = root/"data"/"history"; folder.mkdir(parents=True)
            old = frame(pd.bdate_range("2024-01-02",periods=240),"000001")
            old.to_csv(folder/"000001.csv",index=False)
            fresh = frame(dates_ending(),"000002"); fresh.to_csv(folder/"000002.csv",index=False)
            with patch.object(ds,"ROOT",root), patch.object(ds,"datetime",clock(CACHE_CLOCK)):
                self.assertFalse(ds._history_cache_entry_valid(folder/"000001.csv","000001",CFG))
                self.assertTrue(ds._history_cache_entry_valid(folder/"000001.csv","000001",CFG,lifecycle="delisted"))
                self.assertTrue(ds._history_cache_entry_valid(folder/"000002.csv","000002",CFG))
                master = pd.DataFrame({"code":["000001","000002"],"status":["current","current"]})
                self.assertEqual(ds._research_coverage_snapshot(master)["covered_symbols"],1)
                master.loc[0,"status"] = "delisted"
                self.assertEqual(ds._research_coverage_snapshot(master)["covered_symbols"],2)
                master.loc[0,"status"] = "unknown"
                self.assertEqual(ds._research_coverage_snapshot(master)["covered_symbols"],1)

    def test_quality_and_production_consumers_cannot_inherit_stale_pass(self):
        stale, fresh = frame(["2026-09-30"],"000001"), frame(["2026-10-08"],"000002")
        quality = dq.inspect_histories({"000001":stale},expected_trade_date="2026-10-08")
        self.assertEqual(quality["good"],0); self.assertEqual(quality["completed_session_qualification"],"NOT VERIFIED")
        self.assertEqual(dq.inspect_histories({"000002":fresh},expected_trade_date="2026-10-08")["completed_session_qualification"],"PASS")
        self.assertEqual(dq.inspect_histories({"000002":fresh})["completed_session_qualification"],"NOT VERIFIED")
        current = pipeline._completed_production_histories({"000001":stale,"000002":fresh},"2026-10-08")
        self.assertEqual(set(current),{"000002"})
        master = pd.DataFrame({"code":["000001","000002"],"status":["delisted","current"]})
        historical = pipeline._completed_production_histories({"000001":stale,"000002":fresh},"2026-10-08",master)
        self.assertEqual(set(historical),{"000001","000002"})
        for actual, expected in (("2026-10-08","2026-09-30"),("2026-09-30","2026-10-08"),("2026-10-08",None),(None,"2026-10-08"),("2026-99-99","2026-10-08")):
            with self.subTest(actual=actual,expected=expected), self.assertRaises(cs.CompletedSessionUnavailable):
                cs.require_exact_completed_asof(actual,expected)

    def test_completion_rollover_cannot_promote_cached_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); master = pd.DataFrame({"code":["000001"],"status":["current"]})
            before = {"expected_completed_session":"2026-09-30"}
            after = {"expected_completed_session":"2026-10-08"}
            with patch.object(ds,"ROOT",root), patch.object(ds,"completed_session_context",side_effect=[before,after]), patch.object(ds,"_validated_history_codes",return_value={"000001"}):
                receipt = ds.qualify_research_pool_coverage(master,CFG)
            self.assertEqual(receipt["qualification_status"],"NOT VERIFIED")
            self.assertIn("changed",receipt["completed_session_reason"])

    def test_unavailable_completion_records_blocked_no_trade_in_real_run_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = Mock()
            with patch.object(pipeline,"ROOT",root), patch.object(pipeline,"load_config",return_value=CFG), patch.object(pipeline,"ensure_dirs"), patch.object(pipeline,"setup_logging",return_value=log), patch.object(pipeline,"close_logging"), patch.object(pipeline,"process_lock",return_value=nullcontext()), patch.object(pipeline,"_run_locked",side_effect=cs.CompletedSessionUnavailable("oracle unavailable; NO_TRADE")):
                with self.assertRaises(cs.CompletedSessionUnavailable): pipeline.run()
            receipt = json.loads((root/"state"/"last_run.json").read_text())
            self.assertEqual(receipt["status"],"BLOCKED")
            self.assertEqual(receipt["business_status"],"NOT_VERIFIED")
            self.assertEqual(receipt["decision"]["decision"],"NO_TRADE")

if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompletedSessionContracts))
    receipt = {"schema":"stock-completed-session-contract-v1","source_sha":os.environ.get("STOCK_SOURCE_SHA"),
        "status":"PASS" if result.wasSuccessful() else "FAIL","tests_run":result.testsRun,
        "failures":len(result.failures),"errors":len(result.errors),
        "markets":["SSE","SZSE","BSE"],"calendar_year":2026,
        "scope":"deterministic actual-consumer regressions; no real-network, PIT, EXE, GUI or Final claim"}
    (PRODUCT/"completed_session_contract_evidence.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt))
    raise SystemExit(0 if result.wasSuccessful() else 2)
