import json
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))

from stock_ai.historical_pit import evaluate_historical_st_pit

H = "a" * 64


def write(root: Path, obj: dict):
    p = root / "cache" / "historical_st_pit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def complete():
    return {
        "schema": "stock-ai-historical-st-pit-v1",
        "status": "PASS",
        "full_historical_st_pit": "PASS",
        "daily_state_complete": True,
        "point_in_time_only": True,
        "future_leakage_violations": 0,
        "window_start": "2018-01-01",
        "window_end": "2026-09-30",
        "canonical_sha256": H,
        "source_manifest_sha256": H,
        "markets": {
            market: {
                "st_identity": "PASS",
                "suspension_state": "PASS",
                "trading_calendar": "PASS",
                "daily_state": "PASS",
                "evidence_sha256": H,
                "source_count": 1,
            }
            for market in ("SSE", "SZSE", "BSE")
        },
    }


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert meta["reason"] == "evidence_missing"

    x = complete()
    del x["markets"]["BSE"]
    write(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert meta["market_failures"]["BSE"] == ["missing"]

    x = complete()
    x["future_leakage_violations"] = 1
    write(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "future_leakage_violations" in meta["failures"]

    x = complete()
    x["window_end"] = "2026-09-29"
    write(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "freshness" in meta["failures"]

    x = complete()
    x["canonical_sha256"] = "not-a-hash"
    write(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "canonical_sha256" in meta["failures"]

    x = complete()
    write(root, x)
    status, detail, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "PASS"
    assert not meta["failures"]
    assert "SSE/SZSE/BSE" in detail

print("HISTORICAL ST PIT FAIL-CLOSED CONTRACT TEST PASS")
