import base64
import hashlib
import pathlib
import random
import sys
import tempfile
import unittest

import requests

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from evidence import EvidenceLedger
from net_client import NetClient


class FakeResponse:
    def __init__(self,status=200,content=b"{}",content_type="application/json",url="https://example.test/data",headers=None):
        self.status_code=status
        self.content=content
        self.url=url
        self.headers={"Content-Type":content_type}
        if headers:
            self.headers.update(headers)
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(f"status={self.status_code}",response=self)


class FakeSession:
    def __init__(self,outcomes):
        self.outcomes=list(outcomes)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append({"url":url,**kwargs})
        value=self.outcomes.pop(0)
        if isinstance(value,BaseException):
            raise value
        if not getattr(value,"url",None):
            value.url=url
        return value


class NetworkContractTests(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(ValueError):
            NetClient(max_attempts=1).get("http://example.test/data")

    def test_429_retry_uses_separate_timeout_and_attempt_ledger(self):
        sleeps=[]
        session=FakeSession([
            FakeResponse(429,headers={"Retry-After":"1"}),
            FakeResponse(200,b'{"schema_version":1}')
        ])
        client=NetClient(
            connect_timeout=1,read_timeout=2,max_attempts=2,backoff_base=0.1,
            session=session,sleeper=sleeps.append,rng=random.Random(7)
        )
        raw,receipt=client.get("https://example.test/data")
        self.assertEqual(session.calls[0]["timeout"],(1.0,2.0))
        self.assertEqual(len(receipt["attempts"]),2)
        self.assertEqual(receipt["attempts"][0]["outcome"],"RETRY_HTTP")
        self.assertEqual(receipt["attempts"][-1]["outcome"],"HTTP_RESPONSE")
        self.assertEqual(sleeps,[1.0])
        self.assertTrue(raw)

    def test_https_redirect_downgrade_fails_closed(self):
        client=NetClient(
            max_attempts=1,
            session=FakeSession([FakeResponse(200,b"{}",url="http://example.test/data")]),
            sleeper=lambda _:None,rng=random.Random(1),
        )
        with self.assertRaises(ValueError) as ctx:
            client.get("https://example.test/data")
        attempts=getattr(ctx.exception,"glp_attempts",())
        self.assertTrue(attempts)
        self.assertEqual(attempts[-1]["outcome"],"FINAL_INSECURE_REDIRECT")

    def test_raw_payload_receipt_materializes_by_hash(self):
        payload=b'{"schema_version":1,"rules":[1],"hypothesis_templates":[1],"sources":[1]}'
        client=NetClient(
            max_attempts=1,
            session=FakeSession([FakeResponse(200,payload)]),
            sleeper=lambda _:None,rng=random.Random(1),
        )
        raw,receipt=client.get("https://example.test/data")
        self.assertEqual(receipt["payload_hash"],hashlib.sha256(raw).hexdigest())
        self.assertEqual(base64.b64decode(receipt["body_b64"]),raw)
        with tempfile.TemporaryDirectory() as td:
            ledger=EvidenceLedger(pathlib.Path(td)/"evidence.jsonl")
            row=ledger.record("NETWORK","PASS",source=receipt)
            stored=row["details"]["source"]
            self.assertEqual(stored["raw_sha256"],receipt["payload_hash"])
            self.assertTrue(pathlib.Path(stored["raw_path"]).exists())


if __name__=="__main__":
    unittest.main()
