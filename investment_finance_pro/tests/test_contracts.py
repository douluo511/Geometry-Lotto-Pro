import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts import SERVICE_METHODS
from service import InvestmentService

class ContractTests(unittest.TestCase):
    def test_service_contract(self):
        for name in SERVICE_METHODS:
            self.assertTrue(callable(getattr(InvestmentService, name, None)))

if __name__ == "__main__":
    unittest.main()
