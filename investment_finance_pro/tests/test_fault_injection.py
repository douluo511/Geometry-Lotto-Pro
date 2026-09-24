import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import InvestmentEngine
from service import InvestmentService

class MemoryStorage:
    def __init__(self):
        self.data = None
    def read(self):
        return self.data
    def write(self, data):
        self.data = data
        return data
    def repair(self):
        return {"status": "PASS", "overall": "PASS", "checks": []}
    def path(self):
        return pathlib.Path("memory.json")

class Ledger:
    def record(self, *args, **kwargs):
        return None

class BadNet:
    def fetch_market_history(self, symbol):
        raise TimeoutError("injected market timeout")
    def fetch_fred_series(self, series_id):
        raise TimeoutError("injected macro timeout")

class FaultInjectionTests(unittest.TestCase):
    def test_all_network_failures_are_not_pass(self):
        service = InvestmentService(
            net=BadNet(),
            storage=MemoryStorage(),
            engine=InvestmentEngine(),
            evidence=Ledger(),
        )
        result = service.update_all()
        self.assertEqual(result["update_state"], "FAILED")
        self.assertTrue(all(not p["ok"] for p in result["providers"]))

if __name__ == "__main__":
    unittest.main()
