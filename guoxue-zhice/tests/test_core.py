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
        self.assertEqual(r["user_data_preservation"], "PASS")

    def test_repair_corruption_preserves_original_bytes_and_revalidates(self):
        self.store.state_path.write_bytes(b"{broken-state")
        self.store.config_path.write_text('{"schema":1,"app_version":"0.0.0","network_policy":"http"}', encoding="utf-8")
        self.store.cache_path.write_bytes(b"not-json")
        self.store.index_path.write_text('{"schema":1,"knowledge_sha256":"bad","titles":[]}', encoding="utf-8")

        r = MaintenanceEngine(self.store).one_click_repair()

        self.assertEqual(r["status"], "PASS")
        self.assertTrue(r["recovery_backups"])
        backups = list(self.store.recovery_dir.iterdir())
        self.assertTrue(any(p.name.startswith("state-") and p.read_bytes() == b"{broken-state" for p in backups))
        self.assertEqual(self.store.load_config()["network_policy"], "https-only")
        self.assertEqual(self.store.load_config()["app_version"], "0.2.0")
        self.assertEqual(self.store.load_cache()["entries"], {})
        self.assertEqual(
            self.store.load_index()["knowledge_sha256"],
            self.store._index_value(self.store.load_knowledge())["knowledge_sha256"],
        )

    def test_repair_missing_required_files(self):
        self.store.knowledge_path.unlink()
        self.store.state_path.unlink()
        self.store.config_path.unlink()
        self.store.cache_path.unlink()
        self.store.index_path.unlink()

        r = MaintenanceEngine(self.store).one_click_repair()

        self.assertEqual(r["status"], "PASS")
        self.store.load_knowledge()
        self.store.load_state()
        self.store.load_config()
        self.store.load_cache()
        self.store.load_index()


if __name__ == "__main__":
    unittest.main()
