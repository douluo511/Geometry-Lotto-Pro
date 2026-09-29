import base64
import hashlib
import json
import pathlib
import random
import sys
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
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}", response=self)


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


class NetClientContractTests(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(ValueError):
            NetClient(max_attempts=1)._get_bytes("http://example.test/data","*/*")

    def test_429_retry_uses_separate_timeout_and_attempt_ledger(self):
        sleeps=[]
        session=FakeSession([
            FakeResponse(429,headers={"Retry-After":"1"}),
            FakeResponse(200,b'{"ok":true}')
        ])
        client=NetClient(
            connect_timeout=1,read_timeout=2,max_attempts=2,backoff_base=0.1,
            session=session,sleeper=sleeps.append,rng=random.Random(7)
        )
        raw,receipt=client._get_bytes("https://example.test/data","application/json")
        self.assertEqual(raw,b'{"ok":true}')
        self.assertEqual(session.calls[0]["timeout"],(1.0,2.0))
        self.assertEqual(len(receipt["attempts"]),2)
        self.assertEqual(receipt["attempts"][0]["outcome"],"RETRY_HTTP")
        self.assertEqual(receipt["attempts"][-1]["outcome"],"HTTP_RESPONSE")
        self.assertEqual(sleeps,[1.0])

    def test_https_redirect_downgrade_fails_closed(self):
        session=FakeSession([FakeResponse(200,b"{}",url="http://example.test/data")])
        client=NetClient(max_attempts=1,session=session,sleeper=lambda _:None,rng=random.Random(1))
        with self.assertRaises(ValueError) as ctx:
            client._get_bytes("https://example.test/data","application/json")
        attempts=getattr(ctx.exception,"glp_attempts",())
        self.assertTrue(attempts)
        self.assertEqual(attempts[-1]["outcome"],"FINAL_INSECURE_REDIRECT")

    def test_raw_payload_receipt_and_materialization(self):
        payload=b'{"value":42}'
        session=FakeSession([FakeResponse(200,payload)])
        client=NetClient(max_attempts=1,session=session,sleeper=lambda _:None,rng=random.Random(1))
        raw,receipt=client._get_bytes("https://example.test/data","application/json")
        self.assertEqual(hashlib.sha256(raw).hexdigest(),receipt["payload_hash"])
        self.assertEqual(base64.b64decode(receipt["body_b64"]),payload)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ledger=EvidenceLedger(pathlib.Path(td)/"evidence.jsonl")
            row=ledger.record("NETWORK","PASS",receipts=[receipt])
            stored=row["details"]["receipts"][0]
            self.assertEqual(stored["raw_sha256"],receipt["payload_hash"])
            self.assertTrue(pathlib.Path(stored["raw_path"]).exists())


    def test_nasdaq_history_parser_accepts_keyless_public_shape(self):
        payload={
            "data":{
                "tradesTable":{
                    "rows":[
                        {
                            "date":f"09/{day:02d}/2026",
                            "close":"$100.00",
                            "open":"$99.50",
                            "high":"$101.00",
                            "low":"$99.00",
                            "volume":"1,000,000",
                        }
                        for day in range(1,31)
                    ]
                }
            }
        }
        rows=NetClient._parse_nasdaq_history(payload,"TEST")
        self.assertEqual(len(rows),30)
        self.assertEqual(rows[-1]["date"],"2026-09-30")
        self.assertEqual(rows[-1]["close"],100.0)

    def test_dff_fred_timeout_falls_back_to_official_nyfed(self):
        nyfed={
            "refRates":[
                {
                    "effectiveDate":"2026-09-28",
                    "type":"EFFR",
                    "percentRate":3.88,
                }
            ]
        }
        session=FakeSession([
            requests.ReadTimeout("fred timeout"),
            FakeResponse(
                200,
                json.dumps(nyfed).encode("utf-8"),
                content_type="application/json",
                url="https://markets.newyorkfed.org/api/rates/unsecured/effr/last/10.json",
            ),
        ])
        client=NetClient(
            max_attempts=1,
            session=session,
            sleeper=lambda _:None,
            rng=random.Random(1),
        )
        item,receipt=client.fetch_fred_series("DFF")
        self.assertEqual(item["series"],"DFF")
        self.assertEqual(item["value"],3.88)
        self.assertEqual(receipt["source_identity"],"NY_FED_EFFR")
        self.assertEqual(receipt["fallback_for"],"FRED:DFF")
        self.assertIn("ReadTimeout",receipt["primary_error"])


if __name__=="__main__":
    unittest.main()
