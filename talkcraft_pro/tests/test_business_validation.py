import json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from talkcraft.engine.reversal import compare_variants
from talkcraft.engine.scoring import analyze_text

class BusinessValidationTests(unittest.TestCase):
    def test_business_core_content_and_boundaries(self):
        cases=json.loads((ROOT/"data/cases.json").read_text(encoding="utf-8"))
        knowledge=json.loads((ROOT/"data/knowledge.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases),60)
        self.assertTrue(all(x["boundary"] for x in cases))
        self.assertGreaterEqual(len(knowledge["guardrails"]),5)
        r=analyze_text("我发现昨天开会30分钟，本来以为五分钟结束，结果会议像连续剧一样自动续订。")
        self.assertTrue(all(0<=v<=100 for v in r.score.as_dict().values()))
    def test_counterexample_more_words_or_technique_does_not_force_better_verdict(self):
        good="昨天等外卖30分钟，本来以为马上到，结果骑手还在找路。我发现马上是一种人生理念。"
        bad="就是就是其实那个这个嗯啊，我觉得人生宇宙永远都像什么一样，结果反而偏偏就是。"
        c=compare_variants(good,bad)
        self.assertEqual(c["verdict"],"REVIEW_OR_ROLLBACK")
    def test_reversal_changes_decision_direction(self):
        weak="我迟到了。"
        strong="昨天我迟到20分钟，本来以为只晚五分钟，结果导航告诉我：你不是迟到，你是在参加下一场。"
        forward=compare_variants(weak,strong); reverse=compare_variants(strong,weak)
        self.assertEqual(forward["verdict"],"KEEP_VARIANT")
        self.assertEqual(reverse["verdict"],"REVIEW_OR_ROLLBACK")
if __name__=="__main__": unittest.main()
