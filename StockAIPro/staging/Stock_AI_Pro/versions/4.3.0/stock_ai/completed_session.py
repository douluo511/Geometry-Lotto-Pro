from __future__ import annotations
from datetime import date, datetime, time as clock_time, timedelta, timezone
import hashlib, json, re
import numpy as np
import pandas as pd

CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
DAILY_BAR_COMPLETION_MARGIN = clock_time(15, 30)
# Each exchange's 2026 notice was checked independently. No other year or
# exchange inherits this schedule. This is a completion oracle, not historical PIT.
CALENDARS = {
    "SSE": {"year": 2026, "published": "2025-12-22",
        "url": "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml",
        "closed": [("2026-01-01","2026-01-03"),("2026-02-15","2026-02-23"),("2026-04-04","2026-04-06"),("2026-05-01","2026-05-05"),("2026-06-19","2026-06-21"),("2026-09-25","2026-09-27"),("2026-10-01","2026-10-07")]},
    "SZSE": {"year": 2026, "published": "2025-12-22",
        "url": "https://www.szse.cn/disclosure/notice/t20251222_618087.html",
        "closed": [("2026-01-01","2026-01-03"),("2026-02-15","2026-02-23"),("2026-04-04","2026-04-06"),("2026-05-01","2026-05-05"),("2026-06-19","2026-06-21"),("2026-09-25","2026-09-27"),("2026-10-01","2026-10-07")]},
    "BSE": {"year": 2026, "published": "2025-12-22",
        "url": "https://www.bse.cn/important_news/200027428.html",
        "closed": [("2026-01-01","2026-01-03"),("2026-02-15","2026-02-23"),("2026-04-04","2026-04-06"),("2026-05-01","2026-05-05"),("2026-06-19","2026-06-21"),("2026-09-25","2026-09-27"),("2026-10-01","2026-10-07")]},
}

class CompletedSessionUnavailable(RuntimeError):
    pass

def market_for_code(code: str) -> str:
    text = str(code)
    if re.fullmatch(r"[0-9]{6}", text) is None:
        raise CompletedSessionUnavailable("security identity must be six ASCII digits")
    if text.startswith(("920", "4", "8")):
        return "BSE"
    if text.startswith("6"):
        return "SSE"
    if text.startswith(("0", "3")):
        return "SZSE"
    raise CompletedSessionUnavailable("no frozen exchange completion calendar for this security")

def is_session(day: date, market: str) -> bool:
    schedule = CALENDARS.get(market)
    if not schedule or day.year != schedule["year"]:
        raise CompletedSessionUnavailable("no authoritative completion calendar for exchange/year")
    return day.weekday() < 5 and not any(
        date.fromisoformat(start) <= day <= date.fromisoformat(end)
        for start, end in schedule["closed"])

def completed_session_context(now: datetime | None = None, markets=("SSE", "SZSE", "BSE")) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise CompletedSessionUnavailable("completion time must have an explicit timezone")
    local = current.astimezone(CHINA_STANDARD_TIME)
    requested = list(dict.fromkeys(markets))
    if not requested:
        raise CompletedSessionUnavailable("at least one exchange calendar is required")
    completed = {}
    for market in requested:
        probe = local.date()
        today_is_session = is_session(probe, market)
        if today_is_session and local.time() < DAILY_BAR_COMPLETION_MARGIN:
            probe -= timedelta(days=1)
        for _ in range(40):
            if is_session(probe, market):
                completed[market] = probe.isoformat()
                break
            probe -= timedelta(days=1)
        else:
            raise CompletedSessionUnavailable("could not resolve a completed exchange session")
    if len(set(completed.values())) != 1:
        raise CompletedSessionUnavailable("exchange completed-session dates disagree")
    schedules = {market: CALENDARS[market] for market in requested}
    digest = hashlib.sha256(json.dumps(schedules,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"status": "PASS", "expected_completed_session": next(iter(completed.values())),
        "exchange_completed_sessions": completed, "calendar_sources": schedules,
        "calendar_sha256": digest, "china_time": local.isoformat(),
        "completion_margin_local": DAILY_BAR_COMPLETION_MARGIN.isoformat(),
        "scope": "frozen 2026 daily completion only; no historical PIT qualification"}

def validated_daily_dates(values) -> pd.Series:
    series = pd.Series(values)
    for value in series:
        if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("daily source dates must be canonical YYYY-MM-DD")
    dates = pd.to_datetime(series, errors="coerce")
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("daily source dates must be valid and unique")
    if getattr(dates.dt, "tz", None) is not None or not dates.eq(dates.dt.normalize()).all():
        raise ValueError("daily source dates must represent whole sessions")
    return dates

def select_completed_daily_frame(frame: pd.DataFrame, *, market: str, now=None,
                                 require_latest=True, date_column="date"):
    if frame is None or frame.empty or date_column not in frame:
        raise ValueError("daily source frame/date is missing")
    context = completed_session_context(now, markets=(market,))
    dates = validated_daily_dates(frame[date_column])
    values = frame.copy()
    # Even an excluded unfinished bar must not hide malformed source numbers.
    for column in ("open", "close", "high", "low", "volume", "amount", "turnover_rate"):
        if column in values:
            numbers = pd.to_numeric(values[column],errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(numbers).all() or (numbers < 0).any():
                raise ValueError("daily source numeric fields must be finite and nonnegative")
            if column in ("open","close","high","low") and (numbers <= 0).any():
                raise ValueError("daily source prices must be positive")
    for day in dates.dt.date:
        if day.weekday() >= 5 or (day.year == CALENDARS[market]["year"] and not is_session(day, market)):
            raise ValueError("daily source contains a non-trading session date")
    expected = pd.Timestamp(context["expected_completed_session"])
    local = datetime.fromisoformat(context["china_time"])
    today = pd.Timestamp(local.date())
    may_exclude_today = is_session(local.date(), market) and local.time() < DAILY_BAR_COMPLETION_MARGIN
    unfinished = dates.eq(today) & (dates > expected) & may_exclude_today
    if ((dates > expected) & ~unfinished).any():
        raise ValueError("daily source has future/closed date outside today's unfinished session")
    selected = values.loc[~unfinished].copy()
    selected[date_column] = dates.loc[~unfinished]
    selected = selected.sort_values(date_column).reset_index(drop=True)
    if selected.empty:
        raise ValueError("no completed daily bars remain")
    latest = selected[date_column].max().strftime("%Y-%m-%d")
    if require_latest and latest != context["expected_completed_session"]:
        raise ValueError("daily source is missing the exact latest completed session")
    detail = {**context, "raw_rows": int(len(values)), "completed_rows": int(len(selected)),
        "discarded_unfinished_dates": dates.loc[unfinished].dt.strftime("%Y-%m-%d").tolist(),
        "actual_latest_date": latest, "latest_equals_oracle": latest == context["expected_completed_session"],
        "require_latest": bool(require_latest), "raw_payload_receipts_unchanged": True}
    return selected, detail

def require_exact_completed_asof(actual, expected):
    for name, value in (("actual",actual),("expected",expected)):
        if not isinstance(value,str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",value) is None:
            raise CompletedSessionUnavailable(name + " completed-session identity is missing/invalid; NO_TRADE")
        try:
            valid = date.fromisoformat(value).isoformat() == value
        except ValueError:
            valid = False
        if not valid:
            raise CompletedSessionUnavailable(name + " completed-session identity is invalid; NO_TRADE")
    if actual != expected:
        raise CompletedSessionUnavailable("行情过期或完成交易日不匹配：actual=" + actual + " expected=" + expected + "; NO_TRADE")
