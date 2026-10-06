from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
TARGET = HERE / "bse_termination_primary_semantics.py"


def load_target():
    spec = importlib.util.spec_from_file_location("bse_termination_primary_semantics", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load target")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TerminationSemanticRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_target()

    def terminal_dates(self, text: str) -> list[str]:
        return sorted({
            hit["date"]
            for hit in self.mod.extract_semantic_hits(text)
            if hit["role"] == "terminal"
        })

    def test_disclosure_history_dates_are_not_terminal_effective_dates(self):
        text = (
            "四、前期终止上市风险提示公告的披露情况。"
            "公司已于2026年1月29日披露了《关于公司股票可能被终止上市暨立案调查进展的风险提示公告》。"
            "公司已于2026年2月11日披露了《关于公司股票可能被终止上市暨立案调查进展的第二次风险提示公告》。"
            "交易所尚未作出终止上市决定，实际终止上市日期尚未确定。"
        )
        self.assertEqual(self.terminal_dates(text), [])

    def test_direct_stock_terminal_date_remains_supported(self):
        text = "根据交易所决定，公司股票自2026年7月30日起终止上市并摘牌。"
        self.assertEqual(self.terminal_dates(text), ["2026-07-30"])

    def test_received_decision_date_is_not_terminal_date(self):
        text = (
            "公司于2026年6月1日收到北京证券交易所作出的终止上市决定。"
            "公司股票自2026年7月30日起终止上市。"
        )
        self.assertEqual(self.terminal_dates(text), ["2026-07-30"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
