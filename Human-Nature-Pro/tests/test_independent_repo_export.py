from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from export_independent_repo import export_repo,verify

def write(root:Path,rel:str,data:bytes=b"x"):
    p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)

class ExportTests(unittest.TestCase):
    def source(self,root:Path):
        write(root,"Human-Nature-Pro/app.py",b"print('ok')\n")
        write(root,"Human-Nature-Pro/tests/test_ok.py",b"def test_ok(): assert True\n")
        write(root,"Human-Nature-Pro/dist/skip.exe",b"skip")
        write(root,"Human-Nature-Pro/evidence/skip.json",b"{}")
        write(root,".github/workflows/human-nature-pro-windows.yml",b"name: project\n")
        write(root,"DLT/secret.py",b"no\n")
    def test_export_and_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; dst=Path(td)/"dst"; root.mkdir(); self.source(root)
            p=export_repo(root,dst,"a"*40)
            self.assertEqual(p["status"],"PASS")
            self.assertFalse((dst/"DLT").exists())
            self.assertFalse((dst/"Human-Nature-Pro/dist").exists())
    def test_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; dst=Path(td)/"dst"; root.mkdir(); self.source(root)
            export_repo(root,dst,"b"*40)
            (dst/"Human-Nature-Pro/app.py").write_bytes(b"tampered")
            self.assertEqual(verify(dst)["status"],"FAIL")
    def test_unmanifested_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; dst=Path(td)/"dst"; root.mkdir(); self.source(root)
            export_repo(root,dst,"c"*40); write(dst,"unexpected.txt")
            self.assertEqual(verify(dst)["status"],"FAIL")
if __name__=="__main__":
    unittest.main()
