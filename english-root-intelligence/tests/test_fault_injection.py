import base64
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import MANIFEST_URLS
from domain import SourceReceipt
from service import create_service
from storage import RootStorage

def receipt(url, source_id, raw):
    return SourceReceipt(
        source_id=source_id,
        url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        fetched_at=datetime.now(timezone.utc).isoformat(),
        byte_count=len(raw),
        attempts=1,
        attempt_ledger=({"attempt":1,"outcome":"HTTP_RESPONSE","status_code":200,"error_type":None,"retry_delay":0.0,"url":url},),
        raw_b64=base64.b64encode(raw).decode("ascii"),
    )

class BadNet:
    def get_json(self, url, **kwargs):
        raise TimeoutError("injected timeout")
    def get_bytes(self, url, **kwargs):
        raise TimeoutError("injected timeout")

class QuorumNet:
    def __init__(self, raw, second_raw=None):
        self.raw = raw
        self.second_raw = second_raw if second_raw is not None else raw
        self.data_calls = 0
        self.manifest = {
            "schema": 1,
            "version": "test",
            "data_url": "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/english-root-intelligence/data/roots.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    def get_json(self, url, *, source_id=None):
        raw = json.dumps(self.manifest, sort_keys=True).encode()
        return dict(self.manifest), receipt(url, source_id or url, raw)
    def get_bytes(self, url, *, source_id=None):
        self.data_calls += 1
        raw = self.raw if self.data_calls == 1 else self.second_raw
        return raw, receipt(url, source_id or url, raw)

class T(unittest.TestCase):
    def test_network_failure_not_success_and_history_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            s = create_service(root, BadNet())
            before = s.storage.store.roots_path.read_bytes()
            progress_before = s.storage.store.progress_path.read_bytes()
            with self.assertRaises(Exception):
                s.one_click_update()
            self.assertEqual(before, s.storage.store.roots_path.read_bytes())
            self.assertEqual(progress_before, s.storage.store.progress_path.read_bytes())

    def test_distribution_disagreement_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            seed = sraw = (ROOT/"data"/"roots.json").read_bytes()
            s = create_service(root, QuorumNet(seed, second_raw=seed + b"\n"))
            before = s.storage.store.roots_path.read_bytes()
            with self.assertRaises(Exception):
                s.one_click_update()
            self.assertEqual(before, s.storage.store.roots_path.read_bytes())

    def test_evidence_stage_failure_rolls_back_all_production_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            raw = (ROOT/"data"/"roots.json").read_bytes()
            s = create_service(root, QuorumNet(raw))
            roots_before = s.storage.store.roots_path.read_bytes()
            progress_before = s.storage.store.progress_path.read_bytes()
            evidence_before = s.evidence.path.read_bytes() if s.evidence.path.exists() else None
            original = s.storage._stage
            def fail_evidence(path, data):
                if pathlib.Path(path).name == "evidence.jsonl":
                    raise OSError("injected evidence staging failure")
                return original(path, data)
            s.storage._stage = fail_evidence
            with self.assertRaises(OSError):
                s.one_click_update()
            self.assertEqual(roots_before, s.storage.store.roots_path.read_bytes())
            self.assertEqual(progress_before, s.storage.store.progress_path.read_bytes())
            current = s.evidence.path.read_bytes() if s.evidence.path.exists() else None
            # Failure logging may append a FAIL row, but canonical roots/progress must not change.
            self.assertTrue(current is None or b'"status": "FAIL"' in current)

if __name__=="__main__":
    unittest.main()
