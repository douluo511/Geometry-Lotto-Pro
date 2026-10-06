import json, pathlib, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from release_gate import evaluate, HARD_GATES

class ReleaseGateTests(unittest.TestCase):
    def _exe(self,p,b=b"x"): p.write_bytes(b)
    def test_repository_independence_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            d=pathlib.Path(td); c=d/"c.exe"; f=d/"f.exe"; self._exe(c); self._exe(f)
            gates={k:"PASS" for k in HARD_GATES}; gates["repository_independence"]="FAIL"
            gi=d/"g.json"; gi.write_text(json.dumps({"gates":gates}),encoding="utf-8")
            r=evaluate(gi,c,f); self.assertEqual(r["final_gate"],"FAIL"); self.assertEqual(r["failures"],{"repository_independence":"FAIL"})
    def test_unknown_or_hash_mismatch_never_passes(self):
        with tempfile.TemporaryDirectory() as td:
            d=pathlib.Path(td); c=d/"c.exe"; f=d/"f.exe"; self._exe(c,b"a"); self._exe(f,b"b")
            gates={k:"PASS" for k in HARD_GATES}; gates.pop("real_network")
            gi=d/"g.json"; gi.write_text(json.dumps({"gates":gates}),encoding="utf-8")
            r=evaluate(gi,c,f); self.assertEqual(r["final_gate"],"FAIL"); self.assertIn("real_network",r["failures"]); self.assertIn("same_hash",r["failures"])
if __name__=="__main__": unittest.main()
