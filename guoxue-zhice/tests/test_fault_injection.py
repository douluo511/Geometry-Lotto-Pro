import hashlib, tempfile, unittest
from pathlib import Path
from net_client import NetworkError
from service import GuoxueService
from storage import Store
class FakeNet:
    def __init__(self,manifest=None,raw=None,fail=False): self.manifest=manifest; self.raw=raw; self.fail=fail
    def get_json(self,url):
        if self.fail: raise NetworkError("injected manifest outage")
        return self.manifest,{"source":url,"requested_url":url,"http_status":200,"content_type":"application/json","payload_sha256":"1"*64,"bytes":1,"fetched_at":"test","attempt":1}
    def get_bytes(self,url,allowed_content_types=None):
        if self.fail: raise NetworkError("injected payload outage")
        return self.raw,{"source":url,"requested_url":url,"http_status":200,"content_type":"application/json","payload_sha256":hashlib.sha256(self.raw).hexdigest(),"bytes":len(self.raw),"fetched_at":"test","attempt":1}
class FaultInjectionTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.tmp.name)); self.original=self.store.knowledge_path.read_bytes()
    def tearDown(self): self.tmp.cleanup()
    def test_hash_mismatch_preserves_database(self):
        m={"schema":1,"version":"fault","data_url":"https://example.test/knowledge.json","sha256":"0"*64}; s=GuoxueService(store=self.store,net_client=FakeNet(m,self.original))
        with self.assertRaises(ValueError): s.one_click_update()
        self.assertEqual(self.store.knowledge_path.read_bytes(),self.original)
    def test_invalid_payload_preserves_database(self):
        bad=b"{}"; m={"schema":1,"version":"fault","data_url":"https://example.test/knowledge.json","sha256":hashlib.sha256(bad).hexdigest()}; s=GuoxueService(store=self.store,net_client=FakeNet(m,bad))
        with self.assertRaises(Exception): s.one_click_update()
        self.assertEqual(self.store.knowledge_path.read_bytes(),self.original)
    def test_network_outage_preserves_database(self):
        s=GuoxueService(store=self.store,net_client=FakeNet(fail=True))
        with self.assertRaises(RuntimeError): s.one_click_update()
        self.assertEqual(self.store.knowledge_path.read_bytes(),self.original)
    def test_corrupt_state_is_repaired(self):
        self.store.state_path.write_text("{broken",encoding="utf-8"); r=GuoxueService(store=self.store,net_client=FakeNet(fail=True)).one_click_repair(); self.assertEqual(r["status"],"PASS"); self.store.load_state()
if __name__=="__main__": unittest.main()
