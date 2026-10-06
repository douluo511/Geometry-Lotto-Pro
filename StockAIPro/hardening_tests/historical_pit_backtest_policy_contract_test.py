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
from stock_ai.historical_pit import evaluate_historical_st_pit


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bytes(root: Path, rel: str, payload: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return sha(p)


def install_claim(root: Path, rows: list[dict], calendar_dates=None) -> None:
    calendar_dates = list(calendar_dates or [D1, D2, D3])
    window_start, window_end = calendar_dates[0], calendar_dates[-1]
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
    canonical_sha = sha(canonical)
    calendar_rel = "cache/historical_market_calendar.json"
    calendar_sha = write_bytes(
        root,
        calendar_rel,
        (json.dumps({
            "schema": "stock-ai-historical-market-calendar-v1",
            "window_start": window_start,
            "window_end": window_end,
            "markets": {
                market: {"status": "PASS", "source_count": 1, "dates": calendar_dates}
                for market in ("SSE", "SZSE", "BSE")
            },
        }, sort_keys=True) + "\n").encode("utf-8"),
    )
    denominator_markets = {}
    market_rank = {"SSE": 0, "SZSE": 1, "BSE": 2}
    for market in ("SSE", "SZSE", "BSE"):
        market_rows = [r for r in rows if r["market"] == market]
        by_code = {}
        for row in market_rows:
            by_code.setdefault(row["code"], []).append(row["date"])
        lifecycle_rel = f"cache/historical_st_pit_{market.lower()}_lifecycle.jsonl"
        lifecycle_lines = []
        expected_lines = []
        for code in sorted(by_code):
            code_dates = sorted(by_code[code])
            listing, delisting = code_dates[0], code_dates[-1]
            lifecycle_lines.append(json.dumps({
                "market": market, "code": code,
                "listing_date": listing, "delisting_date": delisting,
            }, sort_keys=True) + "\n")
            for day in calendar_dates:
                if listing <= day <= delisting:
                    expected_lines.append(f"{day}|{market}|{code}\n")
        lifecycle_sha = write_bytes(root, lifecycle_rel, "".join(lifecycle_lines).encode("utf-8"))
        expected_rel = f"cache/historical_st_pit_{market.lower()}_expected_keys.txt"
        expected_payload = "".join(expected_lines).encode("ascii")
        expected_sha = write_bytes(root, expected_rel, expected_payload)
        raw_rel = f"cache/raw_{market.lower()}_fixture.json"
        raw_sha = write_bytes(root, raw_rel, (json.dumps({"market": market, "fixture": True}, sort_keys=True) + "\n").encode("utf-8"))
        provenance_rel = f"cache/historical_st_pit_{market.lower()}_provenance.json"
        provenance_sha = write_bytes(
            root, provenance_rel,
            (json.dumps({
                "market": market,
                "point_in_time_only": True,
                "raw_files": [{"path": raw_rel, "sha256": raw_sha}],
            }, sort_keys=True) + "\n").encode("utf-8"),
        )
        denominator_markets[market] = {
            "status": "PASS",
            "source_count": 1,
            "lifecycle_path": lifecycle_rel,
            "lifecycle_sha256": lifecycle_sha,
            "expected_keys_path": expected_rel,
            "expected_keys_sha256": expected_sha,
            "expected_key_count": len(expected_lines),
            "provenance_path": provenance_rel,
            "provenance_sha256": provenance_sha,
        }
    denominator_rel = "cache/historical_st_pit_denominator.json"
    denominator_sha = write_bytes(
        root, denominator_rel,
        (json.dumps({
            "schema": "stock-ai-historical-pit-denominator-v1",
            "window_start": window_start,
            "window_end": window_end,
            "calendar_manifest_sha256": calendar_sha,
            "source_manifest_sha256": source_sha,
            "universe_definition": "all_eligible_mainland_equities_with_listing_delisting_boundaries",
            "nonlisted_policy": "exclude_pre_listing_and_post_delisting",
            "st_effective_date_rule": "point_in_time_effective_date_only",
            "suspension_effective_date_rule": "point_in_time_effective_date_only",
            "completeness_formula": "canonical_unique_expected_keys/expected_keys",
            "raw_provenance_required": True,
            "point_in_time_only": True,
            "future_leakage_violations": 0,
            "source_gap_count": 0,
            "semantic_ambiguity_count": 0,
            "markets": denominator_markets,
        }, sort_keys=True) + "\n").encode("utf-8"),
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
                "point_in_time_only": True,
                "future_leakage_violations": 0,
                "window_start": window_start,
                "window_end": window_end,
                "canonical_sha256": canonical_sha,
                "source_count": 1,
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
        "window_start": window_start,
        "window_end": window_end,
        "canonical_path": canonical_rel,
        "canonical_sha256": canonical_sha,
        "source_manifest_path": source_rel,
        "source_manifest_sha256": source_sha,
        "calendar_manifest_path": calendar_rel,
        "calendar_manifest_sha256": calendar_sha,
        "denominator_manifest_path": denominator_rel,
        "denominator_manifest_sha256": denominator_sha,
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
    {"date": D1, "market": "BSE",  "code": "920023", "st": False, "suspended": False},
    {"date": D2, "market": "BSE",  "code": "920023", "st": False, "suspended": False},
    {"date": D3, "market": "BSE",  "code": "920023", "st": False, "suspended": False},
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
        pit_status, pit_detail, pit_meta = evaluate_historical_st_pit(root, D3)
        print("BACKTEST_POLICY_FIXTURE_EVALUATOR=" + json.dumps({
            "status": pit_status,
            "detail": pit_detail,
            "failures": pit_meta.get("failures"),
            "market_failures": pit_meta.get("market_failures"),
            "bindings": {
                key: {
                    "status": value.get("status"),
                    "reason": value.get("reason"),
                    "semantic_status": value.get("semantic_status"),
                    "semantic_reason": value.get("semantic_reason"),
                }
                for key, value in (pit_meta.get("bindings") or {}).items()
            },
        }, sort_keys=True))
        assert pit_status == "PASS", (pit_detail, pit_meta)
        out, ev = bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
    assert out["code"].tolist() == ["600002"], out
    assert ev["signal_st_excluded"] == 1
    assert ev["liquidity_ranking_after_signal_pit"] is True
    assert ev["market_calendar_source"] == "verified_bound_market_calendar"
    assert ev["calendar_manifest_sha256"]
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
    calendar_dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    omitted = "2026-01-06"
    calendar_rows = []
    anchors = (("SSE", "600002"), ("SZSE", "000001"), ("BSE", "920023"))
    for market, code in anchors:
        for day in calendar_dates:
            if day == omitted:
                continue
            calendar_rows.append({
                "date": day, "market": market, "code": code,
                "st": False, "suspended": False,
            })
    install_claim(root, calendar_rows, calendar_dates=calendar_dates)
    status, _, meta = evaluate_historical_st_pit(root, calendar_dates[-1])
    assert status == "WARN"
    assert "canonical_calendar_coverage" in meta["failures"]
    assert meta["bindings"]["canonical"]["calendar_coverage_status"] == "WARN"
    assert omitted in meta["bindings"]["canonical"]["calendar_coverage_meta"]["missing_samples"]["SSE"]

    ds = pd.DataFrame([
        {"date": calendar_dates[0], "entry_date": calendar_dates[2], "code": "600002", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 0, "exclude_st": True}}
    with patch.object(bt, "ROOT", root):
        try:
            bt._historical_candidate_pool(ds, cfg, pd.to_datetime(calendar_dates))
        except RuntimeError as exc:
            assert "historical ST/PIT evidence not qualified" in str(exc)
        else:
            raise AssertionError("canonical omission of a bound trading day must fail closed")


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    bad = [dict(r) for r in rows]
    bad[0]["market"] = "SZSE"  # 600001 is an SSE code.
    install_claim(root, bad)

    # The hardened evaluator must reject the malformed canonical bytes at the
    # earliest evidence boundary and preserve the exact semantic reason.
    status, _, meta = evaluate_historical_st_pit(root, D3)
    assert status == "WARN"
    assert "canonical_semantics" in meta["failures"]
    assert "market_code_mismatch" in meta["bindings"]["canonical"]["semantic_reason"]

    # End-to-end policy consumption must still fail closed.  Do not couple this
    # assertion to the older downstream loader wording because the bundle is
    # now rejected before lookup.
    ds = pd.DataFrame([
        {"date": D1, "entry_date": D2, "code": "600001", "log_amount20": 20.0},
    ])
    cfg = {"universe": {"min_turnover_cny": 0, "live_top_n": 0, "exclude_st": False}}
    with patch.object(bt, "ROOT", root):
        try:
            bt._historical_candidate_pool(ds, cfg, pd.to_datetime([D1, D2, D3]))
        except RuntimeError as exc:
            assert "historical ST/PIT evidence not qualified" in str(exc)
        else:
            raise AssertionError("market/code mismatch must fail closed")

print("HISTORICAL PIT BACKTEST POLICY / TOP-N / FUTURE-SAFETY CONTRACT PASS")
