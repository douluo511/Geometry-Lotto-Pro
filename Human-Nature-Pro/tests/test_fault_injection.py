import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service import create_service

class BadNet:
    def get(self, url):
        raise TimeoutError("injected timeout")

class FaultInjectionTests(unittest.TestCase):
    def test_network_failure_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            service = create_service(pathlib.Path(td), ROOT / "knowledge_base.json", BadNet())
            with self.assertRaises(Exception):
                service.update_all()

    def test_corrupt_storage_repair(self):
        with tempfile.TemporaryDirectory() as td:
            service = create_service(pathlib.Path(td), ROOT / "knowledge_base.json")
            service.storage.path.write_text("{bad", encoding="utf-8")
            result = service.repair()
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["action"], "restored")

if __name__ == "__main__":
    unittest.main()
