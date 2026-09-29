import pathlib
import sys
import unittest
from datetime import date, timedelta

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from engine import InvestmentEngine


def rows(drift: float, shock_every: int = 0):
    out=[]; start=date(2026,1,1); price=100.0
    for i in range(100):
        move=drift
        if shock_every and i and i%shock_every==0:
            move-=0.08
        price=max(1.0,price*(1.0+move))
        out.append({
            "date":(start+timedelta(days=i)).isoformat(),
            "open":price,"high":price*1.01,"low":price*0.99,
            "close":price,"volume":1_000_000+i,
        })
    return out


class BusinessValidationTests(unittest.TestCase):
    def setUp(self):
        self.engine=InvestmentEngine()

    def test_business_output_is_research_only_not_action_signal(self):
        metrics={
            "UP":self.engine.compute_metrics(rows(0.002)),
            "FLAT":self.engine.compute_metrics(rows(0.0)),
        }
        ranked=self.engine.rank(metrics,{},{"US_10Y_TREASURY":{"value":4.0}})
        self.assertTrue(ranked)
        self.assertTrue(all(x["status"]=="UNVALIDATED_RESEARCH_RANK" for x in ranked))
        forbidden={"BUY","SELL","STRONG_BUY","STRONG_SELL","VALIDATED_EDGE"}
        self.assertTrue(all(x["status"] not in forbidden for x in ranked))

    def test_counterexample_missing_fundamentals_and_high_drawdown_do_not_create_false_certainty(self):
        metric=self.engine.compute_metrics(rows(0.001,shock_every=25))
        ranked=self.engine.rank({"RISKY":metric},{},{"US_10Y_TREASURY":{"value":5.0}})
        row=ranked[0]
        self.assertEqual(row["valuation"]["valuation_status"],"INSUFFICIENT_FUNDAMENTALS")
        self.assertIn(row["scenario"]["risk_state"],{"MEDIUM","HIGH"})
        self.assertEqual(row["status"],"UNVALIDATED_RESEARCH_RANK")

    def test_reversal_changes_ranking_but_never_validation_state(self):
        up=self.engine.compute_metrics(rows(0.002))
        down=self.engine.compute_metrics(rows(-0.001))
        first=self.engine.rank({"A":up,"B":down},{},{})
        second=self.engine.rank({"A":down,"B":up},{},{})
        self.assertNotEqual(first[0]["symbol"],second[0]["symbol"])
        self.assertTrue(all(x["status"]=="UNVALIDATED_RESEARCH_RANK" for x in first+second))


if __name__=="__main__":
    unittest.main()
