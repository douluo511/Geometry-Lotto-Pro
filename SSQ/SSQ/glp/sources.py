from __future__ import annotations

import html as _html
import base64
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlsplit

import requests

from glp.net_client import NetClient
from glp.constants import (
    HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_HISTORY_URL,
    SHANGHAI_URL, SSQ_HISTORY_START_ISSUE,
)
from glp.domain import CanonicalDataset, Draw, SourceReceipt
from glp.util import canonical_json, sha256_bytes, sha256_json, utc_now


class SourceError(RuntimeError):
    pass


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeometryLottoProSSQ/8.5",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
}
TIMEOUT = (20, 30)
NET = NetClient(connect_timeout=20, read_timeout=30, max_attempts=3)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
PARSER_VERSION = "ssq-source-parser-v8.7-fail-closed+raw+calendar-v1"

# Freshness is based on the frozen public draw calendar, not an arbitrary age.
# Ministry of Finance-approved SSQ rules: draws every Tuesday/Thursday/Sunday.
# 2025/2026 national lottery-market closures are also Ministry of Finance
# announcements. Unknown calendar years fail closed until an updater ships the
# next official closure calendar.
SSQ_DRAW_WEEKDAYS = frozenset({1, 3, 6})  # Monday=0
CHINA_TZ = timezone(timedelta(hours=8))
FRESHNESS_POLICY_SOURCES = {
    "rule": "https://zhs.mof.gov.cn/zhengcefabu/201404/t20140421_1069579.htm",
    "2025": "https://zhs.mof.gov.cn/zhengcefabu/202412/t20241206_3949123.htm",
    "2026": "https://www.mof.gov.cn/gp/xxgkml/zhs/202512/t20251225_3980248.htm",
}
OFFICIAL_MARKET_CLOSURES = {
    2025: (
        (date(2025, 1, 27), date(2025, 2, 5)),
        (date(2025, 10, 1), date(2025, 10, 4)),
    ),
    2026: (
        (date(2026, 2, 14), date(2026, 2, 23)),
        (date(2026, 10, 1), date(2026, 10, 4)),
    ),
}
RawRecorder = Callable[[dict, bytes], None]


def _response_url(response, requested_url: str) -> str:
    """Accept only the requested official host, even after HTTPS redirects."""
    actual = str(getattr(response, "url", None) or requested_url)
    expected = urlsplit(requested_url)
    received = urlsplit(actual)
    if received.scheme.lower() != "https" or received.hostname != expected.hostname or received.username or received.password:
        raise SourceError(f"official source redirected outside its HTTPS host: {actual}")
    return actual


def _record_response(
    recorder: RawRecorder | None, source: str, response, raw: bytes, requested_url: str,
    request_params: dict[str, str] | None = None,
) -> None:
    actual_url = _response_url(response, requested_url)
    if recorder is None:
        return
    digest = sha256_bytes(raw)
    recorder({
        "source": source,
        "url": actual_url,
        "requested_url": requested_url,
        "request_params": request_params or {},
        "fetched_at": utc_now(),
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "parser_version": PARSER_VERSION,
        "sha256": digest,
        "bytes": len(raw),
        "artifact": f"raw_responses/{digest}.bin",
        "attempts": [dict(item) for item in getattr(response, "glp_attempts", ())],
    }, raw)


def _get_official(
    source: str, url: str, recorder: RawRecorder | None = None,
    *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None,
):
    try:
        response = NET.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.HTTPError as exc:
        # The final HTTP error body is evidence too; it is never a successful
        # draw and can only be retained if another official quorum succeeds.
        response = exc.response
        if response is not None:
            _record_response(recorder, source, response, bytes(response.content), url, params)
            if not getattr(exc, "glp_attempts", None):
                exc.glp_attempts = getattr(response, "glp_attempts", ())
        raise
    if int(response.status_code) != 200:
        _record_response(recorder, source, response, bytes(response.content), url, params)
        error = requests.HTTPError(f"official HTTPS GET returned HTTP {response.status_code}", response=response)
        error.glp_attempts = getattr(response, "glp_attempts", ())
        raise error
    return response


def _response_body(response, source: str, *, json_expected: bool, raw: bytes | None = None) -> bytes:
    raw = bytes(response.content) if raw is None else raw
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise SourceError(f"{source}: empty or oversized HTTP response")
    media_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
    allowed = {"application/json", "text/json"} if json_expected else {"text/html", "application/xhtml+xml"}
    if media_type not in allowed:
        raise SourceError(f"{source}: unexpected Content-Type {media_type!r}")
    return raw


def _validate_http_payload(response, raw: bytes, *, expected: str) -> dict:
    """Validate a fetched body and expose its response/attempt provenance."""
    if expected not in {"json", "html"}:
        raise ValueError("expected must be json or html")
    if int(getattr(response, "status_code", 0)) != 200:
        raise SourceError("official HTTP response was not successful")
    _response_body(response, "official source", json_expected=expected == "json", raw=raw)
    return {
        "http_status": 200,
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "attempts": [dict(item) for item in getattr(response, "glp_attempts", ())],
        "body_b64": base64.b64encode(raw).decode("ascii"),
        "fetched_at": utc_now(),
        "final_url": str(getattr(response, "url", "") or "") or None,
        "parser_version": PARSER_VERSION,
        "validation_result": "PASS",
    }


def _is_market_closed(day: date) -> bool:
    ranges = OFFICIAL_MARKET_CLOSURES.get(day.year)
    if ranges is None:
        raise SourceError(
            f"freshness calendar for {day.year} is not frozen from an official closure notice"
        )
    return any(start <= day <= end for start, end in ranges)


def _is_regular_ssq_draw_day(day: date) -> bool:
    return day.weekday() in SSQ_DRAW_WEEKDAYS and not _is_market_closed(day)


def _expected_latest_completed_draw_day(today: date) -> date:
    if today.year not in OFFICIAL_MARKET_CLOSURES:
        raise SourceError(
            f"freshness calendar for {today.year} is unavailable; updater required"
        )
    # Use strictly earlier calendar days. On a scheduled draw date the official
    # result may not have been published yet, so the prior completed draw remains
    # acceptable until the following China-local date.
    cursor = today - timedelta(days=1)
    for _ in range(40):
        if cursor.year not in OFFICIAL_MARKET_CLOSURES:
            raise SourceError(
                f"freshness calendar for {cursor.year} is unavailable across year boundary"
            )
        if _is_regular_ssq_draw_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise SourceError("could not resolve a completed SSQ draw date from the frozen calendar")


def _validate_history(
    draws: list[Draw], source: str, *, fresh: bool = True, today: date | None = None
) -> None:
    if not draws:
        raise SourceError(f"{source}: empty draw history")
    for draw in draws:
        draw.validate()
        if draw.draw_date[:4] != draw.issue[:4]:
            raise SourceError(f"{source}: issue/date year mismatch: {draw.issue}")
    if any(draws[i].issue >= draws[i + 1].issue or draws[i].draw_date >= draws[i + 1].draw_date
           for i in range(len(draws) - 1)):
        raise SourceError(f"{source}: duplicate, conflicting or nonmonotonic draw history")
    if fresh:
        latest = date.fromisoformat(draws[-1].draw_date)
        local_today = today or datetime.now(CHINA_TZ).date()
        if latest > local_today:
            raise SourceError(f"{source}: future latest draw {latest.isoformat()}")
        expected = _expected_latest_completed_draw_day(local_today)
        if latest < expected:
            raise SourceError(
                f"{source}: stale latest draw {latest.isoformat()}; "
                f"expected at least {expected.isoformat()} from frozen draw calendar"
            )


def _validate_freshness(
    draws: list[Draw], source: str, *, today: date | None = None
) -> dict:
    local_today = today or datetime.now(CHINA_TZ).date()
    _validate_history(draws, source, today=local_today)
    latest = date.fromisoformat(draws[-1].draw_date)
    expected = _expected_latest_completed_draw_day(local_today)
    return {
        "schema": "ssq-freshness-calendar-v1",
        "latest_date": draws[-1].draw_date,
        "china_local_date": local_today.isoformat(),
        "expected_latest_completed_draw_date": expected.isoformat(),
        "age_days": (local_today - latest).days,
        "draw_weekdays": ["Tuesday", "Thursday", "Sunday"],
        "policy_year": local_today.year,
        "policy_sources": {
            "rule": FRESHNESS_POLICY_SOURCES["rule"],
            "closure": FRESHNESS_POLICY_SOURCES[str(local_today.year)],
        },
    }


def _issue(value: object) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"\d{5}", s):
        s = "20" + s
    if not re.fullmatch(r"20\d{5}", s):
        raise SourceError(f"非法双色球期号: {value!r}")
    return s


def _date(value: object) -> str:
    s = str(value or "").strip()
    m = re.fullmatch(r"(20\d{2})[-/](\d{2})[-/](\d{2})(?:\s*\([^)]*\))?", s)
    if not m:
        raise SourceError(f"非法开奖日期: {value!r}")
    normalized = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise SourceError(f"invalid calendar date: {value!r}") from exc
    return normalized


def _balls(value: object, count: int) -> list[int]:
    if isinstance(value, (list, tuple)):
        tokens = list(value)
    else:
        s = str(value or "").strip()
        # Shanghai renders the six reds as a 12-digit compact cell.
        if count == 6 and re.fullmatch(r"\d{12}", s):
            tokens = [s[i:i + 2] for i in range(0, 12, 2)]
        else:
            tokens = re.split(r"[,，\s;|/-]+", s)
    if any(isinstance(token, bool) or not re.fullmatch(r"\d{1,2}", str(token)) for token in tokens):
        raise SourceError(f"invalid ball tokens: {tokens!r}")
    nums = [int(token) for token in tokens]
    if len(nums) != count:
        raise SourceError(f"球号数量错误: expected={count} got={nums!r}")
    return nums


def _draw(issue: object, day: object, reds: object, blue: object) -> Draw:
    red_values = sorted(_balls(reds, 6))
    blue_values = _balls(blue, 1)
    if len(set(red_values)) != 6 or not all(1 <= n <= 33 for n in red_values):
        raise SourceError(f"红球非法: {red_values!r}")
    if not (1 <= blue_values[0] <= 16):
        raise SourceError(f"蓝球非法: {blue_values!r}")
    obj = Draw(_issue(issue), _date(day), tuple(red_values), tuple(blue_values))
    validate = getattr(obj, "validate", None)
    if callable(validate):
        validate()
    return obj


def _same_draw(a: Draw, b: Draw, compare_date: bool = True) -> bool:
    return (
        a.issue == b.issue
        and tuple(a.front) == tuple(b.front)
        and tuple(a.back) == tuple(b.back)
        and (not compare_date or a.draw_date == b.draw_date)
    )


def _unique_draws(draws: Iterable[Draw], source: str) -> list[Draw]:
    unique: dict[str, Draw] = {}
    for draw in draws:
        prior = unique.get(draw.issue)
        if prior is not None:
            raise SourceError(f"{source}: duplicate issue {draw.issue}")
        unique[draw.issue] = draw
    ordered = sorted(unique.values(), key=lambda d: (d.draw_date, d.issue))
    _validate_history(ordered, source, fresh=False)
    return ordered


def _text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        decoded = None
        for enc in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                decoded = raw.decode(enc)
                break
            except UnicodeDecodeError:
                pass
        if decoded is None:
            raise SourceError("official HTML response has invalid text encoding")
        text = decoded
    else:
        text = raw
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _html_markup(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceError("official HTML response has invalid text encoding")


def _response_receipt(source: str, response, raw: bytes, draw_count: int, latest_issue: str, detail: str) -> SourceReceipt:
    return SourceReceipt(
        source=source,
        fetched_at=utc_now(),
        http_status=int(getattr(response, "status_code", 0) or 0),
        raw_sha256=sha256_bytes(raw),
        draw_count=int(draw_count),
        latest_issue=str(latest_issue),
        status="PASS",
        detail=detail,
    )


def _failed_receipt(source: str, detail: str) -> SourceReceipt:
    return SourceReceipt(
        source=source,
        fetched_at=utc_now(),
        http_status=0,
        raw_sha256="",
        draw_count=0,
        latest_issue="",
        status="FAIL",
        detail=detail,
    )


def _national_params(page_no: int, page_size: int = 100) -> dict[str, str]:
    return {
        "name": "ssq",
        "issueCount": "",
        "issueStart": "",
        "issueEnd": "",
        "dayStart": "",
        "dayEnd": "",
        "pageNo": str(page_no),
        "pageSize": str(page_size),
        "week": "",
        "systemType": "PC",
    }


def _national_manifest_entry(page_no: int, raw: bytes) -> dict:
    url = requests.Request("GET", NATIONAL_URL, params=_national_params(page_no)).prepare().url
    return {"page": page_no, "sha256": sha256_bytes(raw), "bytes": len(raw), "url": url}


def fetch_national_page(page_no: int, record_raw: RawRecorder | None = None) -> tuple[list[Draw], bytes, int]:
    response = _get_official("official_cwl_L0", NATIONAL_URL, record_raw,
                             params=_national_params(page_no), headers=HEADERS)
    response.raise_for_status()
    raw = bytes(response.content)
    _record_response(record_raw, "official_cwl_L0", response, raw, NATIONAL_URL, _national_params(page_no))
    _response_body(response, "CWL", json_expected=True, raw=raw)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("China Welfare Lottery returned invalid JSON bytes") from exc
    if not isinstance(payload, dict):
        raise SourceError("中国福彩网主源结构改变")
    state = payload.get("state")
    try:
        state_ok = int(state) == 0
    except Exception:
        state_ok = str(state).upper() in {"OK", "PASS", "SUCCESS"}
    rows = payload.get("result")
    if not state_ok or not isinstance(rows, list):
        raise SourceError("中国福彩网主源状态或结构改变")
    draws: list[Draw] = []
    seen_issues: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceError(f"national source row {index} is not an object")
        try:
            draw = _draw(row.get("code"), row.get("date"), row.get("red"), row.get("blue"))
        except (SourceError, TypeError, ValueError) as exc:
            raise SourceError(f"national source row {index} violates draw schema") from exc
        if draw.issue in seen_issues:
            raise SourceError(f"national source page repeats issue {draw.issue}")
        seen_issues.add(draw.issue)
        draws.append(draw)
    if not draws:
        raise SourceError("中国福彩网主源未解析到双色球记录")
    page_num = payload.get("pageNum")
    if page_num is None:
        total = payload.get("total")
        page_num = math.ceil(int(total) / 100) if total else 1
    try:
        pages = int(page_num)
        if not 1 <= pages <= 10000:
            raise ValueError("page count outside allowed range")
    except Exception as exc:
        raise SourceError("中国福彩网页数无效") from exc
    return draws, raw, pages


def fetch_national_history(
    progress: Callable[[str], None] | None = None, record_raw: RawRecorder | None = None,
) -> tuple[list[Draw], SourceReceipt, list[dict]]:
    first, raw_first, pages = fetch_national_page(1, record_raw)
    page_draws: dict[int, list[Draw]] = {1: first}
    raw_manifest = [_national_manifest_entry(1, raw_first)]
    if progress:
        progress(f"中国福彩网主源：1/{pages} 页")
    if pages > 1:
        max_workers = min(6, pages - 1)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fetch_national_page, p, record_raw): p for p in range(2, pages + 1)}
            for future in as_completed(futures):
                p = futures[future]
                draws, raw, reported_pages = future.result()
                if reported_pages != pages:
                    raise SourceError("中国福彩网分页数量在请求期间发生变化")
                page_draws[p] = draws
                raw_manifest.append(_national_manifest_entry(p, raw))
                if progress:
                    progress(f"中国福彩网主源：{len(page_draws)}/{pages} 页")
    unique: dict[str, Draw] = {}
    for p in sorted(page_draws):
        for d in page_draws[p]:
            prev = unique.get(d.issue)
            if prev is not None:
                raise SourceError(f"China Welfare Lottery returned duplicate issue {d.issue}")
            unique[d.issue] = d
    ordered = sorted(unique.values(), key=lambda d: (d.draw_date, d.issue))
    _validate_history(ordered, "CWL")
    if any(ordered[i].draw_date >= ordered[i + 1].draw_date for i in range(len(ordered) - 1)):
        raise SourceError("中国福彩网主源日期顺序异常")
    receipt = SourceReceipt(
        source="official_cwl_L0",
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256=sha256_json(sorted(raw_manifest, key=lambda x: x["page"])),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
        detail=f"中国福利彩票发行管理中心 API；pages={pages}",
    )
    return ordered, receipt, sorted(raw_manifest, key=lambda x: x["page"])


def parse_shanghai_history(raw: bytes | str) -> list[Draw]:
    text = _text(raw)
    draws: list[Draw] = []
    row_anchors = re.findall(r"20\d{5}\s+20\d{2}-\d{2}-\d{2}", text)
    # Current official page table: issue | date(day) | 12 compact red digits | 2 blue digits.
    compact = re.compile(r"(20\d{5})\s+(20\d{2}-\d{2}-\d{2})(?:\([^)]*\))?\s+(\d{12})\s+(\d{2})(?!\d)")
    for m in compact.finditer(text):
        draws.append(_draw(m.group(1), m.group(2), m.group(3), m.group(4)))
    if draws:
        if len(draws) != len(row_anchors):
            raise SourceError("Shanghai draw rows are only partially parsed")
        return _unique_draws(draws, "Shanghai")

    # Fallback for markup that separates each ball into its own element.
    issue_matches = list(re.finditer(r"20\d{5}", text))
    for idx, im in enumerate(issue_matches):
        end = issue_matches[idx + 1].start() if idx + 1 < len(issue_matches) else min(len(text), im.start() + 700)
        chunk = text[im.start():end]
        dm = re.search(r"20\d{2}-\d{2}-\d{2}", chunk)
        if not dm:
            continue
        tail = chunk[dm.end():dm.end() + 260]
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", tail)]
        if len(nums) < 7:
            raise SourceError(f"Shanghai issue {im.group(0)} has fewer than seven ball tokens")
        draws.append(_draw(im.group(0), dm.group(0), nums[:6], [nums[6]]))
    if not draws:
        raise SourceError("上海福彩双色球专页解析失败")
    if len(draws) != len(row_anchors):
        raise SourceError("Shanghai draw rows are only partially parsed")
    return _unique_draws(draws, "Shanghai")


def fetch_shanghai_history(record_raw: RawRecorder | None = None) -> tuple[list[Draw], SourceReceipt, bytes]:
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.swlc.net.cn/"
    response = _get_official("official_shanghai_L1", SHANGHAI_URL, record_raw, headers=headers)
    response.raise_for_status()
    raw = bytes(response.content)
    _record_response(record_raw, "official_shanghai_L1", response, raw, SHANGHAI_URL)
    _response_body(response, "Shanghai", json_expected=False, raw=raw)
    draws = parse_shanghai_history(raw)
    _validate_history(draws, "Shanghai")
    receipt = _response_receipt(
        "official_shanghai_L1", response, raw, len(draws), draws[-1].issue,
        "上海市福利彩票发行中心 双色球往期开奖专页",
    )
    return draws, receipt, raw



def _shanghai_full_chunk_specs(start_issue: str) -> list[dict[str, str]]:
    start = _issue(start_issue)
    start_year = int(start[:4])
    start_seq = int(start[-3:])
    current_year = datetime.now(timezone.utc).year
    if start_year < 2003 or start_year > current_year:
        raise SourceError(f"Shanghai full-history start year is invalid: {start}")
    specs: list[dict[str, str]] = []
    sequence = 0
    for year in range(start_year, current_year + 1):
        for low, high in ((1, 99), (100, 999)):
            if year == start_year:
                low = max(low, start_seq)
            if low > high:
                continue
            sequence += 1
            specs.append({
                "sequence": str(sequence),
                "view": "previous",
                "limit": "100",
                "start_issue": f"{year}{low:03d}",
                "end_issue": f"{year}{high:03d}",
            })
    return specs


def fetch_shanghai_full_history(
    start_issue: str = SSQ_HISTORY_START_ISSUE,
    record_raw: RawRecorder | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[Draw], SourceReceipt, list[dict]]:
    """Fetch complete SSQ history from Shanghai's official HTTPS issue-range form."""
    specs = _shanghai_full_chunk_specs(start_issue)
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.swlc.net.cn/"
    all_draws: list[Draw] = []
    manifest: list[dict] = []
    current_year = datetime.now(timezone.utc).year

    for spec in specs:
        params = {
            "view": spec["view"],
            "limit": spec["limit"],
            "start_issue": spec["start_issue"],
            "end_issue": spec["end_issue"],
        }
        source_operation_attempts: list[dict] = []
        response = None
        for source_attempt in range(1, 3):
            try:
                response = _get_official(
                    "official_shanghai_L1", SHANGHAI_HISTORY_URL, record_raw,
                    params=params, headers=headers,
                )
                source_operation_attempts.append({
                    "attempt": source_attempt,
                    "status": "PASS",
                    "error_type": None,
                    "transport_attempts": [
                        dict(item) for item in getattr(response, "glp_attempts", ())
                    ],
                })
                break
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                source_operation_attempts.append({
                    "attempt": source_attempt,
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "transport_attempts": [
                        dict(item) for item in getattr(exc, "glp_attempts", ())
                    ],
                })
                if source_attempt >= 2:
                    raise
                if progress:
                    progress(
                        "上海福彩全历史分块瞬态网络失败；"
                        f"{spec['start_issue']}..{spec['end_issue']} 进行一次有界重试"
                    )
        if response is None:
            raise RuntimeError("Shanghai bounded source retry produced no response")
        response.raise_for_status()
        raw = bytes(response.content)
        _record_response(
            record_raw, "official_shanghai_L1", response, raw,
            SHANGHAI_HISTORY_URL, params,
        )
        _response_body(response, "Shanghai full history", json_expected=False, raw=raw)

        actual = urlsplit(str(getattr(response, "url", "") or ""))
        actual_params = dict(parse_qsl(actual.query, keep_blank_values=True))
        if actual.scheme.lower() != "https" or actual.hostname != urlsplit(SHANGHAI_HISTORY_URL).hostname:
            raise SourceError("Shanghai full-history response left the official HTTPS host")
        if actual_params != params:
            raise SourceError(
                f"Shanghai full-history response query differs from request: "
                f"expected={params!r} actual={actual_params!r}"
            )

        try:
            chunk_draws = parse_shanghai_history(raw)
        except SourceError:
            year = int(spec["start_issue"][:4])
            if year != current_year or int(spec["start_issue"][-3:]) < 100:
                raise
            markup = _html_markup(raw)
            if "<tbody" not in markup.lower() or re.search(
                r"20\d{5}\s+20\d{2}-\d{2}-\d{2}", _text(raw)
            ):
                raise
            chunk_draws = []

        for draw in chunk_draws:
            if not (spec["start_issue"] <= draw.issue <= spec["end_issue"]):
                raise SourceError(
                    f"Shanghai returned issue outside requested range: {draw.issue} "
                    f"not in {spec['start_issue']}..{spec['end_issue']}"
                )
        if int(spec["start_issue"][:4]) < current_year and not chunk_draws:
            raise SourceError(
                f"Shanghai historical range is unexpectedly empty: "
                f"{spec['start_issue']}..{spec['end_issue']}"
            )

        all_draws.extend(chunk_draws)
        manifest.append({
            "sequence": int(spec["sequence"]),
            "start_issue": spec["start_issue"],
            "end_issue": spec["end_issue"],
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
            "url": str(response.url),
            "draw_count": len(chunk_draws),
            "first_issue": chunk_draws[0].issue if chunk_draws else None,
            "last_issue": chunk_draws[-1].issue if chunk_draws else None,
            "source_operation_attempts": source_operation_attempts,
        })
        if progress:
            progress(f"上海福彩全历史：{len(manifest)}/{len(specs)} 分块")

    ordered = _unique_draws(all_draws, "Shanghai full history")
    if not ordered or ordered[0].issue != _issue(start_issue):
        raise SourceError(
            f"Shanghai full history does not start at required issue {start_issue}: "
            f"{ordered[0].issue if ordered else 'EMPTY'}"
        )
    _validate_history(ordered, "Shanghai full history")

    by_year: dict[str, list[int]] = {}
    for draw in ordered:
        by_year.setdefault(draw.issue[:4], []).append(int(draw.issue[-3:]))
    for year, suffixes in by_year.items():
        first = int(start_issue[-3:]) if year == start_issue[:4] else 1
        if suffixes != list(range(first, max(suffixes) + 1)):
            raise SourceError(f"Shanghai full history has issue gaps/duplicates in {year}")

    receipt = SourceReceipt(
        source="official_shanghai_L1",
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256=sha256_json(manifest),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
        detail=(
            f"上海市福利彩票发行中心 HTTPS 按期号全历史；chunks={len(manifest)}；"
            f"source_retries={sum(max(0, len(row.get('source_operation_attempts', [])) - 1) for row in manifest)}"
        ),
    )
    return ordered, receipt, manifest

def _hebei_home_snapshot(raw: bytes | str) -> dict:
    # Parse only the draw panel. News headlines contain unrelated prize amounts.
    markup = _html_markup(raw)
    panels = re.findall(r'<li\b[^>]*class=["\'][^"\']*kj-info-item[^"\']*["\'][^>]*>(.*?)</li>', markup, re.I | re.S)
    matched = [panel for panel in panels if "logo_ssq.png" in panel]
    if len(matched) != 1:
        raise SourceError("河北福彩双色球开奖区块缺失或重复")
    panel = matched[0]
    issue = re.search(r"第\s*(20\d{5})\s*期", _text(panel))
    block = re.search(r'<div\b[^>]*class=["\'][^"\']*cirle-number[^"\']*["\'][^>]*>(.*?)</div>', panel, re.I | re.S)
    if issue is None or block is None:
        raise SourceError("河北福彩双色球期号或号码容器缺失")
    spans = re.findall(r"<span\b([^>]*)>\s*(\d{1,2})\s*</span>", block.group(1), re.I | re.S)
    if len(spans) != 7 or "blue-num" not in spans[-1][0] or any("blue-num" in a for a, _ in spans[:6]):
        raise SourceError("河北福彩双色球红蓝球结构非法")
    reds = tuple(sorted(int(v) for _, v in spans[:6]))
    blue = int(spans[-1][1])
    if len(set(reds)) != 6 or not all(1 <= n <= 33 for n in reds) or not 1 <= blue <= 16:
        raise SourceError("河北福彩双色球号码非法")
    return {"issue": _issue(issue.group(1)), "front": reds, "back": (blue,)}


def _hebei_announce_snapshot(raw: bytes | str) -> dict:
    """Parse date + 6+1 balls from Hebei's official SSQ announcement page."""
    text = _text(raw)
    dm = re.search(r"开奖日期\s*[:：]?\s*(20\d{2}-\d{2}-\d{2})", text)
    if not dm:
        raise SourceError("河北福彩开奖公告未找到开奖日期")
    marker = re.search(r"开奖号码\s*[:：]?", text)
    if not marker:
        raise SourceError("河北福彩开奖公告未找到开奖号码")
    tail = text[marker.end():marker.end() + 240]
    nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", tail)]
    if len(nums) >= 7:
        reds, blue = nums[:6], nums[6]
        if len(set(reds)) == 6 and all(1 <= n <= 33 for n in reds) and 1 <= blue <= 16:
            return {
                "draw_date": _date(dm.group(1)),
                "front": tuple(sorted(reds)),
                "back": (blue,),
            }
    raise SourceError("河北福彩开奖公告未解析到6+1开奖号码")


def parse_hebei_latest(home_raw: bytes | str, announce_raw: bytes | str | None = None) -> Draw:
    """Return a fully dated Hebei official draw after internal endpoint consensus.

    v8.3 deliberately requires two server-rendered pages from the same official
    centre: homepage anchors the issue; announcement anchors the date.  Their
    ball sets must agree before the source is considered usable.
    """
    if announce_raw is None:
        raise SourceError("河北福彩 v8.3 需要首页+开奖公告双页面共识")
    home = _hebei_home_snapshot(home_raw)
    ann = _hebei_announce_snapshot(announce_raw)
    if home["front"] != ann["front"] or home["back"] != ann["back"]:
        raise SourceError("河北福彩首页与开奖公告号码冲突，拒绝该来源")
    return _draw(home["issue"], ann["draw_date"], list(home["front"]), list(home["back"]))


def fetch_hebei_latest(record_raw: RawRecorder | None = None) -> tuple[Draw, SourceReceipt, dict]:
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.yzfcw.com/"
    home_response = _get_official("official_hebei_L2", HEBEI_URL, record_raw, headers=headers)
    home_response.raise_for_status()
    home_raw = bytes(home_response.content)
    _record_response(record_raw, "official_hebei_L2", home_response, home_raw, HEBEI_URL)
    announce_response = _get_official("official_hebei_L2", HEBEI_ANNOUNCE_URL, record_raw, headers=headers)
    announce_response.raise_for_status()
    announce_raw = bytes(announce_response.content)
    _record_response(record_raw, "official_hebei_L2", announce_response, announce_raw, HEBEI_ANNOUNCE_URL)
    _response_body(home_response, "Hebei homepage", json_expected=False, raw=home_raw)
    _response_body(announce_response, "Hebei announcement", json_expected=False, raw=announce_raw)
    draw = parse_hebei_latest(home_raw, announce_raw)
    _validate_history([draw], "Hebei")
    receipt = SourceReceipt(
        source="official_hebei_L2",
        fetched_at=utc_now(),
        http_status=min(int(home_response.status_code), int(announce_response.status_code)),
        raw_sha256=sha256_json({
            "home": sha256_bytes(home_raw),
            "announce": sha256_bytes(announce_raw),
        }),
        draw_count=1,
        latest_issue=draw.issue,
        status="PASS",
        detail="河北省福利彩票发行管理中心：首页期号/号码 + 双色球开奖公告日期/号码，双页面内部共识",
    )
    return draw, receipt, {"home": home_raw, "announce": announce_raw}


def _overlap_verify(a: Iterable[Draw], b: Iterable[Draw], label: str) -> int:
    amap = {d.issue: d for d in a}
    bmap = {d.issue: d for d in b}
    common = sorted(set(amap) & set(bmap))
    for issue in common:
        if not _same_draw(amap[issue], bmap[issue]):
            raise SourceError(f"官方来源冲突，拒绝更新: {label} issue={issue}")
    return len(common)


def _merge_trusted_baseline(baseline_draws: Iterable[Draw], recent: list[Draw]) -> tuple[list[Draw], int]:
    baseline = list(baseline_draws)
    if not baseline:
        raise SourceError("国家主源不可用且没有可信本地/内置基线")
    overlap = _overlap_verify(baseline, recent, "trusted-seed-vs-shanghai")
    baseline_issues = {d.issue for d in baseline}
    if baseline[-1].issue not in {d.issue for d in recent}:
        raise SourceError("国家主源不可用，且上海100期窗口未覆盖本地最新期；拒绝不完整补洞")
    merged = list(baseline)
    last_date = baseline[-1].draw_date
    for d in recent:
        if d.issue in baseline_issues:
            continue
        if d.draw_date <= last_date:
            raise SourceError(f"省级增量数据时间倒序: {d.issue}")
        merged.append(d)
        baseline_issues.add(d.issue)
        last_date = d.draw_date
    return merged, overlap


def build_canonical(
    progress: Callable[[str], None] | None = None,
    baseline_draws: Iterable[Draw] | None = None,
    baseline_raw_verified: bool = False,
    baseline_evidence: dict | None = None,
    failure_sink: Callable[[dict], object] | None = None,
) -> tuple[CanonicalDataset, dict]:
    capture: dict = {
        "started_at": utc_now(),
        "receipts": [],
        "errors": {},
        "attempt_ledger": {},
        "raw_responses": [],
        "raw_payloads": {},
    }
    try:
        return _build_canonical_impl(
            progress, baseline_draws, baseline_raw_verified, baseline_evidence, capture,
        )
    except Exception as exc:
        failure = {
            "schema": "official-network-failure-v1",
            "game": "SSQ",
            "status": "FAIL",
            "crosscheck_status": "FAIL",
            "started_at": capture["started_at"],
            "failed_at": utc_now(),
            "reason": f"{type(exc).__name__}: {exc}",
            "source_receipts": [asdict(receipt) for receipt in capture["receipts"]],
            "source_errors": dict(capture["errors"]),
            "attempt_ledger": dict(capture["attempt_ledger"]),
            "raw_responses": list(capture["raw_responses"]),
            "raw_response_status": "PENDING_PERSISTENCE",
            "_raw_response_payloads": dict(capture["raw_payloads"]),
        }
        if failure_sink is not None:
            try:
                path = failure_sink(failure)
                setattr(exc, "failure_evidence_path", str(path))
            except Exception as sink_exc:
                raise SourceError(
                    f"source validation failed ({type(exc).__name__}: {exc}); "
                    f"failure evidence persistence also failed ({type(sink_exc).__name__}: {sink_exc})"
                ) from exc
        raise


def _build_canonical_impl(
    progress: Callable[[str], None] | None,
    baseline_draws: Iterable[Draw] | None,
    baseline_raw_verified: bool,
    baseline_evidence: dict | None,
    capture: dict,
) -> tuple[CanonicalDataset, dict]:
    receipts: list[SourceReceipt] = capture["receipts"]
    errors: dict[str, str] = capture["errors"]
    attempt_ledger: dict[str, list[dict]] = capture["attempt_ledger"]
    national_draws: list[Draw] | None = None
    shanghai_draws: list[Draw] | None = None
    hebei_draw: Draw | None = None
    raw_manifest: list[dict] = []
    raw_responses: list[dict] = capture["raw_responses"]
    raw_payloads: dict[str, bytes] = capture["raw_payloads"]
    raw_lock = Lock()

    def record_raw(metadata: dict, raw: bytes) -> None:
        digest = metadata["sha256"]
        with raw_lock:
            existing = raw_payloads.get(digest)
            if existing is not None and existing != raw:
                raise SourceError("raw response digest collision")
            raw_payloads[digest] = raw
            raw_responses.append(metadata)

    if progress:
        progress("真实官方网络：连接中国福彩网主源…")
    try:
        national_draws, receipt, raw_manifest = fetch_national_history(progress, record_raw)
        receipts.append(receipt)
    except Exception as exc:
        errors["national"] = f"{type(exc).__name__}: {exc}"
        attempt_ledger["national"] = [dict(item) for item in getattr(exc, "glp_attempts", ())]
        receipts.append(_failed_receipt("official_cwl_L0", errors["national"]))

    baseline = list(baseline_draws or ())
    prior_raw_fallback = (
        national_draws is None
        and baseline_raw_verified
        and isinstance(baseline_evidence, dict)
        and baseline_evidence.get("schema") == "official-source-evidence-v8.5"
        and baseline_evidence.get("raw_response_status") == "PASS"
        and baseline_evidence.get("canonical_hash") == sha256_json([d.to_dict() for d in baseline])
        and any(
            r.get("source") == "official_cwl_L0" and r.get("status") == "PASS"
            for r in baseline_evidence.get("source_receipts", []) if isinstance(r, dict)
        )
    )
    shanghai_raw_manifest: list[dict] = []
    if progress:
        progress(
            "真实官方网络：连接上海福彩 HTTPS 全历史…"
            if national_draws is None and not prior_raw_fallback
            else "真实官方网络：连接上海福彩双色球专页…"
        )
    try:
        if national_draws is None and not prior_raw_fallback:
            shanghai_draws, receipt, shanghai_raw_manifest = fetch_shanghai_full_history(
                SSQ_HISTORY_START_ISSUE, record_raw, progress,
            )
        else:
            shanghai_draws, receipt, _ = fetch_shanghai_history(record_raw)
        receipts.append(receipt)
    except Exception as exc:
        errors["shanghai"] = f"{type(exc).__name__}: {exc}"
        attempt_ledger["shanghai"] = [dict(item) for item in getattr(exc, "glp_attempts", ())]
        receipts.append(_failed_receipt("official_shanghai_L1", errors["shanghai"]))

    if progress:
        progress("真实官方网络：连接河北福彩双色球专页…")
    try:
        hebei_draw, receipt, _ = fetch_hebei_latest(record_raw)
        receipts.append(receipt)
    except Exception as exc:
        errors["hebei"] = f"{type(exc).__name__}: {exc}"
        attempt_ledger["hebei"] = [dict(item) for item in getattr(exc, "glp_attempts", ())]
        receipts.append(_failed_receipt("official_hebei_L2", errors["hebei"]))

    crosscheck_count = 0
    verification = ""
    canonical_draws: list[Draw]

    if national_draws is not None:
        validators = 0
        if shanghai_draws is not None:
            overlap = _overlap_verify(national_draws, shanghai_draws, "CWL-vs-Shanghai")
            if overlap <= 0:
                raise SourceError("中国福彩与上海福彩没有可交叉验证的共同期次")
            latest = national_draws[-1]
            sh_latest = shanghai_draws[-1]
            if not _same_draw(latest, sh_latest):
                raise SourceError(
                    f"官方来源最新期冲突或省级缓存落后，拒绝更新: CWL={latest.issue} Shanghai={sh_latest.issue}"
                )
            crosscheck_count += overlap
            validators += 1
        if hebei_draw is not None:
            latest = national_draws[-1]
            if not _same_draw(latest, hebei_draw):
                raise SourceError(f"官方来源最新期冲突，拒绝更新: CWL={latest.issue} Hebei={hebei_draw.issue}")
            crosscheck_count += 1
            validators += 1
        if validators < 1:
            raise SourceError("只有中国福彩单源可用；不足双官方源共识，拒绝 PASS")
        canonical_draws = national_draws
        verification = f"CWL_L0_PLUS_{validators}_PROVINCIAL_VALIDATOR"
    else:
        if shanghai_draws is None or hebei_draw is None:
            raise SourceError("中国福彩主源不可用时，上海+河北双官方补偿链必须同时可用；诊断=" + json.dumps(errors, ensure_ascii=False))
        if not _same_draw(shanghai_draws[-1], hebei_draw):
            raise SourceError(
                f"省级双官方源最新期冲突，拒绝更新: Shanghai={shanghai_draws[-1].issue} Hebei={hebei_draw.issue}"
            )
        if prior_raw_fallback:
            canonical_draws, overlap = _merge_trusted_baseline(baseline, shanghai_draws)
            crosscheck_count = overlap + 1
            verification = "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS"
        else:
            if not shanghai_raw_manifest:
                raise SourceError("CWL 不可用且上海全历史 raw manifest 缺失")
            if shanghai_draws[0].issue != SSQ_HISTORY_START_ISSUE:
                raise SourceError("上海全历史起点不符合冻结的 SSQ 历史范围")
            overlap = 0
            if baseline:
                if len(shanghai_draws) < len(baseline):
                    raise SourceError("上海全历史短于本地 baseline，拒绝替换")
                overlap = _overlap_verify(baseline, shanghai_draws, "baseline-vs-Shanghai-full")
                if overlap != len(baseline):
                    raise SourceError("上海全历史未完整覆盖本地 baseline")
                if [d.issue for d in shanghai_draws[:len(baseline)]] != [d.issue for d in baseline]:
                    raise SourceError("上海全历史不能证明 baseline 是其严格前缀")
            canonical_draws = shanghai_draws
            crosscheck_count = 1
            verification = "SHANGHAI_FULL_L1_PLUS_HEBEI_CURRENT"

    if not canonical_draws:
        raise SourceError("Canonical Dataset 为空")
    for i in range(len(canonical_draws) - 1):
        if canonical_draws[i].draw_date >= canonical_draws[i + 1].draw_date:
            raise SourceError("Canonical Dataset 日期非严格递增")

    _validate_history(canonical_draws, "canonical")
    freshness = _validate_freshness(canonical_draws, "canonical")
    draw_dicts = [d.to_dict() for d in canonical_draws]
    canonical_hash = sha256_json(draw_dicts)
    dataset = CanonicalDataset(
        draws=canonical_draws,
        canonical_hash=canonical_hash,
        receipts=receipts,
        crosscheck_count=int(crosscheck_count),
        crosscheck_status="PASS",
    )
    evidence = {
        "schema": "official-source-evidence-v8.5",
        "parser_version": PARSER_VERSION,
        "game": "SSQ",
        "fetched_at": utc_now(),
        "freshness": freshness,
        "canonical_hash": canonical_hash,
        "draw_count": len(canonical_draws),
        "latest": canonical_draws[-1].to_dict(),
        "crosscheck_count": int(crosscheck_count),
        "crosscheck_status": "PASS",
        "verification": verification,
        "source_receipts": [asdict(r) for r in receipts],
        "source_errors": errors,
        "national_raw_manifest": raw_manifest,
        "shanghai_raw_manifest": shanghai_raw_manifest or None,
        "raw_responses": sorted(raw_responses, key=lambda r: (r["source"], r["url"], r["fetched_at"])),
        "raw_response_status": "PENDING_PERSISTENCE",
        "_raw_response_payloads": raw_payloads,
        "baseline_lineage": baseline_evidence if verification == "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS" else None,
        "baseline_canonical_hash": (
            baseline_evidence["canonical_hash"]
            if verification == "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS"
            else sha256_json([d.to_dict() for d in baseline])
            if verification == "SHANGHAI_FULL_L1_PLUS_HEBEI_CURRENT" and baseline
            else None
        ),
        "baseline_draw_count": (
            len(baseline)
            if verification in {
                "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS",
                "SHANGHAI_FULL_L1_PLUS_HEBEI_CURRENT",
            }
            else None
        ),
        "baseline_overlap_count": (
            overlap if verification == "SHANGHAI_FULL_L1_PLUS_HEBEI_CURRENT" else None
        ),
        "canonical_payload_sha256": sha256_bytes(canonical_json(draw_dicts).encode("utf-8")),
    }
    return dataset, evidence
