from __future__ import annotations
import json, os, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pandas as pd

PRODUCT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"))
from stock_ai import data_source as ds

INTRADAY = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
class FrozenClock:
    @staticmethod
    def now(tz=None):
        return INTRADAY.astimezone(tz) if tz is not None else INTRADAY.replace(tzinfo=None)

class Provider:
    def stock_zh_index_daily_em(self, **kwargs):
        return pd.DataFrame({"date": ["2026-09-30", "2026-10-08"], "close": [3800.0, 3810.0]})
    stock_zh_index_daily_tx = stock_zh_index_daily_em
    def stock_zh_a_hist(self, **kwargs):
        # Finite, correctly bounded canonicalizable real-provider fields.
        return pd.DataFrame({"date": ["2026-09-30", "2026-10-08"],
            "open": [10.0,10.0], "close": [10.1,10.1], "high": [10.2,10.2],
            "low": [9.9,9.9], "volume": [10000,10000], "amount": [100000,100000],
            "turnover_rate": [1.0,1.0]})

OBSERVED = {}
class CompletedDailyBarBoundary(unittest.TestCase):
    def test_index_maximum_is_not_completed_session_during_intraday(self):
        with patch.object(ds, "_ak", return_value=Provider()), patch.object(ds, "datetime", FrozenClock):
            actual = ds.fetch_expected_trade_date()
        OBSERVED["index_intraday_latest"] = actual
        self.assertEqual(actual, "2026-09-30", "Product accepted today's unfinished index day as completed")
    def test_unfinished_stock_bar_is_not_committed_as_complete_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "data" / "history").mkdir(parents=True)
            cfg = {"universe": {"history_start": "20180101", "history_adjust": "hfq"},
                   "network": {"timeout_seconds": 15}}
            with patch.object(ds, "ROOT", root), patch.object(ds, "datetime", FrozenClock):
                rows = ds.update_symbol_history("600000", cfg, provider=Provider())
            actual = pd.to_datetime(rows["date"]).max().strftime("%Y-%m-%d")
            persisted = pd.read_csv(root / "data" / "history" / "600000.csv")
            committed = pd.to_datetime(persisted["date"]).max().strftime("%Y-%m-%d")
        OBSERVED.update({"history_latest": actual, "persisted_latest": committed})
        self.assertEqual(actual, "2026-09-30", "Product retained today's unfinished stock daily bar")
        self.assertEqual(committed, "2026-09-30")

if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompletedDailyBarBoundary))
    receipt = {"schema": "stock-completed-session-first-fail-v1",
        "source_sha": os.environ.get("STOCK_SOURCE_SHA"),
        "fixed_china_time": "2026-10-08T10:00:00+08:00",
        "expected_completed": "2026-09-30", "observed": OBSERVED,
        "tests_run": result.testsRun, "failures": len(result.failures), "fixture_errors": len(result.errors),
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "scope": "offline product counterexamples; no real-network or Final claim"}
    (PRODUCT / "completed_session_first_fail_evidence.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt))
    raise SystemExit(0 if result.wasSuccessful() else 2)
