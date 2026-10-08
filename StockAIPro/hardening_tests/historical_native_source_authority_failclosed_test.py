"""FAIL FIRST: recomputed SHA256 over made-up history is not exchange-native data.

This intentionally reuses the older COMPLETE fixture builder, whose JSONL
contains only one self-declared equity per SSE/SZSE/BSE and fabricated
market trading calendar/ST/suspension. Byte consistency is not source truth.
Without independently verified exchange-original security-master authority,
actual PIT eligibility MUST be WARN, never PASS.
"""
from __future__ import annotations
import runpy
import tempfile
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
old = runpy.run_path(str(HERE / "historical_st_pit_contract_test.py"))
PACKAGE_ROOT = HERE.parent / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))
from stock_ai.historical_pit import evaluate_historical_st_pit

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    claim = old["complete"](root)
    old["write_claim"](root, claim)
    status, detail, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN", (
        "FALSE BUSINESS PASS: three internally hash-consistent, entirely "
        "synthetic exchange-universe/ST/calendar snapshots qualified as "
        "genuine historical point-in-time source-native truth",
        status, detail
    )
    assert "native_source_authority_unverified" in meta.get("failures", []), meta.get("failures")

print("STOCK FORGED SELF-BOUND NATIVE-UNIVERSE BUSINESS GATE 1/1 PASS")
