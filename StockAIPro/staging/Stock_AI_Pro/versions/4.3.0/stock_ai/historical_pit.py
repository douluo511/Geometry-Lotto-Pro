from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

SCHEMA = "stock-ai-historical-st-pit-v1"
CALENDAR_SCHEMA = "stock-ai-historical-market-calendar-v1"
DENOMINATOR_SCHEMA = "stock-ai-historical-pit-denominator-v1"
RAW_LIFECYCLE_SCHEMA = "stock-ai-security-lifecycle-source-v1"
REQUIRED_MARKETS = ("SSE", "SZSE", "BSE")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PASS = "PASS"
WARN = "WARN"
MARKET_LIFECYCLE_START = {"BSE": date(2021, 11, 15)}
# BSE rule published 2024-04-19: NEW IPOs may use 920 codes from
# 2024-04-22, unlike 248 PRE-EXISTING issuers switching in two separate
# phases on 2025-05-06 (6 pilots) and 2025-10-09 (remaining 242).
# These are only necessary date bounds, NOT membership or as-of evidence.
BSE_920_NEW_IPO_CODE_START = date(2024, 4, 22)
BSE_LEGACY_PILOT_SWITCH_DAY = date(2025, 5, 6)
BSE_LEGACY_UNIFIED_SWITCH_DAY = date(2025, 10, 9)


def _parse_day(value):
    """Accept only the canonical as-of YYYY-MM-DD wire date or exact date objects.

    date.fromisoformat also parses YYYYMMDD and ISO-week dates; admitting these
    silently weakens official market-calendar and effective-event contracts.
    """
    if type(value) is date:
        return value
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _hex64(value) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value.lower()) is not None


def _market_for_code(code: str):
    code = str(code)
    if re.fullmatch(r"[0-9]{6}", code) is None:
        return None
    # Scope is mainland A-share / BSE equity codes only.  BSE includes both
    # legacy 4/8 prefixes and ONLY the 920xxx unified securities code.
    # Other 92xxxx codes are NOT BSE listed-equity identifiers.
    if code.startswith("920") or code.startswith(("4", "8")):
        return "BSE"
    if code.startswith(("600", "601", "603", "605", "688")):
        return "SSE"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    return None


def _impossible_market_code_day(market: str, code: str, day: date):
    """Reject objectively impossible exchange/code dates, never assert membership.

    During 2024-04-22..2025-10-08 a 920 code may identify a newly
    listed IPO, while the pre-existing 248 issuers switched in phases.
    A code prefix or these date bounds cannot establish issuer identity,
    pilot identity, actual trading, daily ST/suspension, or full PIT.
    """
    if market == "BSE":
        if day < MARKET_LIFECYCLE_START["BSE"]:
            return "bse_before_market_open"
        if str(code).startswith("920") and day < BSE_920_NEW_IPO_CODE_START:
            return "bse_920_before_new_ipo_activation"
        if str(code).startswith(("4", "8")) and day >= BSE_LEGACY_UNIFIED_SWITCH_DAY:
            return "bse_legacy_after_unified_switch"
    return None


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



def _read_json_object(path: Path):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"invalid_json:{type(exc).__name__}", None
    if not isinstance(obj, dict):
        return False, "not_object", None
    return True, "PASS", obj


def _validate_source_manifest_semantics(path: Path):
    ok, reason, obj = _read_json_object(path)
    if not ok:
        return False, reason, None
    if obj.get("point_in_time_only") is not True:
        return False, "point_in_time_only", obj
    sources = obj.get("sources")
    if not isinstance(sources, list):
        return False, "sources_missing", obj
    normalized = {str(x).strip().upper() for x in sources}
    missing = [market for market in REQUIRED_MARKETS if market not in normalized]
    if missing:
        return False, "sources_missing_markets:" + ",".join(missing), obj
    return True, "PASS", {"sources": sorted(normalized), "point_in_time_only": True}


def _validate_calendar_manifest_semantics(path: Path, start, end, expected=None):
    ok, reason, obj = _read_json_object(path)
    if not ok:
        return False, reason, None
    if obj.get("schema") != CALENDAR_SCHEMA:
        return False, "schema_mismatch", obj
    if start is None or end is None or start > end:
        return False, "invalid_window", obj
    if obj.get("window_start") != start.isoformat() or obj.get("window_end") != end.isoformat():
        return False, "window_mismatch", obj
    markets = obj.get("markets")
    if not isinstance(markets, dict):
        return False, "markets_missing", obj
    normalized = {}
    for market in REQUIRED_MARKETS:
        item = markets.get(market)
        if not isinstance(item, dict):
            return False, f"market_missing:{market}", obj
        if item.get("status") != PASS:
            return False, f"market_not_pass:{market}", obj
        try:
            if int(item.get("source_count", 0)) < 1:
                return False, f"source_count:{market}", obj
        except Exception:
            return False, f"source_count:{market}", obj
        dates_raw = item.get("dates")
        if not isinstance(dates_raw, list) or not dates_raw:
            return False, f"dates_missing:{market}", obj
        parsed = []
        seen = set()
        for idx, value in enumerate(dates_raw):
            day = _parse_day(value)
            if day is None:
                return False, f"date_invalid:{market}:{idx}", obj
            if day < start or day > end:
                return False, f"date_outside_window:{market}:{day.isoformat()}", obj
            lifecycle = MARKET_LIFECYCLE_START.get(market)
            if lifecycle is not None and day < lifecycle:
                return False, f"date_before_market_lifecycle:{market}:{day.isoformat()}", obj
            iso = day.isoformat()
            if iso in seen:
                return False, f"date_duplicate:{market}:{iso}", obj
            seen.add(iso)
            parsed.append(iso)
        if parsed != sorted(parsed):
            return False, f"dates_not_sorted:{market}", obj
        if expected is not None and expected.isoformat() not in seen:
            return False, f"expected_trade_date_missing:{market}:{expected.isoformat()}", obj
        normalized[market] = parsed
    return True, "PASS", {
        "schema": CALENDAR_SCHEMA,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "market_dates": normalized,
        "market_date_counts": {market: len(days) for market, days in normalized.items()},
    }


def _validate_raw_provenance(root: Path, path: Path, market: str):
    ok, reason, obj = _read_json_object(path)
    if not ok:
        return False, reason, None
    if obj.get("market") != market:
        return False, "market_mismatch", obj
    if obj.get("point_in_time_only") is not True:
        return False, "point_in_time_only", obj
    raw_files = obj.get("raw_files")
    if not isinstance(raw_files, list) or not raw_files:
        return False, "raw_files_missing", obj

    verified = []
    lifecycle_by_code = {}
    for idx, item in enumerate(raw_files):
        if not isinstance(item, dict):
            return False, f"raw_file_invalid:{idx}", obj
        good, why, meta = _verify_bound_file(root, item.get("path"), item.get("sha256"))
        if not good:
            return False, f"raw_file_binding:{idx}:{why}", obj

        raw_ok, raw_reason, raw_obj = _read_json_object(Path(meta["path"]))
        if not raw_ok:
            return False, f"raw_file_semantics:{idx}:{raw_reason}", obj
        if raw_obj.get("schema") != RAW_LIFECYCLE_SCHEMA:
            return False, f"raw_file_schema:{idx}", raw_obj
        if raw_obj.get("market") != market:
            return False, f"raw_file_market:{idx}", raw_obj
        if raw_obj.get("point_in_time_only") is not True:
            return False, f"raw_file_point_in_time_only:{idx}", raw_obj

        securities = raw_obj.get("securities")
        if not isinstance(securities, list) or not securities:
            return False, f"raw_file_securities_missing:{idx}", raw_obj
        for sec_idx, sec in enumerate(securities):
            if not isinstance(sec, dict):
                return False, f"raw_security_invalid:{idx}:{sec_idx}", raw_obj
            code = str(sec.get("code") or "").strip()
            listing = _parse_day(sec.get("listing_date"))
            delisting_raw = sec.get("delisting_date")
            delisting = _parse_day(delisting_raw) if delisting_raw not in (None, "") else None
            if _market_for_code(code) != market:
                return False, f"raw_security_market_code:{idx}:{sec_idx}:{code}", raw_obj
            if listing is None:
                return False, f"raw_security_listing_date:{idx}:{sec_idx}:{code}", raw_obj
            impossible = _impossible_market_code_day(market, code, listing)
            if impossible:
                return False, f"{impossible}:raw:{idx}:{sec_idx}:{code}", raw_obj
            if delisting is not None and delisting < listing:
                return False, f"raw_security_lifecycle_order:{idx}:{sec_idx}:{code}", raw_obj

            normalized = (
                code,
                listing.isoformat(),
                delisting.isoformat() if delisting is not None else None,
            )
            previous = lifecycle_by_code.get(code)
            if previous is not None and previous != normalized:
                return False, f"raw_security_conflict:{code}", raw_obj
            lifecycle_by_code[code] = normalized
        verified.append(meta)

    lifecycle_rows = [
        {
            "code": code,
            "listing_date": listing,
            "delisting_date": delisting,
        }
        for code, listing, delisting in sorted(lifecycle_by_code.values())
    ]
    if not lifecycle_rows:
        return False, "raw_lifecycle_empty", obj
    lifecycle_payload = "".join(
        f"{row['code']}|{row['listing_date']}|{row['delisting_date'] or ''}\n"
        for row in lifecycle_rows
    ).encode("utf-8")
    return True, "PASS", {
        "raw_file_count": len(verified),
        "verified": verified,
        "lifecycle_rows": lifecycle_rows,
        "lifecycle_count": len(lifecycle_rows),
        "lifecycle_sha256": hashlib.sha256(lifecycle_payload).hexdigest(),
    }

def _read_lifecycle(path: Path, market: str):
    rows = []
    seen = set()
    last_code = None
    try:
        handle = path.open("r", encoding="utf-8")
    except Exception as exc:
        return False, f"open_failed:{type(exc).__name__}", None
    with handle:
        for lineno, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception as exc:
                return False, f"malformed_jsonl:{lineno}:{type(exc).__name__}", None
            if not isinstance(item, dict):
                return False, f"row_not_object:{lineno}", None
            code = str(item.get("code") or "").strip()
            row_market = str(item.get("market") or "").strip().upper()
            listing = _parse_day(item.get("listing_date"))
            delisting_raw = item.get("delisting_date")
            delisting = _parse_day(delisting_raw) if delisting_raw not in (None, "") else None
            if row_market != market or _market_for_code(code) != market:
                return False, f"market_code_mismatch:{lineno}", None
            if listing is None:
                return False, f"listing_date_invalid:{lineno}", None
            impossible = _impossible_market_code_day(market, code, listing)
            if impossible:
                return False, f"{impossible}:lifecycle:{lineno}:{code}", None
            if delisting is not None and delisting < listing:
                return False, f"lifecycle_order:{lineno}", None
            if code in seen:
                return False, f"duplicate_code:{code}", None
            if last_code is not None and code < last_code:
                return False, f"lifecycle_not_sorted:{lineno}", None
            last_code = code
            seen.add(code)
            rows.append((code, listing, delisting))
    if not rows:
        return False, "lifecycle_empty", None
    return True, "PASS", rows


def _validate_denominator_manifest_semantics(
    root: Path, path: Path, start, end, calendar_sha256, calendar_semantic_meta,
    source_manifest_sha256, canonical_semantic_meta,
):
    ok, reason, obj = _read_json_object(path)
    if not ok:
        return False, reason, None
    required_scalars = {
        "schema": DENOMINATOR_SCHEMA,
        "universe_definition": "all_eligible_mainland_equities_with_listing_delisting_boundaries",
        "nonlisted_policy": "exclude_pre_listing_and_post_delisting",
        "st_effective_date_rule": "point_in_time_effective_date_only",
        "suspension_effective_date_rule": "point_in_time_effective_date_only",
        "completeness_formula": "canonical_unique_expected_keys/expected_keys",
    }
    for field, expected_value in required_scalars.items():
        if obj.get(field) != expected_value:
            return False, f"{field}_mismatch", obj
    if start is None or end is None or obj.get("window_start") != start.isoformat() or obj.get("window_end") != end.isoformat():
        return False, "window_mismatch", obj
    if str(obj.get("calendar_manifest_sha256") or "").lower() != str(calendar_sha256 or "").lower():
        return False, "calendar_hash_mismatch", obj
    if str(obj.get("source_manifest_sha256") or "").lower() != str(source_manifest_sha256 or "").lower():
        return False, "source_manifest_hash_mismatch", obj
    if obj.get("raw_provenance_required") is not True or obj.get("point_in_time_only") is not True:
        return False, "provenance_or_pit_policy", obj
    for field in ("future_leakage_violations", "source_gap_count", "semantic_ambiguity_count"):
        try:
            if int(obj.get(field, -1)) != 0:
                return False, field, obj
        except Exception:
            return False, field, obj

    calendar_dates = (calendar_semantic_meta or {}).get("market_dates") or {}
    canonical_counts = (canonical_semantic_meta or {}).get("market_row_counts") or {}
    canonical_hashes = (canonical_semantic_meta or {}).get("market_key_sha256") or {}
    markets = obj.get("markets")
    if not isinstance(markets, dict):
        return False, "markets_missing", obj
    result = {}
    for market in REQUIRED_MARKETS:
        item = markets.get(market)
        if not isinstance(item, dict) or item.get("status") != PASS:
            return False, f"market_missing_or_not_pass:{market}", obj
        try:
            if int(item.get("source_count", 0)) < 1:
                return False, f"source_count:{market}", obj
        except Exception:
            return False, f"source_count:{market}", obj

        life_ok, life_reason, life_meta = _verify_bound_file(
            root, item.get("lifecycle_path"), item.get("lifecycle_sha256")
        )
        if not life_ok:
            return False, f"lifecycle_binding:{market}:{life_reason}", obj
        lifecycle_ok, lifecycle_reason, lifecycle = _read_lifecycle(
            Path(life_meta["path"]), market
        )
        if not lifecycle_ok:
            return False, f"lifecycle_semantics:{market}:{lifecycle_reason}", obj

        prov_ok, prov_reason, prov_meta = _verify_bound_file(
            root, item.get("provenance_path"), item.get("provenance_sha256")
        )
        if not prov_ok:
            return False, f"provenance_binding:{market}:{prov_reason}", obj
        raw_ok, raw_reason, raw_meta = _validate_raw_provenance(
            root, Path(prov_meta["path"]), market
        )
        if not raw_ok:
            return False, f"provenance_semantics:{market}:{raw_reason}", obj

        raw_lifecycle = [
            (
                row["code"],
                _parse_day(row["listing_date"]),
                _parse_day(row["delisting_date"]) if row.get("delisting_date") else None,
            )
            for row in (raw_meta.get("lifecycle_rows") or [])
        ]
        if raw_lifecycle != lifecycle:
            return False, f"raw_lifecycle_mismatch:{market}", {
                "raw_count": len(raw_lifecycle),
                "lifecycle_count": len(lifecycle),
                "raw_lifecycle_sha256": raw_meta.get("lifecycle_sha256"),
            }

        expected_ok, expected_reason, expected_meta = _verify_bound_file(
            root, item.get("expected_keys_path"), item.get("expected_keys_sha256")
        )
        if not expected_ok:
            return False, f"expected_keys_binding:{market}:{expected_reason}", obj

        days = [_parse_day(value) for value in (calendar_dates.get(market) or [])]
        if not days or any(day is None for day in days):
            return False, f"calendar_dates_missing:{market}", obj
        derived_lines = []
        for code, listing, delisting in lifecycle:
            for day in days:
                if day < listing or (delisting is not None and day > delisting):
                    continue
                derived_lines.append(f"{day.isoformat()}|{market}|{code}\n")
        if not derived_lines:
            return False, f"derived_denominator_empty:{market}", obj
        derived_payload = "".join(derived_lines).encode("ascii")
        actual_payload = Path(expected_meta["path"]).read_bytes()
        if actual_payload != derived_payload:
            return False, f"expected_keys_not_derivable:{market}", {
                "expected_bytes": len(derived_payload),
                "actual_bytes": len(actual_payload),
            }
        derived_sha = hashlib.sha256(derived_payload).hexdigest()
        derived_count = len(derived_lines)
        try:
            declared_count = int(item.get("expected_key_count", -1))
        except Exception:
            return False, f"expected_key_count:{market}", obj
        if declared_count != derived_count:
            return False, f"expected_key_count:{market}", obj
        if int(canonical_counts.get(market, -1)) != derived_count:
            return False, f"canonical_denominator_count:{market}", {
                "canonical": canonical_counts.get(market), "expected": derived_count
            }
        if str(canonical_hashes.get(market) or "").lower() != derived_sha:
            return False, f"canonical_denominator_hash:{market}", {
                "canonical": canonical_hashes.get(market), "expected": derived_sha
            }
        result[market] = {
            "expected_key_count": derived_count,
            "expected_keys_sha256": derived_sha,
            "lifecycle_count": len(lifecycle),
            "raw_provenance": raw_meta,
            "canonical_key_sha256": canonical_hashes.get(market),
        }
    return True, "PASS", {
        "schema": DENOMINATOR_SCHEMA,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "markets": result,
        "total_expected_key_count": sum(x["expected_key_count"] for x in result.values()),
        "completeness_ratio": 1.0,
    }


def _weekday_slots(start: date, end: date) -> int:
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _validate_canonical_semantics(path: Path, start, end, expected):
    if start is None or end is None or start > end:
        return False, "invalid_window", None

    counts = {market: 0 for market in REQUIRED_MARKETS}
    dates = {market: set() for market in REQUIRED_MARKETS}
    key_hashers = {market: hashlib.sha256() for market in REQUIRED_MARKETS}
    market_rank = {market: idx for idx, market in enumerate(REQUIRED_MARKETS)}
    seen = set()
    last_sort_key = None
    rows = 0

    try:
        handle = path.open("r", encoding="utf-8")
    except Exception as exc:
        return False, f"open_failed:{type(exc).__name__}", None

    with handle:
        for lineno, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            rows += 1
            try:
                row = json.loads(text)
            except Exception as exc:
                return False, f"malformed_jsonl:{lineno}:{type(exc).__name__}", None
            if not isinstance(row, dict):
                return False, f"row_not_object:{lineno}", None

            day = _parse_day(row.get("date"))
            market = str(row.get("market") or "").strip().upper()
            code = str(row.get("code") or "").strip()
            st = row.get("st")
            suspended = row.get("suspended")

            if day is None or day < start or day > end:
                return False, f"date_outside_window:{lineno}", None
            if market not in REQUIRED_MARKETS:
                return False, f"market_invalid:{lineno}:{market}", None
            expected_market = _market_for_code(code)
            if expected_market is None:
                return False, f"security_code_invalid:{lineno}:{code}", None
            if market != expected_market:
                return False, f"market_code_mismatch:{lineno}:{market}/{code}", None
            impossible = _impossible_market_code_day(market, code, day)
            if impossible:
                return False, f"{impossible}:daily:{lineno}:{code}", None
            if type(st) is not bool or type(suspended) is not bool:
                return False, f"state_type_invalid:{lineno}", None

            key = (day.isoformat(), code)
            if key in seen:
                return False, f"duplicate_key:{day.isoformat()}:{code}", None
            sort_key = (market_rank[market], code, day.isoformat())
            if last_sort_key is not None and sort_key < last_sort_key:
                return False, f"canonical_key_order:{lineno}", None
            last_sort_key = sort_key
            seen.add(key)
            counts[market] += 1
            dates[market].add(day.isoformat())
            key_hashers[market].update(
                f"{day.isoformat()}|{market}|{code}\n".encode("ascii")
            )

    if rows < 1:
        return False, "canonical_empty", None
    missing_markets = [market for market, count in counts.items() if count < 1]
    if missing_markets:
        return False, "missing_markets:" + ",".join(missing_markets), {
            "rows": rows,
            "market_row_counts": counts,
        }

    # A hash-bound three-market file can still be semantically incomplete if it
    # contains only one/few dates while claiming a multi-year daily-state window.
    # Require a conservative weekday-density floor before any PASS. This is a
    # sanity floor, not a substitute for a bound official trading-calendar x
    # point-in-time-universe denominator in the real production evidence bundle.
    date_axis_sanity = {}
    for market in REQUIRED_MARKETS:
        effective_start = max(start, MARKET_LIFECYCLE_START.get(market, start))
        weekday_slots = _weekday_slots(effective_start, end) if effective_start <= end else 0
        minimum_dates = max(1, (weekday_slots * 7 + 9) // 10) if weekday_slots else 1
        observed_dates = len(dates[market])
        date_axis_sanity[market] = {
            "effective_start": effective_start.isoformat(),
            "window_end": end.isoformat(),
            "weekday_slots": weekday_slots,
            "minimum_date_count_70pct_weekdays": minimum_dates,
            "observed_date_count": observed_dates,
        }
        if observed_dates < minimum_dates:
            return False, f"date_axis_too_sparse:{market}:{observed_dates}/{minimum_dates}", {
                "rows": rows,
                "market_row_counts": counts,
                "market_date_counts": {m: len(days) for m, days in dates.items()},
                "date_axis_sanity": date_axis_sanity,
            }

    if expected is not None:
        expected_iso = expected.isoformat()
        missing_fresh = [market for market in REQUIRED_MARKETS if expected_iso not in dates[market]]
        if missing_fresh:
            return False, "expected_trade_date_missing_markets:" + ",".join(missing_fresh), {
                "rows": rows,
                "market_row_counts": counts,
                "expected_trade_date": expected_iso,
            }

    return True, "PASS", {
        "rows": rows,
        "market_row_counts": counts,
        "market_key_sha256": {market: key_hashers[market].hexdigest() for market in REQUIRED_MARKETS},
        "market_date_counts": {market: len(days) for market, days in dates.items()},
        "market_dates": {market: sorted(days) for market, days in dates.items()},
        "market_first_date": {market: min(days) for market, days in dates.items()},
        "market_last_date": {market: max(days) for market, days in dates.items()},
        "date_axis_sanity": date_axis_sanity,
        "expected_trade_date": expected.isoformat() if expected is not None else None,
    }


def _validate_market_evidence_semantics(path: Path, market: str, claim_market: dict, claim: dict):
    ok, reason, obj = _read_json_object(path)
    if not ok:
        return False, reason, None
    if obj.get("market") != market:
        return False, "market_mismatch", obj
    for field in ("st_identity", "suspension_state", "trading_calendar", "daily_state"):
        if obj.get(field) != PASS or claim_market.get(field) != PASS:
            return False, f"{field}_not_pass", obj
    if obj.get("point_in_time_only") is not True:
        return False, "point_in_time_only", obj
    try:
        if int(obj.get("future_leakage_violations", -1)) != 0:
            return False, "future_leakage_violations", obj
    except Exception:
        return False, "future_leakage_violations", obj
    if obj.get("window_start") != claim.get("window_start") or obj.get("window_end") != claim.get("window_end"):
        return False, "window_mismatch", obj
    if str(obj.get("canonical_sha256") or "").lower() != str(claim.get("canonical_sha256") or "").lower():
        return False, "canonical_hash_mismatch", obj
    try:
        if int(obj.get("source_count", 0)) < 1:
            return False, "source_count", obj
    except Exception:
        return False, "source_count", obj
    return True, "PASS", {
        "market": market,
        "window_start": obj.get("window_start"),
        "window_end": obj.get("window_end"),
        "canonical_sha256": obj.get("canonical_sha256"),
        "source_count": int(obj.get("source_count")),
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

    calendar_ok, calendar_reason, calendar_meta = _verify_bound_file(
        root, obj.get("calendar_manifest_path"), obj.get("calendar_manifest_sha256")
    )
    bindings["calendar_manifest"] = {
        "status": PASS if calendar_ok else WARN,
        "reason": calendar_reason,
        "meta": calendar_meta,
    }
    if not calendar_ok:
        failures.append("calendar_manifest_binding")

    canonical_semantic_ok = False
    canonical_semantic_meta = None
    calendar_semantic_ok = False
    calendar_semantic_meta = None

    if canonical_ok:
        canonical_semantic_ok, canonical_semantic_reason, canonical_semantic_meta = _validate_canonical_semantics(
            Path(canonical_meta["path"]), start, end, expected
        )
        bindings["canonical"]["semantic_status"] = PASS if canonical_semantic_ok else WARN
        bindings["canonical"]["semantic_reason"] = canonical_semantic_reason
        bindings["canonical"]["semantic_meta"] = canonical_semantic_meta
        if not canonical_semantic_ok:
            failures.append("canonical_semantics")

    if source_ok:
        source_semantic_ok, source_semantic_reason, source_semantic_meta = _validate_source_manifest_semantics(
            Path(source_meta["path"])
        )
        bindings["source_manifest"]["semantic_status"] = PASS if source_semantic_ok else WARN
        bindings["source_manifest"]["semantic_reason"] = source_semantic_reason
        bindings["source_manifest"]["semantic_meta"] = source_semantic_meta
        if not source_semantic_ok:
            failures.append("source_manifest_semantics")

    if calendar_ok:
        calendar_semantic_ok, calendar_semantic_reason, calendar_semantic_meta = _validate_calendar_manifest_semantics(
            Path(calendar_meta["path"]), start, end, expected
        )
        bindings["calendar_manifest"]["semantic_status"] = PASS if calendar_semantic_ok else WARN
        bindings["calendar_manifest"]["semantic_reason"] = calendar_semantic_reason
        bindings["calendar_manifest"]["semantic_meta"] = calendar_semantic_meta
        if not calendar_semantic_ok:
            failures.append("calendar_manifest_semantics")

    denominator_ok, denominator_reason, denominator_meta = _verify_bound_file(
        root, obj.get("denominator_manifest_path"), obj.get("denominator_manifest_sha256")
    )
    bindings["denominator_manifest"] = {
        "status": PASS if denominator_ok else WARN,
        "reason": denominator_reason,
        "meta": denominator_meta,
    }
    if not denominator_ok:
        failures.append("denominator_manifest_binding")

    denominator_semantic_ok = False
    denominator_semantic_meta = None

    if canonical_semantic_ok and calendar_semantic_ok:
        canonical_dates = (canonical_semantic_meta or {}).get("market_dates") or {}
        bound_dates = (calendar_semantic_meta or {}).get("market_dates") or {}
        missing_by_market = {}
        for market in REQUIRED_MARKETS:
            missing = sorted(set(bound_dates.get(market) or []) - set(canonical_dates.get(market) or []))
            if missing:
                missing_by_market[market] = missing
        coverage_meta = {
            "status": PASS if not missing_by_market else WARN,
            "missing_counts": {market: len(days) for market, days in missing_by_market.items()},
            "missing_samples": {market: days[:12] for market, days in missing_by_market.items()},
        }
        bindings["canonical"]["calendar_coverage_status"] = coverage_meta["status"]
        bindings["canonical"]["calendar_coverage_meta"] = coverage_meta
        if missing_by_market:
            failures.append("canonical_calendar_coverage")

    if denominator_ok and canonical_semantic_ok and calendar_semantic_ok:
        denominator_semantic_ok, denominator_semantic_reason, denominator_semantic_meta = _validate_denominator_manifest_semantics(
            root,
            Path(denominator_meta["path"]),
            start,
            end,
            obj.get("calendar_manifest_sha256"),
            calendar_semantic_meta,
            obj.get("source_manifest_sha256"),
            canonical_semantic_meta,
        )
        bindings["denominator_manifest"]["semantic_status"] = PASS if denominator_semantic_ok else WARN
        bindings["denominator_manifest"]["semantic_reason"] = denominator_semantic_reason
        bindings["denominator_manifest"]["semantic_meta"] = denominator_semantic_meta
        if not denominator_semantic_ok:
            failures.append("denominator_manifest_semantics")

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
            if evidence_ok:
                evidence_semantic_ok, evidence_semantic_reason, evidence_semantic_meta = _validate_market_evidence_semantics(
                    Path(evidence_meta["path"]), market, m, obj
                )
                bindings[market]["semantic_status"] = PASS if evidence_semantic_ok else WARN
                bindings[market]["semantic_reason"] = evidence_semantic_reason
                bindings[market]["semantic_meta"] = evidence_semantic_meta
                if not evidence_semantic_ok:
                    bad.append("evidence_semantics")
            else:
                bad.append("evidence_binding")
        if bad:
            market_failures[market] = bad

    if market_failures:
        failures.append("market_coverage")

    # SHA256 over self-authored normalized JSON is not a genuine exchange
    # original SSE, SZSE or BSE native issuer master / historical ST source.
    # Until three independent exchange-native historical masters and their
    # day-by-security coverage have real source-bound validation, even fully
    # self-consistent canonical/calendar/denominator bytes MUST NOT qualify.
    # Missing historical notices never proves NORMAL/non-suspended. A claimed
    # "verified" boolean inside the same untrusted JSON cannot lift this gate.
    failures.append("native_source_authority_unverified")

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
        "calendar_manifest_sha256": obj.get("calendar_manifest_sha256"),
        "denominator_manifest_sha256": obj.get("denominator_manifest_sha256"),
        "denominator": denominator_semantic_meta,
        "bindings": bindings,
    }

    if failures:
        return WARN, "历史ST/停牌逐日PIT证据未完整闭合：" + ",".join(failures), meta

    return PASS, (
        f"历史ST/停牌逐日PIT证据完整且字节哈希绑定；SSE/SZSE/BSE；"
        f"{obj.get('window_start')}..{obj.get('window_end')}"
    ), meta

def load_historical_st_pit_subset(root: Path, required_keys, expected_trade_date=None):
    """Load only required (date, code) daily PIT states after full evidence qualification.

    The claim/evidence bundle must first pass evaluate_historical_st_pit().  The
    canonical JSONL is then streamed and validated.  Missing requested keys,
    malformed rows, conflicting duplicate keys, or invalid state types fail
    closed instead of silently treating a stock as non-ST/tradable.
    """
    root = Path(root)
    required = set()
    for item in required_keys:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise RuntimeError(f"invalid historical PIT key: {item!r}")
        day = _parse_day(item[0])
        code = str(item[1] or "").strip()
        if day is None or not code:
            raise RuntimeError(f"invalid historical PIT key: {item!r}")
        required.add((day.isoformat(), code))

    if not required:
        raise RuntimeError("historical PIT subset request is empty")

    status, detail, meta = evaluate_historical_st_pit(root, expected_trade_date)
    if status != PASS:
        raise RuntimeError(f"historical ST/PIT evidence not qualified: {detail}")

    canonical_binding = (meta.get("bindings") or {}).get("canonical") or {}
    canonical_meta = canonical_binding.get("meta") or {}
    canonical_path_raw = canonical_meta.get("path")
    if not isinstance(canonical_path_raw, str) or not canonical_path_raw:
        raise RuntimeError("qualified canonical historical PIT path is unavailable")
    canonical_path = Path(canonical_path_raw)
    if not canonical_path.is_file():
        raise RuntimeError("qualified canonical historical PIT file disappeared")

    calendar_binding = (meta.get("bindings") or {}).get("calendar_manifest") or {}
    calendar_semantic_meta = calendar_binding.get("semantic_meta") or {}
    bound_market_dates = calendar_semantic_meta.get("market_dates") or {}
    if any(not isinstance(bound_market_dates.get(market), list) or not bound_market_dates.get(market)
           for market in REQUIRED_MARKETS):
        raise RuntimeError("qualified bound historical market calendar is unavailable")

    claim_path = root / "cache" / "historical_st_pit.json"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    window_start = _parse_day(claim.get("window_start"))
    window_end = _parse_day(claim.get("window_end"))
    if window_start is None or window_end is None:
        raise RuntimeError("qualified historical PIT window is invalid")

    found = {}
    scanned_rows = 0
    market_row_counts = {market: 0 for market in REQUIRED_MARKETS}
    market_dates = {market: set() for market in REQUIRED_MARKETS}
    with canonical_path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            scanned_rows += 1
            try:
                row = json.loads(text)
            except Exception as exc:
                raise RuntimeError(
                    f"malformed historical PIT JSONL at line {lineno}: {type(exc).__name__}"
                ) from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"historical PIT row is not an object at line {lineno}")

            day = _parse_day(row.get("date"))
            market = str(row.get("market") or "").strip().upper()
            code = str(row.get("code") or "").strip()
            st = row.get("st")
            suspended = row.get("suspended")
            if day is None or day < window_start or day > window_end:
                raise RuntimeError(f"historical PIT date outside qualified window at line {lineno}")
            if market not in REQUIRED_MARKETS:
                raise RuntimeError(f"historical PIT market invalid at line {lineno}: {market!r}")
            expected_market = _market_for_code(code)
            if expected_market is None:
                raise RuntimeError(f"historical PIT security code invalid at line {lineno}: {code!r}")
            if market != expected_market:
                raise RuntimeError(
                    f"historical PIT market/code mismatch at line {lineno}: "
                    f"{market}/{code} expected={expected_market}"
                )
            impossible = _impossible_market_code_day(market, code, day)
            if impossible:
                raise RuntimeError(
                    f"historical PIT impossible exchange/code day at line {lineno}: "
                    f"{impossible}:{market}/{code}/{day.isoformat()}"
                )
            if type(st) is not bool or type(suspended) is not bool:
                raise RuntimeError(f"historical PIT state types invalid at line {lineno}")
            market_row_counts[market] += 1
            market_dates[market].add(day.isoformat())

            key = (day.isoformat(), code)
            if key not in required:
                continue
            state = {"market": market, "st": st, "suspended": suspended}
            if key in found:
                raise RuntimeError(f"duplicate historical PIT state for requested key: {key}")
            found[key] = state

    missing = sorted(required - set(found))
    if missing:
        raise RuntimeError(
            f"historical PIT state missing for {len(missing)}/{len(required)} required keys; "
            f"sample={missing[:8]}"
        )

    return found, {
        "status": PASS,
        "required_key_count": len(required),
        "found_key_count": len(found),
        "scanned_rows": scanned_rows,
        "market_row_counts": market_row_counts,
        "canonical_market_dates": {market: sorted(days) for market, days in market_dates.items()},
        "market_dates": {market: list(bound_market_dates[market]) for market in REQUIRED_MARKETS},
        "canonical_sha256": meta.get("canonical_sha256"),
        "calendar_manifest_sha256": meta.get("calendar_manifest_sha256"),
        "window_start": claim.get("window_start"),
        "window_end": claim.get("window_end"),
        "expected_trade_date": str(expected_trade_date) if expected_trade_date else None,
    }

