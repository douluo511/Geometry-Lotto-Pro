import base64
import hashlib
import pathlib
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from service import create_service


class FixtureNet:
    def __init__(self,payload:bytes):
        self.payload=payload
    def get(self,url):
        digest=hashlib.sha256(self.payload).hexdigest()
        return self.payload,{
            "requested_url":url,
            "final_url":url,
            "http_status":200,
            "content_type":"application/json",
            "payload_hash":digest,
            "bytes":len(self.payload),
            "fetched_at":"2026-09-29T00:00:00+00:00",
            "attempts":[{"attempt":1,"outcome":"HTTP_RESPONSE","status_code":200,"requested_url":url,"final_url":url}],
            "body_b64":base64.b64encode(self.payload).decode("ascii"),
        }


class IntegrationTests(unittest.TestCase):
    def test_service_network_storage_engine_evidence_round_trip(self):
        payload=(ROOT/"knowledge_base.json").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            service=create_service(root,ROOT/"knowledge_base.json",FixtureNet(payload))
            result=service.update_all()
            self.assertEqual(result["status"],"PASS")
            self.assertTrue(result["source"]["payload_hash"])
            analysis=service.analyze("客户说预算不足，需要再考虑。","保护利益并保持合作")
            self.assertGreaterEqual(len(analysis["hypotheses"]),4)
            self.assertTrue(analysis["reverse_validation"])
            raw=list((root/"raw").glob("*.bin"))
            self.assertTrue(raw)
            self.assertTrue((root/"evidence.jsonl").exists())


if __name__=="__main__":
    unittest.main()
