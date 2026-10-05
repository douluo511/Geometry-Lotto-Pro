import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))

from stock_ai.backtest import _apply_historical_tradability_pit


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bytes(root: Path, rel: str, payload: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return sha(p)


def install_complete_claim(root: Path, rows: list[dict]) -> None:
    canonical_path = "cache/historical_st_pit_daily_state.jsonl"
    canonical_payload = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    canonical_sha = write_bytes(root, canonical_path, canonical_payload)
    source_manifest_path = "cache/historical_st_pit_sources.json"
    source_manifest_sha = write_bytes(
        root,
        source_manifest_path,
        b'{"point_in_time_only":true,"sources":["SSE","SZSE","BSE"]}\n',
    )
    markets = {}
    for market in ("SSE", "SZSE", "BSE"):
        rel = f"cache/historical_st_pit_{market.lower()}.json"
        evidence_sha = write_bytes(
            root,
            rel,
            (json.dumps(
                {"market": market, "st_identity": "PASS", "suspension_state": "PASS"},
                sort_keys=True,
            ) + "\n").encode("utf-8"),
        )
        markets[market] = {
            "st_identity": "PASS",
            "suspension_state": "PASS",
            "trading_calendar": "PASS",
            "daily_state": "PASS",
            "evidence_path": rel,
            "evidence_sha256": evidence_sha,
            "source_count": 1,
        }
    claim = {
        "schema": "stock-ai-historical-st-pit-v1",
        "status": "PASS",
        "full_historical_st_pit": "PASS",
        "daily_state_complete": True,
        "point_in_time_only": True,
        "future_leakage_violations": 0,
        "window_start": "2018-01-01",
        "window_end": "2026-09-30",
        "canonical_path": canonical_path,
        "canonical_sha256": canonical_sha,
        "source_manifest_path": source_manifest_path,
        "source_manifest_sha256": source_manifest_sha,
        "markets": markets,
    }
    p = root / "cache" / "historical_st_pit.json"
    p.write_text(json.dumps(claim, ensure_ascii=False), encoding="utf-8")


def frame():
    return pd.DataFrame([
        {"date": pd.Timestamp("2026-09-30"), "code": "600000", "log_amount20": 20.0},
        {"date": pd.Timestamp("2026-09-30"), "code": "600001", "log_amount20": 20.0},
        {"date": pd.Timestamp("2026-09-30"), "code": "000001", "log_amount20": 20.0},
        {"date": pd.Timestamp("2026-09-30"), "code": "430001", "log_amount20": 20.0},
    ])


rows = [
    {"date": "2026-09-30", "market": "SSE", "code": "600000", "st": False, "suspended": False},
    {"date": "2026-09-30", "market": "SSE", "code": "600001", "st": True, "suspended": False},
    {"date": "2026-09-30", "market": "SZSE", "code": "000001", "st": False, "suspended": True},
    {"date": "2026-09-30", "market": "BSE", "code": "430001", "st": False, "suspended": False},
]

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_complete_claim(root, rows)
    cfg = {"universe": {"exclude_st": True}}
    out, evidence = _apply_historical_tradability_pit(frame(), cfg, root)
    assert set(out["code"]) == {"600000", "430001"}
    assert evidence["binding"] == "same-date-market-code-only"
    assert evidence["excluded_st_rows"] == 1
    assert evidence["excluded_suspended_rows"] == 1
    assert evidence["covered_rows"] == 4

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_complete_claim(root, rows[:-1])
    try:
        _apply_historical_tradability_pit(frame(), {"universe": {"exclude_st": True}}, root)
        raise AssertionError("missing exact PIT row must fail closed")
    except RuntimeError as exc:
        assert "coverage missing" in str(exc)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    future_only = [dict(row, date="2026-10-01") if row["code"] == "600000" else row for row in rows]
    install_complete_claim(root, future_only)
    try:
        _apply_historical_tradability_pit(frame(), {"universe": {"exclude_st": True}}, root)
        raise AssertionError("future-only PIT state must not be backfilled")
    except RuntimeError as exc:
        assert "outside verified window" in str(exc) or "coverage missing" in str(exc)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_complete_claim(root, rows)
    out, evidence = _apply_historical_tradability_pit(
        frame(), {"universe": {"exclude_st": False}}, root
    )
    assert set(out["code"]) == {"600000", "600001", "430001"}
    assert evidence["excluded_st_rows"] == 0
    assert evidence["excluded_suspended_rows"] == 1

print("HISTORICAL ST PIT BACKTEST CONSUMPTION CONTRACT PASS")
