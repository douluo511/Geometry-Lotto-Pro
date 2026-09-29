import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from contracts import validate_knowledge
from domain import SourceRecord
from service import PsychologyService
from storage import KnowledgeStorage


class QuorumClient:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, validator=validate_knowledge, *, source_id=""):
        validator(self.payload)
        raw = json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self.payload, SourceRecord(
            url=url,
            fetched_at="2026-09-29T00:00:00+00:00",
            http_status=200,
            sha256="b" * 64,
            bytes_count=len(raw),
            content_type="application/json",
            source_id=source_id,
            attempts=({"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": 200},),
            raw_b64=base64.b64encode(raw).decode("ascii"),
        )


class IntegrationTests(unittest.TestCase):
    def test_quorum_update_storage_analysis_repair_chain(self):
        base = json.loads((PROJECT / "knowledge.json").read_text(encoding="utf-8"))
        remote = json.loads(json.dumps(base))
        remote["version"] = "99.0.0"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            local = root / "knowledge.json"
            bundle.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")

            service = PsychologyService(
                KnowledgeStorage(local, bundle),
                QuorumClient(remote),
                ["https://a.example/knowledge.json", "https://b.example/knowledge.json"],
            )
            updated = service.update_knowledge()
            self.assertEqual(updated.status, "UPDATED")
            self.assertEqual(updated.network_gate, "PASS")
            self.assertEqual(len(updated.sources), 2)
            self.assertEqual(service.knowledge["version"], "99.0.0")
            self.assertTrue(service.storage.evidence_path.exists())

            result = service.analyze_text(
                "最近很忙，改天再说，不过有空我会联系你。",
                "以前通常会主动约具体时间。",
            )
            self.assertTrue(result.hypotheses)
            self.assertTrue(result.reverse_validation)
            self.assertIn("不是读心", result.disclaimer)

            repaired = service.repair()
            self.assertEqual(repaired["knowledge"], "PASS")
            self.assertEqual(repaired["core"], "PASS")


if __name__ == "__main__":
    unittest.main()
