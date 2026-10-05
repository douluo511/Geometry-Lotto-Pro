import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))

import stock_ai.backtest as bt


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bytes(root: Path, rel: str, payload: bytes) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha(path)


def install_evidence(root: Path, rows: list[dict]) -> None:
    canonical_rel = "cache/historical_st_pit_daily_state.jsonl"
    canonical = root / canonical_rel
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    source_rel = "cache/historical_st_pit_sources.json"
    source_sha = write_bytes(
        root,
        source_rel,
        b'{"sources":["SSE","SZSE","BSE"],"point_in_time_only":true}\n',
    )
    markets = {}
    for market in ("SSE", "SZSE", "BSE"):
        rel = f"cache/historical_st_pit_{market.lower()}.json"
        ev_sha = write_bytes(
            root,
            rel,
            (
                json.dumps(
                    {
                        "market": market,
                        "st_identity": "PASS",
                        "suspension_state": "PASS",
                        "trading_calendar": "PASS",
                        "daily_state": "PASS",
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
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
BASE_ROWS = [
    # SSE normal name; future ST on D3 must not leak backward into D1/D2.
    {"date": D1, "market": "SSE", "code": "600001", "st": False, "suspended": False},
    {"date": D2, "market": "SSE", "code": "600001", "st": False, "suspended": False},
    {"date": D3, "market": "SSE", "code": "600001", "st": True, "suspended": False},
    # ST at signal date.
    {"date": D1, "market": "SSE", "code": "600002", "st": True, "suspended": False},
    {"date": D2, "market": "SSE", "code": "600002", "st": False, "suspended": False},
    {"date": D3, "market": "SSE", "code": "600002", "st": False, "suspended": False},
    # Suspension on the true next market day; observed price entry skips to D3.
    {"date": D1, "market": "SSE", "code": "600003", "st": False, "suspended": False},
    {"date": D2, "market": "SSE", "code": "600003", "st": False, "suspended": True},
    {"date": D3, "market": "SSE", "code": "600003", "st": False, "suspended": False},
    # SZSE entry-day suspension.
    {"date": D1, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
    {"date": D2, "market": "SZSE", "code": "000001", "st": False, "suspended": True},
    {"date": D3, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
    # BSE calendar anchor proves all required market calendars are present.
    {"date": D1, "market": "BSE", "code": "430001", "st": False, "suspended": False},
    {"date": D2, "market": "BSE", "code": "430001", "st": False, "suspended": False},
    {"date": D3, "market": "BSE", "code": "430001", "st": False, "suspended": False},
]


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    install_evidence(root, BASE_ROWS)
    ds = pd.DataFrame(
        [
            {"date": D1, "entry_date": D2, "code": "600001"},
            {"date": D1, "entry_date": D2, "code": "600002"},
            {"date": D1, "entry_date": D2, "code": "000001"},
            {"date": D1, "entry_date": D3, "code": "600003"},
        ]
    )
    filtered, evidence = bt._apply_historical_pit_policy(
        ds, {"universe": {"exclude_st": True}}, root
    )
    assert filtered["code"].tolist() == ["600001"], filtered
    assert evidence["status"] == "PASS"
    assert evidence["exact_date_join"] is True
    assert evidence["future_lookup"] is False
    assert evidence["excluded_signal_st"] == 1
    assert evidence["excluded_entry_suspended"] == 2
    assert evidence["excluded_not_next_market_open"] == 1

    # Policy parity: disabling production ST exclusion also disables historical
    # ST exclusion, while suspension handling remains mandatory.
    st_only = ds[ds["code"] == "600002"].copy()
    kept, _ = bt._apply_historical_pit_policy(
        st_only, {"universe": {"exclude_st": False}}, root
    )
    assert kept["code"].tolist() == ["600002"]

    # Future D3 ST state for 600001 must never be used for the D1 signal.
    normal = ds[ds["code"] == "600001"].copy()
    kept, _ = bt._apply_historical_pit_policy(
        normal, {"universe": {"exclude_st": True}}, root
    )
    assert kept["code"].tolist() == ["600001"]

    # Exact-date coverage is fail-closed.  A PASS claim with a hash-bound but
    # incomplete canonical row set must not silently backfill from past/future.
    incomplete = [
        row for row in BASE_ROWS
        if not (row["date"] == D1 and row["code"] == "600001")
    ]
    install_evidence(root, incomplete)
    try:
        bt._apply_historical_pit_policy(
            normal, {"universe": {"exclude_st": True}}, root
        )
    except RuntimeError as exc:
        assert "missing exact signal-date coverage" in str(exc)
    else:
        raise AssertionError("missing PIT signal state must fail closed")

print("HISTORICAL PIT BACKTEST CONSUMPTION / NO-FUTURE-LEAKAGE CONTRACT PASS")
