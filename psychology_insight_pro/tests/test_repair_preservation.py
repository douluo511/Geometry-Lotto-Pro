import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from storage import KnowledgeStorage
from service import create_service

class RepairPreservationTests(unittest.TestCase):
    def test_corrupt_knowledge_and_provenance_exact_backup_post_self_test(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'knowledge.json'
            local.write_bytes(b'corrupt exact user bytes')
            provenance = local.with_suffix('.source.json')
            provenance.write_bytes(b'previous source receipt')
            result = KnowledgeStorage(local, PROJECT / 'knowledge.json').repair_knowledge()
            for path, raw in ((local, b'corrupt exact user bytes'), (provenance, b'previous source receipt')):
                backup = Path(result['backups'][path.name])
                self.assertEqual(backup.read_bytes(), raw)
                self.assertIn(hashlib.sha256(raw).hexdigest(), backup.name)
            self.assertFalse(provenance.exists())
            svc = create_service(local, PROJECT / 'knowledge.json', ['https://a.example/knowledge.json', 'https://b.example/knowledge.json'])
            self.assertEqual(svc.repair()['post_repair_self_test']['status'], 'PASS')
    def test_healthy_knowledge_and_receipts_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'knowledge.json'
            raw = (PROJECT / 'knowledge.json').read_bytes()
            local.write_bytes(raw)
            evidence = local.with_suffix('.source.json')
            evidence.write_bytes(b'valid receipt unchanged')
            result = KnowledgeStorage(local, PROJECT / 'knowledge.json').repair_knowledge()
            self.assertEqual(result['repair_action'], 'NO_REPAIR_NEEDED')
            self.assertEqual(local.read_bytes(), raw)
            self.assertEqual(evidence.read_bytes(), b'valid receipt unchanged')
    def test_invalid_bundle_cannot_overwrite_or_erase_existing_state(self):
        with tempfile.TemporaryDirectory() as td:
            local, bundle = Path(td) / 'knowledge.json', Path(td) / 'bundle.json'
            local.write_bytes(b'original corrupt bytes')
            bundle.write_bytes(b'invalid bundle')
            evidence = local.with_suffix('.source.json')
            evidence.write_bytes(b'original source ledger')
            with self.assertRaises(Exception):
                KnowledgeStorage(local, bundle).repair_knowledge()
            self.assertEqual(local.read_bytes(), b'original corrupt bytes')
            self.assertEqual(evidence.read_bytes(), b'original source ledger')

if __name__ == '__main__':
    unittest.main()
