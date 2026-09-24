import tempfile, unittest
from pathlib import Path
from contracts import assert_analysis_contract, assert_service_contract
from domain import ContractError, validate_manifest
from release_gate import REQUIRED_GATES, evaluate
from service import GuoxueService
class ContractTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.service=GuoxueService(Path(self.tmp.name))
    def tearDown(self): self.tmp.cleanup()
    def test_service_contract(self): assert_service_contract(self.service)
    def test_analysis_contract(self): assert_analysis_contract(self.service.analyze_goal("我要谈合作价格，判断底线和筹码并控制风险"))
    def test_manifest_contract(self):
        with self.assertRaises(ContractError): validate_manifest({"schema":1,"version":"x","data_url":"http://example.com","sha256":"0"*64})
        with self.assertRaises(ContractError): validate_manifest({"schema":1,"version":"x","data_url":"https://example.com","sha256":"bad"})
    def test_release_gate_rejects_non_pass(self):
        gates={name:"PASS" for name in REQUIRED_GATES}; gates["fault_injection"]="WARNING"; r=evaluate({"gates":gates}); self.assertEqual(r["final_gate"],"FAIL")
    def test_release_gate_accepts_complete_pass(self):
        r=evaluate({"gates":{name:"PASS" for name in REQUIRED_GATES}}); self.assertEqual(r["final_gate"],"PASS"); self.assertEqual(r["hard_fail_count"],0)
    def test_ui_routes_only_through_service(self):
        src=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8"); self.assertIn("from service import GuoxueService",src); self.assertNotIn("from engine import",src); self.assertNotIn("from storage import",src); self.assertNotIn("from net_client import",src)
if __name__=="__main__": unittest.main()
