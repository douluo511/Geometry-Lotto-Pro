import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))

import stock_ai.backtest as bt


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bytes(root: Path, rel: str, payload: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return sha(p)


def install_claim(root: Path, rows: list[dict]) -> None:
    canonical_rel = "cache/historical_st_pit_daily_state.jsonl"
    canonical = root / canonical_rel
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    source_rel = "cache/historical_st_pit_sources.json"
    source_sha = write_bytes(
        root, source_rel,
        b'{"point_in_time_only":true,"sources":["SSE","SZSE","BSE"]}\n',
    )
    markets = {}
    for market in ("SSE", "SZSE", "BSE"):
        rel = f"cache/historical_st_pit_{market.lower()}.json"
        ev_sha = write_bytes(
            root, rel,
            (json.dumps({
                "market": market,
                "st_identity": "PASS",
                "suspension_state": "PASS",
                "trading_calendar": "PASS",
                "daily_state": "PASS",
            }, sort_keys=True) + "\n").encode("utf-8"),
        )
        markets[market] = {
            "st_identity": "PASS",
            "suspension_state": "PASS",
            "trading_calendar": "PASS",
            "daily_state": "PASS",
            "evidence_path": rel,
            "evidence_sha256": ev_sha,
            "source_count": 1,
        }
    claim = {
        "schema": "stock-ai-historical-st-pit-v1",
        "status": "PASS",
        "full_historical_st_pit": "PASS",
        "daily_state_complete": True,
        "point_in_time_only": True,
        "future_leakage_violations": 0,
        "window_start": "2026-01-05",
        "window_end": "2026-01-07",
        "canonical_path": canonical_rel,
        "canonical_sha256": sha(canonical),
        "source_manifest_path": source_rel,
        "source_manifest_sha256": source_sha,
        "markets": markets,
    }
    (root / "cache" / "historical_st_pit.json").write_text(
        json.dumps(claim, sort_keys=True), encoding="utf-8"
    )


D1, D2, D3 = "2026-01-05", "2026-01-06", "2026-01-07"
rows = [
    # SSE high-liquidity name is ST on signal day and must be removed BEFORE Top-N.
    {"date": D1, "market": "SSE", "code": "600001", "st": True,  "suspended": False},
    {"date": D2, "market": "SSE", "code": "600001", "st": False, "suspended": False},
    {"date": D3, "market": "SSE", "code": "600001", "st": False, "suspended": False},
    # Normal signal; it becomes ST on D2. D2 ST is future selection information
    # and must NOT remove a candidate chosen at D1. It is not suspended.
    {"date": D1, "market": "SSE", "code": "600002", "st": False, "suspended": False},
    {"date": D2, "market": "SSE", "code": "600002", "st": True,  "suspended": False},
    {"date": D3, "market": "SSE", "code": "600002", "st": True,  "suspended": False},
    # Entry-day suspension must block execution.
    {"date": D1, "market": "SSE", "code": "600003", "st": False, "suspended": False},
    {"date": D2, "market": "SSE", "code": "600003", "st": False, "suspended": True},
    {"date": D3, "market": "SSE", "code": "600003", "st": False, "suspended": False},
    # Calendar anchors for other required markets.
    {"date": D1, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
    {"date": D2, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
    {"date": D3, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
    {"date": D1, "market": "BSE",  "code": "430001", "st": False, "suspended": False},
    {"date": D2, "market": "BSE",  "code": "430001", "st": False, "suspended": False},
    {"date": D3, "market": "BSE",  "code": "430001", "st": False, "suspended": False},
]

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_claim(root, rows)
    ds = pd.DataFrame([
        {"date": D1, "entry_date": D2, "code": "600001", "log_amount20": 30.0},
        {"date": D1, "entry_date": D2, "code": "600002", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 1, "exclude_st": True}}
    with patch.object(bt, "ROOT", root):
        out, ev = bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
    assert out["code"].tolist() == ["600002"], out
    assert ev["signal_st_excluded"] == 1
    assert ev["liquidity_ranking_after_signal_pit"] is True
    assert ev["market_calendar_source"] == "verified_canonical_daily_state"
    assert ev["entry_suspended_excluded"] == 0
    assert ev["future_safety"].startswith("ST selection uses signal-date")

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_claim(root, rows)
    ds = pd.DataFrame([
        {"date": D1, "entry_date": D2, "code": "600003", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 0, "exclude_st": True}}
    with patch.object(bt, "ROOT", root):
        try:
            bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
        except RuntimeError as exc:
            assert "entry execution" in str(exc)
        else:
            raise AssertionError("entry-day suspension must fail/empty closed")

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_claim(root, rows)
    ds = pd.DataFrame([
        # Observed stock row skips D2, while verified SSE calendar says D2 is next.
        {"date": D1, "entry_date": D3, "code": "600002", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 0, "exclude_st": True}}
    with patch.object(bt, "ROOT", root):
        try:
            bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
        except RuntimeError as exc:
            assert "next-market-open" in str(exc)
        else:
            raise AssertionError("skipped verified next-market day must fail/empty closed")

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    bad = [dict(r) for r in rows]
    bad[0]["market"] = "SZSE"  # 600001 is an SSE code.
    install_claim(root, bad)
    ds = pd.DataFrame([
        {"date": D1, "entry_date": D2, "code": "600001", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 0, "exclude_st": False}}
    with patch.object(bt, "ROOT", root):
        try:
            bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
        except RuntimeError as exc:
            assert "market/code mismatch" in str(exc)
        else:
            raise AssertionError("market/code mismatch must fail closed")

print("HISTORICAL PIT BACKTEST POLICY / TOP-N / FUTURE-SAFETY CONTRACT PASS")
