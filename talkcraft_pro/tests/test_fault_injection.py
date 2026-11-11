import pathlib, sys, tempfile, shutil, unittest, requests
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from talkcraft.net.client import NetClient
from talkcraft.service.training_service import TrainingService

class Session:
    def get(self,*a,**k): raise requests.Timeout("boom")
class AlwaysFail:
    def get(self,url):
        from talkcraft.net.client import NetResult
        return NetResult(False,url,"",0,"","",0,1,"",[],"injected")

class FaultInjectionTests(unittest.TestCase):
    def test_retry_exhaustion_fails_closed(self):
        r=NetClient(max_attempts=3,session=Session(),sleeper=lambda _:None).get("https://example.test")
        self.assertFalse(r.ok); self.assertEqual(len(r.attempts),3); self.assertEqual(r.attempts[-1]["outcome"],"FINAL_EXCEPTION")
    def test_source_failure_never_becomes_overall_pass(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td); shutil.copytree(ROOT/"data",base/"data")
            svc=TrainingService(base); svc.net=AlwaysFail()
            r=svc.update_all_sources()
            self.assertFalse(r["ok"]); self.assertTrue(all(not x["ok"] for x in r["sources"]))
if __name__=="__main__": unittest.main()
