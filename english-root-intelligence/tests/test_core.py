from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import LearningEngine, MaintenanceEngine, Store, self_test


class CoreTests(unittest.TestCase):
    def test_self_test(self):
        self.assertEqual(self_test()["status"], "PASS")

    def test_known_word(self):
        with tempfile.TemporaryDirectory() as td:
            e = LearningEngine(Store(Path(td)))
            r = e.analyze("predict")
            self.assertEqual(r["root"]["morpheme"], "dict")
            self.assertIn("dict", r["segmentation"])
            self.assertGreater(r["confidence"], 0.9)

    def test_unknown_word_does_not_fake_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            e = LearningEngine(Store(Path(td)))
            r = e.analyze("xylophone")
            self.assertLess(r["confidence"], 0.5)
            self.assertEqual(r["meaning"], "需要结合词典语境确认")

    def test_repair(self):
        with tempfile.TemporaryDirectory() as td:
            s = Store(Path(td))
            s.roots_path.write_text("{broken", encoding="utf-8")
            r = MaintenanceEngine(s).one_click_repair()
            self.assertEqual(r["status"], "PASS")
            self.assertGreaterEqual(len(s.load_roots()["roots"]), 10)


if __name__ == "__main__":
    unittest.main()
