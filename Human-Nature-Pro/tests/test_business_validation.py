import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from service import create_service


class BusinessValidationTests(unittest.TestCase):
    def setUp(self):
        self.service=create_service(bundled_path=ROOT/"knowledge_base.json")

    def test_business_core_outputs_competing_hypotheses_and_safety_boundary(self):
        result=self.service.analyze(
            "客户说预算不够，付款审批还没下来，也不清楚最终决定权在谁。",
            "保护利益并尽量保留长期合作",
        )
        self.assertGreaterEqual(len(result["hypotheses"]),8)
        self.assertTrue(result["five_why"])
        self.assertTrue(result["reverse_validation"])
        self.assertTrue(all(h["evidence_against"] for h in result["hypotheses"]))
        self.assertIn("不把推测当事实",result["guardrail"])
        self.assertIn("不提供欺骗",result["guardrail"])

    def test_counterexample_strong_motive_claim_remains_inference_not_fact(self):
        result=self.service.analyze(
            "我肯定他故意压价，一定是在针对我。",
            "保护利益",
        )
        state=result["state"]
        self.assertFalse(any("肯定他故意" in x for x in state["facts"]))
        self.assertTrue(any("肯定他故意" in x for x in state["inferences"]))
        self.assertLess(max(h["score"] for h in result["hypotheses"]),0.5)
        self.assertTrue(all(h["missing_evidence"] for h in result["hypotheses"]))

    def test_reversal_evidence_changes_leading_hypothesis_without_turning_it_into_fact(self):
        resource=self.service.analyze(
            "价格、钱、预算、付款、资源、期限、成本都受限制。",
            "保护利益",
        )
        identity=self.service.analyze(
            "他很在意面子和尊重，随后否认、指责、冷淡、生气。",
            "保护关系",
        )
        self.assertNotEqual(resource["hypotheses"][0]["name"],identity["hypotheses"][0]["name"])
        self.assertTrue(resource["reverse_validation"])
        self.assertTrue(identity["reverse_validation"])
        self.assertNotIn("事实判决",resource["guardrail"])
        self.assertIn("不把推测当事实",identity["guardrail"])


if __name__=="__main__":
    unittest.main()
