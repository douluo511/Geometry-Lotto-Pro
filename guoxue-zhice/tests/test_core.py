import tempfile
import unittest
from pathlib import Path

from core import GoalEngine, MaintenanceEngine, ReviewEngine, Store, self_test


class GuoxueZhiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_self_test_passes(self):
        self.assertEqual(self_test(Path(self.tmp.name))["status"], "PASS")

    def test_negotiation_goal_has_multiple_sources(self):
        r = GoalEngine(self.store).analyze("我要谈合作价格，判断对方底线和我的筹码")
        self.assertIn("谈判与合作", r["scenarios"])
        self.assertGreaterEqual(len(r["methods"]), 3)
        self.assertEqual(len(r["five_whys"]), 5)

    def test_review_persists(self):
        e = ReviewEngine(self.store)
        e.save("目标", "行动", "结果", "教训")
        self.assertEqual(len(e.recent()), 1)

    def test_repair_gate(self):
        r = MaintenanceEngine(self.store).one_click_repair()
        self.assertEqual(r["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
