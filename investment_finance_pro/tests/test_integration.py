import pathlib
import sys
import unittest
from datetime import date, timedelta

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from engine import InvestmentEngine
from service import InvestmentService
from storage import SnapshotStorage


def receipt(tag):
    import base64, hashlib
    raw=("raw-"+tag).encode()
    return {
        "requested_url":"https://example.test/"+tag,
        "final_url":"https://example.test/"+tag,
        "http_status":200,
        "content_type":"application/json",
        "payload_hash":hashlib.sha256(raw).hexdigest(),
        "bytes":len(raw),
        "fetched_at":"2026-09-29T00:00:00+00:00",
        "attempts":[{"attempt":1,"outcome":"HTTP_RESPONSE","status_code":200}],
        "body_b64":base64.b64encode(raw).decode("ascii"),
        "crosscheck_status":"PASS",
    }


class FullNet:
    @staticmethod
    def rows():
        rows=[]; start=date(2026,1,1); price=100.0
        for i in range(100):
            price *= 1.001 + (0.0002 if i%5 else -0.0001)
            rows.append({
                "date":(start+timedelta(days=i)).isoformat(),
                "open":price,"high":price*1.01,"low":price*0.99,
                "close":price,"volume":1_000_000+i,
            })
        return rows
    def fetch_market_history(self,symbol):
        return self.rows(), "FixtureMarket", receipt("market-"+symbol)
    def fetch_us_treasury_10y(self):
        return {"series":"US_TREASURY_10Y","date":"2026-09-28","value":4.0}, receipt("treasury")
    def fetch_fred_series(self,series_id):
        return {"series":series_id,"date":"2026-09-28","value":4.25}, receipt("fred-"+series_id)
    def fetch_sec_companyfacts(self,symbol,cik):
        return {"symbol":symbol,"cik":cik,"fiscal_year":2025,"annual_diluted_eps":5.0,"filed":"2026-02-01","form":"10-K"}, receipt("sec-"+symbol)


class Ledger:
    def __init__(self): self.rows=[]
    def record(self,*args,**kwargs):
        self.rows.append((args,kwargs))


class IntegrationTests(unittest.TestCase):
    def test_service_engine_storage_full_pass_commits_valid_snapshot(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            storage=SnapshotStorage(pathlib.Path(td))
            ledger=Ledger()
            service=InvestmentService(net=FullNet(),storage=storage,engine=InvestmentEngine(),evidence=ledger)
            report=service.update_all()
            self.assertEqual(report["update_state"],"PASS")
            self.assertEqual(report["model_status"],"UNVALIDATED")
            self.assertTrue(report["ranking"])
            self.assertTrue(all(x["status"]=="UNVALIDATED_RESEARCH_RANK" for x in report["ranking"]))
            saved=storage.read()
            self.assertEqual(saved["update_state"],"PASS")
            self.assertNotIn("body_b64", saved["network_receipts"][0])
            self.assertTrue(ledger.rows[-1][1]["snapshot_committed"])


if __name__=="__main__":
    unittest.main()
