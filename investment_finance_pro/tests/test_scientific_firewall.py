import pathlib
import sys
import unittest
from datetime import date, timedelta

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from engine import InvestmentEngine
from scientific_validation import run_scientific_firewall


class NullWorldNet:
    def fetch_market_history(self,symbol):
        symbols=["SPY","QQQ","AAPL","MSFT","NVDA","GOOGL","AMZN"]
        offset=symbols.index(symbol)
        rows=[]
        start=date(2026,1,1)
        price=100.0+offset
        for i in range(120):
            # deterministic alternating path with no persistent cross-sectional edge
            shock=(0.001 if (i+offset)%2==0 else -0.001)
            price *= 1.0+shock
            rows.append({
                "date":(start+timedelta(days=i)).isoformat(),
                "open":price,"high":price*1.005,"low":price*0.995,
                "close":price,"volume":1_000_000+i,
            })
        import base64,hashlib
        raw=("history-"+symbol).encode()
        receipt={
            "requested_url":"https://example.test/"+symbol,
            "final_url":"https://example.test/"+symbol,
            "http_status":200,
            "content_type":"application/json",
            "payload_hash":hashlib.sha256(raw).hexdigest(),
            "bytes":len(raw),
            "fetched_at":"2026-09-29T00:00:00+00:00",
            "attempts":[{"attempt":1,"outcome":"HTTP_RESPONSE","status_code":200}],
            "body_b64":base64.b64encode(raw).decode("ascii"),
        "crosscheck_status":"PASS",
        }
        return rows,"NullFixture",receipt


class ScientificFirewallTests(unittest.TestCase):
    def test_null_world_executes_full_oos_protocol_without_promotion(self):
        symbols=["SPY","QQQ","AAPL","MSFT","NVDA","GOOGL","AMZN"]
        report,receipts=run_scientific_firewall(NullWorldNet(),InvestmentEngine(),symbols)
        self.assertEqual(report["status"],"PASS")
        self.assertEqual(report["scientific_gate"],"PASS")
        self.assertEqual(report["model_status"],"UNVALIDATED")
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(report["edge_state"],"NO_EDGE")
        self.assertGreaterEqual(report["oos"]["n"],25)
        self.assertTrue(all(report["integrity_checks"].values()))
        self.assertEqual(len(receipts),len(symbols))

    def test_cost_stress_and_random_baseline_are_mandatory(self):
        symbols=["SPY","QQQ","AAPL","MSFT","NVDA","GOOGL","AMZN"]
        report,_=run_scientific_firewall(NullWorldNet(),InvestmentEngine(),symbols)
        self.assertIn("stress_cost_bootstrap95_lower",report["oos"])
        self.assertIn("random_mean_gain",report["baselines"])
        self.assertIn("momentum_only_mean_gain",report["baselines"])
        self.assertIn("risk_only_mean_gain",report["baselines"])


if __name__=="__main__":
    unittest.main()
