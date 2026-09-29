import pathlib
import sys
import unittest
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import InvestmentEngine
from service import InvestmentService


class MemoryStorage:
    def __init__(self, initial=None):
        self.data = initial
        self.writes = 0
    def read(self):
        return self.data
    def write(self, data):
        self.writes += 1
        self.data = data
        return data
    def repair(self):
        return {"status": "PASS", "overall": "PASS", "checks": []}
    def path(self):
        return pathlib.Path("memory.json")


class Ledger:
    def __init__(self):
        self.rows = []
    def record(self, kind, status, **kwargs):
        self.rows.append({"kind": kind, "status": status, **kwargs})
        return self.rows[-1]


class BadNet:
    def fetch_market_history(self, symbol):
        raise TimeoutError("injected market timeout")
    def fetch_fred_series(self, series_id):
        raise TimeoutError("injected macro timeout")
    def fetch_us_treasury_10y(self):
        raise TimeoutError("injected treasury timeout")
    def fetch_sec_companyfacts(self, symbol, cik):
        raise TimeoutError("injected SEC timeout")


class MarketOnlyNet(BadNet):
    @staticmethod
    def _rows():
        rows=[]
        start=date(2026,1,1)
        price=100.0
        for i in range(90):
            price *= 1.001
            rows.append({
                "date":(start+timedelta(days=i)).isoformat(),
                "open":price,
                "high":price*1.01,
                "low":price*0.99,
                "close":price,
                "volume":1_000_000+i,
            })
        return rows
    def fetch_market_history(self, symbol):
        return self._rows(), "InjectedMarket", {
            "requested_url":"https://example.test/market",
            "final_url":"https://example.test/market",
            "http_status":200,
            "content_type":"application/json",
            "payload_hash":"a"*64,
            "bytes":2,
            "fetched_at":"2026-09-29T00:00:00+00:00",
            "attempts":[{"attempt":1,"outcome":"HTTP_RESPONSE","status_code":200}],
            "body_b64":"e30=",
        }


def known_good():
    return {
        "app":"Investment Finance Pro",
        "version":"0.4.0",
        "research_only":True,
        "model_status":"UNVALIDATED",
        "update_state":"PASS",
        "updated_at_utc":"2026-09-28T00:00:00+00:00",
        "elapsed_seconds":1.0,
        "providers":[],
        "network_receipts":[],
        "macro":{},
        "fundamentals":{},
        "metrics":{"OLD":{"close":100.0}},
        "ranking":[],
    }


class FaultInjectionTests(unittest.TestCase):
    def test_all_network_failures_fail_closed_and_preserve_last_good(self):
        old=known_good()
        storage=MemoryStorage(initial=old.copy())
        ledger=Ledger()
        service=InvestmentService(
            net=BadNet(),
            storage=storage,
            engine=InvestmentEngine(),
            evidence=ledger,
        )
        result=service.update_all()
        self.assertEqual(result["update_state"], "FAILED")
        self.assertEqual(result["model_status"], "UNVALIDATED")
        self.assertTrue(all(not p["ok"] for p in result["providers"]))
        self.assertEqual(storage.data, old)
        self.assertEqual(storage.writes, 0)
        self.assertFalse(ledger.rows[-1]["snapshot_committed"])

    def test_partial_update_never_overwrites_known_good_and_stays_unvalidated(self):
        old=known_good()
        storage=MemoryStorage(initial=old.copy())
        ledger=Ledger()
        service=InvestmentService(
            net=MarketOnlyNet(),
            storage=storage,
            engine=InvestmentEngine(),
            evidence=ledger,
        )
        result=service.update_all()
        self.assertEqual(result["update_state"], "PARTIAL")
        self.assertEqual(result["model_status"], "UNVALIDATED")
        self.assertTrue(result["metrics"])
        self.assertTrue(all(row["status"]=="UNVALIDATED_RESEARCH_RANK" for row in result["ranking"]))
        self.assertEqual(storage.data, old)
        self.assertEqual(storage.writes, 0)
        self.assertFalse(ledger.rows[-1]["snapshot_committed"])


if __name__ == "__main__":
    unittest.main()
