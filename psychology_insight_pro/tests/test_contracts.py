import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from contracts import validate_knowledge
from net_client import NetClient
from service import PsychologyService
from storage import KnowledgeStorage


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bundled = PROJECT / "knowledge.json"
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name) / "knowledge.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_knowledge_schema_contract(self):
        data = json.loads(self.bundled.read_text(encoding="utf-8"))
        validate_knowledge(data)

    def test_service_public_contract(self):
        service = PsychologyService(
            KnowledgeStorage(self.local, self.bundled),
            NetClient(timeout=0.2, retries=0),
            "https://example.com/knowledge.json",
        )
        for name in ("analyze_text", "update_knowledge", "repair", "health"):
            self.assertTrue(callable(getattr(service, name)))
        result = service.analyze_text("不知道，最近比较忙，改天再说。", "以前通常会主动约具体时间。")
        self.assertTrue(result.hypotheses)
        self.assertIn(result.overall_confidence, {"LOW", "MEDIUM", "MEDIUM-HIGH"})
        self.assertTrue(result.reverse_validation)

    def test_risk_boundary_contract(self):
        service = PsychologyService(
            KnowledgeStorage(self.local, self.bundled),
            NetClient(timeout=0.2, retries=0),
            "https://example.com/knowledge.json",
        )
        result = service.analyze_text("嗯。")
        self.assertIn("不是读心", result.disclaimer)
        self.assertIn("不是", result.disclaimer)


if __name__ == "__main__":
    unittest.main()
