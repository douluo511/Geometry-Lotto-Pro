from __future__ import annotations

import hashlib
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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_bound_file(root: Path, rel_path, expected_sha):
    """Verify a declared evidence hash against real bytes under root.

    Absolute paths and traversal outside root are rejected.  A syntactically
    valid SHA-256 string is not evidence by itself: PASS requires the bound
    file to exist and hash to the declared value.
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        return False, "path_missing", None
    if not _hex64(expected_sha):
        return False, "declared_hash_invalid", None

    base = Path(root).resolve()
    raw = Path(rel_path)
    if raw.is_absolute():
        return False, "absolute_path_forbidden", None
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return False, "path_escape", None

    if not candidate.is_file():
        return False, "file_missing", str(candidate)

    actual = _sha256_file(candidate)
    if actual.lower() != str(expected_sha).lower():
        return False, "hash_mismatch", {
            "path": str(candidate),
            "expected": str(expected_sha).lower(),
            "actual": actual,
        }
    return True, "PASS", {
        "path": str(candidate),
        "sha256": actual,
    }


def evaluate_historical_st_pit(root: Path, expected_trade_date=None):
    """Fail-closed evaluator for daily historical ST/suspension PIT evidence.

    PASS is intentionally hard to obtain.  It requires:
    - explicit complete SSE/SZSE/BSE market assertions;
    - point-in-time/freshness/no-future-leakage assertions;
    - real canonical/source/market evidence files under the product root; and
    - SHA-256 recomputation of those exact bytes matching the evidence claims.

    Diagnostic discovery, partial markets, self-declared hashes, missing files,
    path escapes, stale evidence, or byte tampering all remain WARN.
    """
    root = Path(root)
    path = root / "cache" / "historical_st_pit.json"
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
    bindings = {}

    if obj.get("status") != PASS:
        failures.append("status")
    if obj.get("full_historical_st_pit") != PASS:
        failures.append("full_historical_st_pit")
    if obj.get("daily_state_complete") is not True:
        failures.append("daily_state_complete")
    if obj.get("point_in_time_only") is not True:
        failures.append("point_in_time_only")
    try:
        if int(obj.get("future_leakage_violations", -1)) != 0:
            failures.append("future_leakage_violations")
    except Exception:
        failures.append("future_leakage_violations")

    start = _parse_day(obj.get("window_start"))
    end = _parse_day(obj.get("window_end"))
    if start is None or end is None or start > end:
        failures.append("window")
    expected = _parse_day(expected_trade_date) if expected_trade_date else None
    if expected is not None and (end is None or end < expected):
        failures.append("freshness")

    canonical_ok, canonical_reason, canonical_meta = _verify_bound_file(
        root, obj.get("canonical_path"), obj.get("canonical_sha256")
    )
    bindings["canonical"] = {
        "status": PASS if canonical_ok else WARN,
        "reason": canonical_reason,
        "meta": canonical_meta,
    }
    if not canonical_ok:
        failures.append("canonical_binding")

    source_ok, source_reason, source_meta = _verify_bound_file(
        root, obj.get("source_manifest_path"), obj.get("source_manifest_sha256")
    )
    bindings["source_manifest"] = {
        "status": PASS if source_ok else WARN,
        "reason": source_reason,
        "meta": source_meta,
    }
    if not source_ok:
        failures.append("source_manifest_binding")

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
            bindings[market] = {"status": WARN, "reason": "market_missing"}
        else:
            for field in (
                "st_identity",
                "suspension_state",
                "trading_calendar",
                "daily_state",
            ):
                if m.get(field) != PASS:
                    bad.append(field)
            try:
                if int(m.get("source_count", 0)) < 1:
                    bad.append("source_count")
            except Exception:
                bad.append("source_count")

            evidence_ok, evidence_reason, evidence_meta = _verify_bound_file(
                root, m.get("evidence_path"), m.get("evidence_sha256")
            )
            bindings[market] = {
                "status": PASS if evidence_ok else WARN,
                "reason": evidence_reason,
                "meta": evidence_meta,
            }
            if not evidence_ok:
                bad.append("evidence_binding")
        if bad:
            market_failures[market] = bad

    if market_failures:
        failures.append("market_coverage")

    # Stable order makes machine evidence deterministic and easier to diff.
    failures = list(dict.fromkeys(failures))

    meta = {
        "schema": obj.get("schema"),
        "window_start": obj.get("window_start"),
        "window_end": obj.get("window_end"),
        "expected_trade_date": str(expected_trade_date) if expected_trade_date else None,
        "market_failures": market_failures,
        "failures": failures,
        "canonical_sha256": obj.get("canonical_sha256"),
        "source_manifest_sha256": obj.get("source_manifest_sha256"),
        "bindings": bindings,
    }

    if failures:
        return WARN, "历史ST/停牌逐日PIT证据未完整闭合：" + ",".join(failures), meta

    return PASS, (
        f"历史ST/停牌逐日PIT证据完整且字节哈希绑定；SSE/SZSE/BSE；"
        f"{obj.get('window_start')}..{obj.get('window_end')}"
    ), meta


def normalize_stock_code(value) -> str:
    raw = str(value).strip()
    if raw.endswith(".0") and raw[:-2].isdigit():
        raw = raw[:-2]
    if not raw.isdigit():
        raise ValueError(f"invalid stock code: {value!r}")
    code = raw.zfill(6)
    if len(code) != 6:
        raise ValueError(f"invalid stock code width: {value!r}")
    return code


def market_for_code(value) -> str:
    code = normalize_stock_code(value)
    if code.startswith("6"):
        return "SSE"
    if code.startswith(("0", "3")):
        return "SZSE"
    if code.startswith(("4", "8")) or code.startswith("92"):
        return "BSE"
    raise ValueError(f"unsupported A-share market code: {code}")


def load_historical_st_pit_daily_state(root: Path, expected_trade_date=None):
    """Load the exact hash-bound daily PIT state after fail-closed verification.

    The returned mapping is keyed by (date, market, code). No nearest-date,
    forward-fill, backward-fill, or present-day fallback is permitted.
    """
    root = Path(root)
    status, detail, meta = evaluate_historical_st_pit(root, expected_trade_date)
    if status != PASS:
        raise RuntimeError(f"historical ST/PIT evidence not PASS: {detail}")

    claim_path = root / "cache" / "historical_st_pit.json"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    base = root.resolve()
    canonical = (base / str(claim["canonical_path"])).resolve()
    try:
        canonical.relative_to(base)
    except ValueError as exc:
        raise RuntimeError("historical ST/PIT canonical path escaped product root") from exc

    window_start = _parse_day(claim.get("window_start"))
    window_end = _parse_day(claim.get("window_end"))
    if window_start is None or window_end is None:
        raise RuntimeError("historical ST/PIT evidence has invalid window")

    state = {}
    with canonical.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception as exc:
                raise RuntimeError(
                    f"historical ST/PIT canonical JSONL invalid at line {line_no}"
                ) from exc
            day = _parse_day(row.get("date")) if isinstance(row, dict) else None
            if day is None or day < window_start or day > window_end:
                raise RuntimeError(
                    f"historical ST/PIT canonical date outside verified window at line {line_no}"
                )
            market = str(row.get("market", "")).strip().upper()
            if market not in REQUIRED_MARKETS:
                raise RuntimeError(
                    f"historical ST/PIT canonical market invalid at line {line_no}: {market!r}"
                )
            code = normalize_stock_code(row.get("code"))
            if market_for_code(code) != market:
                raise RuntimeError(
                    f"historical ST/PIT market/code mismatch at line {line_no}: {market}/{code}"
                )
            st = row.get("st")
            suspended = row.get("suspended")
            if type(st) is not bool or type(suspended) is not bool:
                raise RuntimeError(
                    f"historical ST/PIT st/suspended must be booleans at line {line_no}"
                )
            key = (day.isoformat(), market, code)
            if key in state:
                raise RuntimeError(
                    f"historical ST/PIT duplicate date/market/code at line {line_no}: {key}"
                )
            state[key] = (st, suspended)

    if not state:
        raise RuntimeError("historical ST/PIT canonical state is empty")

    return state, {
        "status": PASS,
        "detail": detail,
        "window_start": claim.get("window_start"),
        "window_end": claim.get("window_end"),
        "canonical_sha256": claim.get("canonical_sha256"),
        "source_manifest_sha256": claim.get("source_manifest_sha256"),
        "row_count": len(state),
        "bindings": meta.get("bindings", {}),
    }
