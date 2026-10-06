import json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from talkcraft.engine.scoring import analyze_text

class ContractTests(unittest.TestCase):
    def test_score_contract(self):
        r=analyze_text("昨天等外卖30分钟，本来以为马上到，结果骑手还在找路。我发现马上是一种哲学。")
        s=r.score.as_dict()
        self.assertEqual(set(s),{"observation","pov","concise","humor","story","rhythm","interaction"})
        self.assertTrue(all(0<=v<=100 for v in s.values()))
        self.assertTrue(r.next_task)
    def test_content_contract(self):
        drills=json.loads((ROOT/"data/drills.json").read_text(encoding="utf-8"))
        cases=json.loads((ROOT/"data/cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(drills),180); self.assertGreaterEqual(len(cases),60)
        self.assertTrue(all({"id","topic","task","minutes"}<=set(x) for x in drills))
        self.assertTrue(all({"id","mechanism","situation","boundary","reversal_question"}<=set(x) for x in cases))
if __name__=="__main__": unittest.main()
