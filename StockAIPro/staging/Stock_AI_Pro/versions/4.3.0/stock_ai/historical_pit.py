from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

SCHEMA = "stock-ai-historical-st-pit-v1"
REQUIRED_MARKETS = ("SSE", "SZSE", "BSE")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PASS = "PASS"
WARN = "WARN"


def _parse_day(value):
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def _hex64(value) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value.lower()) is not None


def evaluate_historical_st_pit(root: Path, expected_trade_date=None):
    """Fail-closed evaluator for daily historical ST/suspension PIT evidence.

    This function never infers PASS from a diagnostic, endpoint discovery, or
    partial market sample. PASS requires one current canonical evidence file
    whose global and per-market assertions are explicit and hash-bound.
    """
    path = Path(root) / "cache" / "historical_st_pit.json"
    if not path.is_file():
        return WARN, "historical_st_pit.json 缺失；历史ST/停牌逐日状态未验证", {
            "reason": "evidence_missing",
            "path": str(path),
        }

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return WARN, f"历史ST/PIT证据不可解析：{type(exc).__name__}", {
            "reason": "invalid_json",
            "path": str(path),
        }

    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
        return WARN, "历史ST/PIT证据 schema 不匹配", {
            "reason": "schema_mismatch",
            "schema": obj.get("schema") if isinstance(obj, dict) else None,
        }

    failures = []
    if obj.get("status") != PASS:
        failures.append("status")
    if obj.get("full_historical_st_pit") != PASS:
        failures.append("full_historical_st_pit")
    if obj.get("daily_state_complete") is not True:
        failures.append("daily_state_complete")
    if obj.get("point_in_time_only") is not True:
        failures.append("point_in_time_only")
    if int(obj.get("future_leakage_violations", -1)) != 0:
        failures.append("future_leakage_violations")
    if not _hex64(obj.get("canonical_sha256")):
        failures.append("canonical_sha256")
    if not _hex64(obj.get("source_manifest_sha256")):
        failures.append("source_manifest_sha256")

    start = _parse_day(obj.get("window_start"))
    end = _parse_day(obj.get("window_end"))
    if start is None or end is None or start > end:
        failures.append("window")
    expected = _parse_day(expected_trade_date) if expected_trade_date else None
    if expected is not None and (end is None or end < expected):
        failures.append("freshness")

    markets = obj.get("markets")
    if not isinstance(markets, dict):
        failures.append("markets")
        markets = {}

    market_failures = {}
    for market in REQUIRED_MARKETS:
        m = markets.get(market)
        bad = []
        if not isinstance(m, dict):
            bad.append("missing")
        else:
            for field in (
                "st_identity",
                "suspension_state",
                "trading_calendar",
                "daily_state",
            ):
                if m.get(field) != PASS:
                    bad.append(field)
            if not _hex64(m.get("evidence_sha256")):
                bad.append("evidence_sha256")
            try:
                if int(m.get("source_count", 0)) < 1:
                    bad.append("source_count")
            except Exception:
                bad.append("source_count")
        if bad:
            market_failures[market] = bad

    if market_failures:
        failures.append("market_coverage")

    meta = {
        "schema": obj.get("schema"),
        "window_start": obj.get("window_start"),
        "window_end": obj.get("window_end"),
        "expected_trade_date": str(expected_trade_date) if expected_trade_date else None,
        "market_failures": market_failures,
        "failures": failures,
        "canonical_sha256": obj.get("canonical_sha256"),
        "source_manifest_sha256": obj.get("source_manifest_sha256"),
    }

    if failures:
        return WARN, "历史ST/停牌逐日PIT证据未完整闭合：" + ",".join(failures), meta

    return PASS, (
        f"历史ST/停牌逐日PIT证据完整；SSE/SZSE/BSE；"
        f"{obj.get('window_start')}..{obj.get('window_end')}"
    ), meta
