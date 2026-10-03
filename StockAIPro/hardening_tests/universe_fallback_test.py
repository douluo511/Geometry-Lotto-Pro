from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        os.environ["STOCK_AI_DATA_ROOT"] = td
        sys.path.insert(0, str(VERSION))
        from stock_ai import data_source
        from stock_ai.config import ensure_dirs, load_config

        ensure_dirs()
        cfg = load_config()
        cfg["universe"]["exclude_st"] = True
        cfg["universe"]["include_bj"] = False

        class FakeAk:
            def stock_info_a_code_name(self):
                raise RuntimeError("simulated SSE aggregate 403")
            def stock_zh_a_spot_em(self):
                raise RuntimeError("simulated Eastmoney disconnect")
            def stock_zh_a_spot(self):
                return pd.DataFrame({
                    "代码": ["000001", "600000", "000002", "430001"],
                    "名称": ["平安银行", "浦发银行", "*ST测试", "北交测试"],
                    "最新价": [10.0, 9.0, 3.0, 5.0],
                    "成交额": [1e9, 8e8, 5e7, 4e7],
                })

        original_ak = data_source._ak
        original_delisted = data_source.fetch_delisted_universe
        try:
            data_source._ak = lambda: FakeAk()
            data_source.fetch_delisted_universe = lambda cfg, logger=None: pd.DataFrame(
                columns=["code","name","list_date","delist_date","status"]
            )
            result = data_source.fetch_full_universe(cfg)
        finally:
            data_source._ak = original_ak
            data_source.fetch_delisted_universe = original_delisted

        codes = set(result["code"].astype(str))
        assert {"000001", "600000", "000002"}.issubset(codes), codes
        assert "430001" not in codes, codes
        assert set(result["status"]) == {"current"}
        assert set(result["universe_provider"]) == {"sina_spot"}
        assert (Path(td) / "cache" / "universe_master.csv").is_file()
        print("STOCK AI FULL UNIVERSE LIVE FALLBACK TEST PASS", len(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
