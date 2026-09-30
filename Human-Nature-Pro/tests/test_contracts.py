import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts import SERVICE_METHODS
from service import HumanNatureService, create_service

class ContractTests(unittest.TestCase):
    def test_service_contract(self):
        for name in SERVICE_METHODS:
            self.assertTrue(callable(getattr(HumanNatureService, name, None)))

    def test_result_schema(self):
        with tempfile.TemporaryDirectory() as td:
            service = create_service(pathlib.Path(td), ROOT / "knowledge_base.json")
            result = service.analyze("客户说预算不够", "保护利益")
            self.assertIn("hypotheses", result)
            self.assertIn("reverse_validation", result)
            self.assertIn("strategies", result)

if __name__ == "__main__":
    unittest.main()
