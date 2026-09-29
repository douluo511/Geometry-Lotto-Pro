from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import MaintenanceEngine, Store
from net_client import NetClient

class FakeResponse:
    def __init__(self, status=200, content=b"{}", content_type="application/json", url="https://example.invalid/data"):
        self.status_code=status
        self.content=content
        self.headers={"Content-Type":content_type}
        self.url=url

class FakeSession:
    def __init__(self, outcomes):
        self.outcomes=list(outcomes)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append({"url":url,**kwargs})
        value=self.outcomes.pop(0)
        if isinstance(value,BaseException):
            raise value
        return value

class NetworkContractTests(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(ValueError):
            NetClient().get_bytes("http://example.invalid",source_id="x")

    def test_separate_timeout_retry_and_ledger(self):
        sleeps=[]
        session=FakeSession([
            FakeResponse(429),
            FakeResponse(200,b'{"ok":true}')
        ])
        client=NetClient(connect_timeout=1,read_timeout=2,session=session,sleeper=sleeps.append,rng=random.Random(7),backoff_base=0.1)
        raw,receipt=client.get_bytes("https://example.invalid/data",source_id="x")
        self.assertEqual(raw,b'{"ok":true}')
        self.assertEqual(session.calls[0]["timeout"],(1.0,2.0))
        self.assertEqual(len(receipt.attempts),2)
        self.assertEqual(receipt.attempts[0]["outcome"],"RETRY_HTTP")
        self.assertEqual(receipt.attempts[-1]["outcome"],"HTTP_RESPONSE")
        self.assertEqual(len(sleeps),1)

    def test_insecure_redirect_fails_closed(self):
        client=NetClient(session=FakeSession([FakeResponse(200,b"{}",url="http://example.invalid/data")]),sleeper=lambda _:None)
        with self.assertRaises(requests.RequestException) as ctx:
            client.get_bytes("https://example.invalid/data",source_id="x")
        attempts=getattr(ctx.exception,"glp_attempts",())
        self.assertTrue(attempts)
        self.assertEqual(attempts[-1]["outcome"],"FINAL_INSECURE_REDIRECT")

class PersistenceFaultTests(unittest.TestCase):
    def test_evidence_stage_failure_leaves_knowledge_and_state_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td))
            before_k=store.knowledge_path.read_bytes()
            before_s=store.state_path.read_bytes()
            raw=before_k
            evidence={
                "status":"PASS",
                "knowledge_sha256":__import__("hashlib").sha256(raw).hexdigest(),
            }
            original=store._stage_bytes
            def fail(path,data):
                if Path(path)==store.evidence_path:
                    raise OSError("injected evidence stage failure")
                return original(path,data)
            store._stage_bytes=fail
            with self.assertRaises(OSError):
                store.commit_network_update(raw,evidence,"2026-09-29T00:00:00+00:00")
            self.assertEqual(before_k,store.knowledge_path.read_bytes())
            self.assertEqual(before_s,store.state_path.read_bytes())

    def test_bad_hash_cannot_mutate_production(self):
        class FakeNet:
            def get_bytes(self,url,*,source_id):
                if source_id.startswith("manifest"):
                    payload=json.dumps({
                        "schema":1,
                        "version":"x",
                        "data_url":"https://example.invalid/knowledge.json",
                        "sha256":"0"*64
                    }).encode()
                else:
                    payload=(ROOT/"data"/"knowledge.json").read_bytes()
                class R:
                    def __init__(self,raw):
                        self.raw=raw
                    def to_dict(self):
                        return {
                            "source_id":source_id,"requested_url":url,"final_url":url,
                            "http_status":200,"content_type":"application/json","byte_count":len(self.raw),
                            "sha256":__import__("hashlib").sha256(self.raw).hexdigest(),
                            "fetched_at":"2026-09-29T00:00:00+00:00","attempts":[{"attempt":1,"outcome":"HTTP_RESPONSE"}],
                            "raw_b64":"eA==",
                        }
                return payload,R(payload)
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td))
            before_k=store.knowledge_path.read_bytes()
            before_s=store.state_path.read_bytes()
            with self.assertRaises(ValueError):
                MaintenanceEngine(store,FakeNet()).one_click_update()
            self.assertEqual(before_k,store.knowledge_path.read_bytes())
            self.assertEqual(before_s,store.state_path.read_bytes())

if __name__=="__main__":
    unittest.main()
