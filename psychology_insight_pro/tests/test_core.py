import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import analyze, self_test


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PROJECT, "knowledge.json"), "r", encoding="utf-8") as f:
            cls.knowledge = json.load(f)

    def test_core_self_test(self):
        result = self_test()
        self.assertTrue(all(v == "PASS" for v in result.values()))

    def test_competing_hypotheses_exist(self):
        r = analyze("最近很忙，改天再说，但下次有空我们一起吃饭。", self.knowledge)
        self.assertGreaterEqual(len(r.hypotheses), 3)
        self.assertIn(r.overall_confidence, {"LOW", "MEDIUM", "MEDIUM-HIGH"})

    def test_no_text_fails(self):
        with self.assertRaises(ValueError):
            analyze("", self.knowledge)

    def test_baseline_note(self):
        r = analyze("嗯，改天。", self.knowledge, "以前我一般都会当天认真回复，也会主动约具体时间一起见面。")
        self.assertTrue(r.consistency_notes)


if __name__ == "__main__":
    unittest.main()
