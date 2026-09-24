import inspect, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from service import EnglishRootService, create_service
from net_client import NetClient
class T(unittest.TestCase):
 def test_service_contract(self):
  for n in ["analyze","today_roots","stats","mark_practiced","one_click_update","one_click_repair"]: self.assertTrue(callable(getattr(EnglishRootService,n,None)))
 def test_net_bounds(self):
  n=NetClient(max_attempts=99); self.assertLessEqual(n.max_attempts,4); self.assertGreater(n.connect_timeout,0); self.assertGreater(n.read_timeout,0)
if __name__=="__main__": unittest.main()
