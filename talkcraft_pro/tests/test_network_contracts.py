import pathlib, sys, unittest, hashlib, base64
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from talkcraft.net.client import NetClient

class Resp:
    def __init__(self,status=200,url="https://example.test/x",ct="text/html",body=b"<html>ok</html>"):
        self.status_code=status; self.url=url; self.headers={"content-type":ct}; self._body=body
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def iter_content(self,chunk_size=65536): yield self._body
class Session:
    def __init__(self,items): self.items=list(items); self.calls=[]
    def get(self,url,**kw):
        self.calls.append((url,kw)); x=self.items.pop(0)
        if isinstance(x,BaseException): raise x
        return x

class NetworkContractTests(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(ValueError): NetClient().get("http://example.test")
    def test_429_retry_then_success_and_timeout_tuple(self):
        s=Session([Resp(429),Resp(200,body=b"abc")]); sleeps=[]
        r=NetClient(connect_timeout=1,read_timeout=2,max_attempts=2,session=s,sleeper=sleeps.append).get("https://example.test")
        self.assertTrue(r.ok); self.assertEqual(len(s.calls),2)
        self.assertEqual(s.calls[0][1]["timeout"],(1.0,2.0))
        self.assertEqual(r.attempts[0]["outcome"],"RETRY_HTTP")
        self.assertEqual(r.sha256,hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(base64.b64decode(r.body_b64),b"abc")
    def test_https_redirect_downgrade_fails_closed(self):
        r=NetClient(max_attempts=1,session=Session([Resp(200,url="http://example.test/x")]),sleeper=lambda _:None).get("https://example.test")
        self.assertFalse(r.ok); self.assertEqual(r.attempts[0]["outcome"],"FINAL_INSECURE_REDIRECT")
    def test_wrong_content_type_fails_closed(self):
        r=NetClient(max_attempts=1,session=Session([Resp(200,ct="application/json")]),sleeper=lambda _:None).get("https://example.test")
        self.assertFalse(r.ok); self.assertEqual(r.attempts[0]["outcome"],"FINAL_CONTENT_TYPE")
if __name__=="__main__": unittest.main()
