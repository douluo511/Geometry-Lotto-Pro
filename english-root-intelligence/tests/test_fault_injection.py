import pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from service import create_service
class BadNet:
 def get_json(self,url): raise TimeoutError("injected timeout")
 def get_bytes(self,url): raise TimeoutError("injected timeout")
class T(unittest.TestCase):
 def test_network_failure_not_success(self):
  with tempfile.TemporaryDirectory() as td:
   s=create_service(pathlib.Path(td),BadNet())
   with self.assertRaises(Exception): s.one_click_update()
if __name__=="__main__": unittest.main()
