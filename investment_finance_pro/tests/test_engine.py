import pathlib
import sys
import unittest
from datetime import date, timedelta

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from engine import InvestmentEngine


class EngineUnitTests(unittest.TestCase):
    def test_metrics_valuation_scenario_and_unvalidated_rank(self):
        engine=InvestmentEngine()
        rows=[]; start=date(2026,1,1); price=100.0
        for i in range(100):
            price*=1.001
            rows.append({
                "date":(start+timedelta(days=i)).isoformat(),
                "open":price,"high":price*1.01,"low":price*0.99,
                "close":price,"volume":1_000_000+i,
            })
        metric=engine.compute_metrics(rows)
        valuation=engine.valuation(metric["close"],{"annual_diluted_eps":5.0},4.0)
        scenario=engine.scenario(metric,valuation)
        rank=engine.rank({"TEST":metric},{"TEST":{"annual_diluted_eps":5.0}},{"US_10Y_TREASURY":{"value":4.0}})
        self.assertGreater(metric["close"],0)
        self.assertGreaterEqual(metric["volatility_20d_ann"],0)
        self.assertIsNotNone(valuation["pe_proxy"])
        self.assertIn(scenario["risk_state"],{"LOWER","MEDIUM","HIGH"})
        self.assertEqual(rank[0]["status"],"UNVALIDATED_RESEARCH_RANK")


if __name__=="__main__":
    unittest.main()
