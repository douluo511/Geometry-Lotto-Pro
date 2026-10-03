from __future__ import annotations

import hashlib
import html
import json
import re
import requests
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .domain import Draw
from .net_client import NetClient


NATIONAL_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
NATIONAL_LANDING_URL = "https://www.cwl.gov.cn/ygkj/wqkjgg/kl8/"
SHANGHAI_HISTORY_URL = "https://www.swlc.net.cn/lottery/kl8.html"
HAPPY8_HISTORY_START_ISSUE = "2020001"
HAPPY8_HISTORY_START_DATE = "2020-10-28"
JIANGSU_URL = "https://www.jslottery.com/"
JIANGSU_HISTORY_URL = "https://www.jslottery.com/winning_history_a"
FUZHOU_HISTORY_URL = "https://www.jxfzfc.cn/lottery.php"
FUZHOU_AUTHORITY_MARKER = "抚州市慈善和福利彩票事业发展中心"
HAPPY8_MARKET_CLOSURES: dict[int, tuple[tuple[str, str], ...]] = {
    2020: (),
    2021: (("2021-02-09", "2021-02-18"), ("2021-10-01", "2021-10-04")),
    2022: (("2022-01-29", "2022-02-07"), ("2022-10-01", "2022-10-04")),
    2023: (("2023-01-19", "2023-01-28"), ("2023-10-01", "2023-10-04")),
    2024: (("2024-02-08", "2024-02-17"), ("2024-10-01", "2024-10-04")),
    2025: (("2025-01-27", "2025-02-05"), ("2025-10-01", "2025-10-04")),
    2026: (("2026-02-14", "2026-02-23"), ("2026-10-01", "2026-10-04")),
}
HAPPY8_MARKET_CALENDAR_SOURCES: dict[int, str] = {
    2020: "https://zhs.mof.gov.cn/zhengcefabu/201912/t20191216_3442598.htm",
    2021: "https://m.mof.gov.cn/czxw/202012/t20201215_3634843.htm",
    2022: "https://www.mof.gov.cn/gp/xxgkml/zhs/202112/t20211216_3775504.htm",
    2023: "https://zhs.mof.gov.cn/zhengcefabu/202212/t20221227_3860392.htm",
    2024: "https://www.mof.gov.cn/jrttts/202312/t20231204_3919516.htm",
    2025: "https://zhs.mof.gov.cn/zhengcefabu/202412/t20241206_3949123.htm",
    2026: "https://zhs.mof.gov.cn/zhengcefabu/202512/t20251225_3980205.htm",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8Evidence/0.3",
    "Accept": "application/json,text/html;q=0.9,application/xhtml+xml;q=0.8,*/*;q=0.5",
    "Referer": "https://www.swlc.net.cn/",
}
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)


@dataclass(frozen=True)
class SourceReceipt:
    source: str
    url: str
    http_status: int
    fetched_at: str
    raw_sha256: str
    bytes: int
    draw_count: int
    latest_issue: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_html_response(response) -> bytes:
    status = int(response.status_code)
    if status != 200:
        raise RuntimeError(f"official source HTTP status {status}")
    raw = bytes(response.content)
    ctype = str(response.headers.get("Content-Type", "")).lower()
    if "html" not in ctype and "text" not in ctype:
        raise RuntimeError(f"official source content type is not HTML: {ctype!r}")
    if len(raw) < 1000:
        raise RuntimeError(f"official source response too small: {len(raw)} bytes")
    return raw


def _plain(text: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", value).strip()


def _numbers_from_compact(value: str) -> tuple[int, ...]:
    digits = re.sub(r"\s+", "", value)
    if len(digits) != 40 or not digits.isdigit():
        raise ValueError("Happy8 compact result must contain exactly forty digits")
    return tuple(int(digits[i:i + 2]) for i in range(0, 40, 2))



def _national_params(page_no: int, page_size: int = 100) -> dict[str, str]:
    return {
        "name": "kl8",
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


def _validate_national_response(response) -> bytes:
    raw = bytes(response.content)
    status = int(response.status_code)
    if status != 200:
        attempts = list(getattr(response, "happy8_attempts", ()))
        raise RuntimeError(
            f"CWL Happy8 HTTP {status}; bytes={len(raw)} sha256={hashlib.sha256(raw).hexdigest()} "
            f"attempts={attempts!r}"
        )
    ctype = str(response.headers.get("Content-Type", "")).lower()
    if "json" not in ctype:
        raise RuntimeError(f"CWL Happy8 content type is not JSON: {ctype!r}")
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise RuntimeError(f"CWL Happy8 invalid response size: {len(raw)}")
    return raw


def _parse_national_payload(raw: bytes) -> tuple[list[Draw], int | None, int | None]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CWL Happy8 returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("CWL Happy8 payload is not an object")
    state = payload.get("state")
    try:
        state_ok = int(state) == 0
    except Exception:
        state_ok = str(state).upper() in {"OK", "PASS", "SUCCESS"}
    rows = payload.get("result")
    if not state_ok or not isinstance(rows, list):
        raise RuntimeError(f"CWL Happy8 response state/schema changed: state={state!r}")
    draws: list[Draw] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError(f"CWL Happy8 row {index} is not an object")
        issue = row.get("code") or row.get("issue") or row.get("lotteryDrawNum")
        day = row.get("date") or row.get("lotteryDrawTime")
        balls = row.get("red") or row.get("result") or row.get("lotteryDrawResult")
        issue_text = str(issue or "").strip()
        day_text = str(day or "").strip()[:10]
        nums = [int(x) for x in re.findall(r"\d{1,2}", str(balls or ""))]
        try:
            draw = Draw.from_values(issue_text, day_text, nums)
        except Exception as exc:
            raise RuntimeError(f"CWL Happy8 row {index} violates draw schema") from exc
        if draw.issue in seen:
            raise RuntimeError(f"CWL Happy8 page repeats issue {draw.issue}")
        seen.add(draw.issue)
        draws.append(draw)
    page_num = payload.get("pageNum")
    total = payload.get("total")
    try:
        pages = int(page_num) if page_num not in (None, "") else None
    except Exception as exc:
        raise RuntimeError(f"CWL Happy8 invalid pageNum: {page_num!r}") from exc
    try:
        total_count = int(total) if total not in (None, "") else None
    except Exception as exc:
        raise RuntimeError(f"CWL Happy8 invalid total: {total!r}") from exc
    return draws, pages, total_count


def fetch_national_full_history() -> tuple[list[Draw], SourceReceipt, dict[str, bytes], list[dict[str, Any]]]:
    page_size = 100
    page = 1
    reported_pages: int | None = None
    all_draws: list[Draw] = []
    raw_sources: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []

    # CWL currently protects the JSON endpoint with same-site session state.
    # Acquire that state from the official Happy8 history page first, using
    # the same requests.Session for every API page. All network traffic still
    # goes through NetClient, so timeout/retry/HTTPS/attempt-ledger rules stay
    # centralized and auditable.
    session = requests.Session()
    national_net = NetClient(
        connect_timeout=10,
        read_timeout=30,
        max_attempts=3,
        session=session,
    )
    landing_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Referer": "https://www.cwl.gov.cn/",
    }
    bootstrap = national_net.get(
        NATIONAL_LANDING_URL,
        headers=landing_headers,
        timeout=(10, 30),
        allow_redirects=True,
    )
    bootstrap_raw = _validate_html_response(bootstrap)
    bootstrap_url = urlsplit(str(getattr(bootstrap, "url", "") or NATIONAL_LANDING_URL))
    if (
        bootstrap_url.scheme.lower() != "https"
        or bootstrap_url.hostname != urlsplit(NATIONAL_LANDING_URL).hostname
    ):
        raise RuntimeError("CWL Happy8 session bootstrap left official HTTPS host")
    bootstrap_record = {
        "url": str(getattr(bootstrap, "url", "") or NATIONAL_LANDING_URL),
        "http_status": int(bootstrap.status_code),
        "sha256": hashlib.sha256(bootstrap_raw).hexdigest(),
        "bytes": len(bootstrap_raw),
        "attempts": list(getattr(bootstrap, "happy8_attempts", ())),
        "cookie_names": sorted(session.cookies.keys()),
    }
    raw_sources["national_session_bootstrap.html"] = bootstrap_raw

    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Referer": NATIONAL_LANDING_URL,
        "X-Requested-With": "XMLHttpRequest",
    }

    while True:
        params = _national_params(page, page_size)
        response = national_net.get(
            NATIONAL_URL,
            params=params,
            headers=headers,
            timeout=(10, 30),
            allow_redirects=True,
        )
        actual = urlsplit(str(getattr(response, "url", "") or NATIONAL_URL))
        if actual.scheme.lower() != "https" or actual.hostname != urlsplit(NATIONAL_URL).hostname:
            raise RuntimeError("CWL Happy8 response left official HTTPS host")
        raw = _validate_national_response(response)
        draws, pages, total_count = _parse_national_payload(raw)
        if page == 1:
            if pages is None and total_count is not None:
                pages = max(1, (total_count + page_size - 1) // page_size)
            if pages is None or pages < 1 or pages > 10000:
                raise RuntimeError(f"CWL Happy8 page count invalid: {pages!r}")
            reported_pages = pages
        elif pages is not None and pages != reported_pages:
            raise RuntimeError("CWL Happy8 page count changed during fetch")
        if not draws:
            raise RuntimeError(f"CWL Happy8 page {page} contained no draws")
        filename = f"national_page_{page:04d}.json"
        raw_sources[filename] = raw
        manifest.append({
            "sequence": page,
            **({"session_bootstrap": bootstrap_record} if page == 1 else {}),
            "page": page,
            "filename": filename,
            "http_status": int(response.status_code),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "draw_count": len(draws),
            "first_issue": min(d.issue for d in draws),
            "last_issue": max(d.issue for d in draws),
            "url": str(response.url),
        })
        all_draws.extend(draws)
        if page >= int(reported_pages):
            break
        page += 1

    seen: dict[str, Draw] = {}
    for draw in all_draws:
        prior = seen.get(draw.issue)
        if prior and prior != draw:
            raise RuntimeError(f"CWL Happy8 conflicting duplicate issue {draw.issue}")
        seen[draw.issue] = draw
    ordered = sorted(seen.values(), key=lambda d: (d.draw_date, d.issue))
    if not ordered or ordered[0].issue != HAPPY8_HISTORY_START_ISSUE:
        raise RuntimeError(
            f"CWL Happy8 full history does not start at {HAPPY8_HISTORY_START_ISSUE}: "
            f"{ordered[0].issue if ordered else 'EMPTY'}"
        )
    by_year: dict[str, list[int]] = {}
    for draw in ordered:
        by_year.setdefault(draw.issue[:4], []).append(int(draw.issue[-3:]))
    for year, suffixes in by_year.items():
        first = int(HAPPY8_HISTORY_START_ISSUE[-3:]) if year == HAPPY8_HISTORY_START_ISSUE[:4] else 1
        if suffixes != list(range(first, max(suffixes) + 1)):
            raise RuntimeError(f"CWL Happy8 history has issue gaps/duplicates in {year}")
    latest_day = datetime.strptime(ordered[-1].draw_date, "%Y-%m-%d").date()
    age = (date.today() - latest_day).days
    if age < 0 or age > 7:
        raise RuntimeError(f"CWL Happy8 latest draw is stale/future: age_days={age}")
    receipt = SourceReceipt(
        source="national_welfare_lottery",
        url=NATIONAL_URL,
        http_status=200,
        fetched_at=_utc_now(),
        raw_sha256=_sha256_json({"session_bootstrap": bootstrap_record, "pages": manifest}),
        bytes=len(bootstrap_raw) + sum(int(x["bytes"]) for x in manifest),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
    )
    return ordered, receipt, raw_sources, manifest


def parse_shanghai_history(text: str, *, allow_empty: bool = False) -> list[Draw]:
    plain = _plain(text)
    pattern = re.compile(
        r"(20\d{5})\s+(\d{4}-\d{2}-\d{2})(?:\([^)]*\))?\s+((?:\d{2}\s*){20})(?!\d)"
    )
    found: dict[str, Draw] = {}
    for issue, day, compact in pattern.findall(plain):
        draw = Draw.from_values(issue, day, _numbers_from_compact(compact))
        previous = found.get(draw.issue)
        if previous and previous != draw:
            raise RuntimeError(f"Shanghai official source conflict for issue {draw.issue}")
        found[draw.issue] = draw
    draws = sorted(found.values(), key=lambda d: (d.draw_date, d.issue))
    if not draws and not allow_empty:
        raise RuntimeError("Shanghai official history contained no parseable draws")
    return draws


def parse_jiangsu_latest(text: str) -> Draw:
    plain = _plain(text)
    pattern = re.compile(
        r"快乐8\s*第\s*(20\d{5})\s*期\s*((?:\d{2}\s+){19}\d{2})(?!\d)"
    )
    match = pattern.search(plain)
    if not match:
        raise RuntimeError("Jiangsu official home page did not expose a Happy8 result row")
    issue, spaced = match.groups()
    nums = [int(x) for x in re.findall(r"\d{2}", spaced)]
    return Draw.from_values(issue, date.today().isoformat(), nums)


def _year_ranges(year: int) -> list[tuple[int, int]]:
    return [(low, min(low + 98, 396)) for low in range(1, 397, 99)]


def fetch_shanghai_full_history() -> tuple[list[Draw], SourceReceipt, dict[str, bytes], list[dict[str, Any]]]:
    start_year = int(HAPPY8_HISTORY_START_ISSUE[:4])
    current_year = date.today().year
    if current_year < start_year:
        raise RuntimeError("current year precedes Happy8 history start")

    all_draws: list[Draw] = []
    raw_sources: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    seen: dict[str, Draw] = {}

    for year in range(start_year, current_year + 1):
        year_had_data = False
        for low, high in _year_ranges(year):
            if year == start_year:
                low = max(low, int(HAPPY8_HISTORY_START_ISSUE[-3:]))
            if low > high:
                continue
            start_issue = f"{year}{low:03d}"
            end_issue = f"{year}{high:03d}"
            # Match the official Shanghai custom-range form exactly.
            # The form submits view + start_issue + end_issue. The recent-N
            # shortcut's limit parameter is a different query mode and must
            # not be mixed into a custom issue range.
            params = {
                "view": "previous",
                "start_issue": start_issue,
                "end_issue": end_issue,
            }
            response = NET.get(
                SHANGHAI_HISTORY_URL,
                params=params,
                headers=HEADERS,
                timeout=(10, 30),
                allow_redirects=True,
            )
            raw = _validate_html_response(response)
            actual = urlsplit(str(getattr(response, "url", "") or ""))
            expected_host = urlsplit(SHANGHAI_HISTORY_URL).hostname
            if actual.scheme.lower() != "https" or actual.hostname != expected_host:
                raise RuntimeError("Shanghai Happy8 history response left official HTTPS host")
            actual_params = dict(parse_qsl(actual.query, keep_blank_values=True))
            if actual_params != params:
                raise RuntimeError(
                    f"Shanghai Happy8 query changed in transit: expected={params!r} actual={actual_params!r}"
                )

            response.encoding = response.encoding or "utf-8"
            chunk = parse_shanghai_history(response.text, allow_empty=True)
            if not chunk:
                if year_had_data:
                    break
                if year < current_year:
                    visible_issues = re.findall(r"20\d{5}", _plain(response.text))[:12]
                    input_tags = re.findall(r"(?is)<input\b[^>]*>", response.text)
                    input_contract = []
                    for tag in input_tags[:20]:
                        attrs = {}
                        for key in ("name", "id", "type", "value", "placeholder"):
                            match = re.search(
                                rf"(?is)\b{key}\s*=\s*['\\\"]([^'\\\"]*)['\\\"]",
                                tag,
                            )
                            if match:
                                attrs[key] = match.group(1)[:120]
                        if attrs:
                            input_contract.append(attrs)
                    forms = [
                        re.sub(r"\s+", " ", tag)[:300]
                        for tag in re.findall(r"(?is)<form\b[^>]*>", response.text)[:10]
                    ]
                    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", response.text)
                    title = _plain(title_match.group(1))[:180] if title_match else ""
                    script_srcs = [
                        html.unescape(src)[:220]
                        for src in re.findall(
                            r"(?is)<script\b[^>]*\bsrc\s*=\s*['\\\"]([^'\\\"]+)['\\\"]",
                            response.text,
                        )[:20]
                    ]
                    inline_hints = []
                    for body in re.findall(
                        r"(?is)<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>",
                        response.text,
                    ):
                        compact = re.sub(r"\s+", " ", body)
                        for match in re.finditer(
                            r"(?i).{0,90}(?:issue|query|start|end|custom|期号).{0,140}",
                            compact,
                        ):
                            inline_hints.append(match.group(0)[:260])
                            if len(inline_hints) >= 12:
                                break
                        if len(inline_hints) >= 12:
                            break
                    sanitized_text = _plain(response.text)[:420]
                    raise RuntimeError(
                        "Shanghai Happy8 historical range parsed empty: "
                        f"range={start_issue}..{end_issue} bytes={len(raw)} "
                        f"sha256={hashlib.sha256(raw).hexdigest()} "
                        f"title={title!r} text_head={sanitized_text!r} "
                        f"visible_issue_tokens={visible_issues!r} forms={forms!r} "
                        f"inputs={input_contract!r} script_srcs={script_srcs!r} "
                        f"inline_hints={inline_hints!r}"
                    )
                break

            year_had_data = True
            for draw in chunk:
                if not (start_issue <= draw.issue <= end_issue):
                    raise RuntimeError(
                        f"Shanghai Happy8 returned issue outside requested range: {draw.issue} "
                        f"not in {start_issue}..{end_issue}"
                    )
                prior = seen.get(draw.issue)
                if prior and prior != draw:
                    raise RuntimeError(f"Shanghai Happy8 cross-chunk conflict for issue {draw.issue}")
                seen[draw.issue] = draw

            filename = f"shanghai_{start_issue}_{end_issue}.html"
            raw_sources[filename] = raw
            item = {
                "sequence": len(manifest) + 1,
                "start_issue": start_issue,
                "end_issue": end_issue,
                "filename": filename,
                "http_status": int(response.status_code),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "draw_count": len(chunk),
                "first_issue": chunk[0].issue,
                "last_issue": chunk[-1].issue,
                "url": str(response.url),
            }
            manifest.append(item)
            all_draws.extend(chunk)

    ordered = sorted(seen.values(), key=lambda d: (d.draw_date, d.issue))
    if not ordered or ordered[0].issue != HAPPY8_HISTORY_START_ISSUE:
        raise RuntimeError(
            f"Shanghai Happy8 full history does not start at {HAPPY8_HISTORY_START_ISSUE}: "
            f"{ordered[0].issue if ordered else 'EMPTY'}"
        )

    by_year: dict[str, list[int]] = {}
    for draw in ordered:
        by_year.setdefault(draw.issue[:4], []).append(int(draw.issue[-3:]))
    for year, suffixes in by_year.items():
        first = int(HAPPY8_HISTORY_START_ISSUE[-3:]) if year == HAPPY8_HISTORY_START_ISSUE[:4] else 1
        if suffixes != list(range(first, max(suffixes) + 1)):
            raise RuntimeError(f"Shanghai Happy8 history has issue gaps/duplicates in {year}")

    receipt = SourceReceipt(
        source="shanghai_welfare_lottery",
        url=SHANGHAI_HISTORY_URL,
        http_status=200,
        fetched_at=_utc_now(),
        raw_sha256=_sha256_json(manifest),
        bytes=sum(int(x["bytes"]) for x in manifest),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
    )
    return ordered, receipt, raw_sources, manifest



def _market_calendar_date_for_issue(issue: str) -> str:
    if not re.fullmatch(r"20\d{5}", issue):
        raise RuntimeError(f"Happy8 issue format invalid for market calendar: {issue!r}")
    year = int(issue[:4])
    sequence = int(issue[4:])
    if year not in HAPPY8_MARKET_CLOSURES:
        raise RuntimeError(f"Happy8 market calendar year is not frozen: {year}")
    if sequence < 1:
        raise RuntimeError(f"Happy8 issue sequence invalid: {issue}")

    current = date(2020, 10, 28) if year == 2020 else date(year, 1, 1)
    closures = tuple(
        (
            datetime.strptime(start, "%Y-%m-%d").date(),
            datetime.strptime(end, "%Y-%m-%d").date(),
        )
        for start, end in HAPPY8_MARKET_CLOSURES[year]
    )
    count = 0
    while current.year == year:
        if not any(start <= current <= end for start, end in closures):
            count += 1
            if count == sequence:
                return current.isoformat()
        current += timedelta(days=1)
    raise RuntimeError(
        f"Happy8 issue exceeds official market-calendar capacity: issue={issue} "
        f"year_count={count}"
    )


def _decode_html(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _official_host(url: str, allowed: set[str]) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and parsed.hostname in allowed


def _pagination_from_links(markup: str, *, source: str) -> list[int]:
    pages: list[int] = []
    for href in re.findall(r"(?is)href\s*=\s*['\"]([^'\"]+)['\"]", markup):
        query = dict(parse_qsl(urlsplit(html.unescape(href)).query, keep_blank_values=True))
        if source == "fuzhou":
            if query.get("play") != "kl8" or "page" not in query:
                continue
        elif source == "jiangsu":
            if query.get("lottery_type_id") != "17" or "page" not in query:
                continue
        else:
            raise ValueError(f"unknown pagination source: {source}")
        try:
            pages.append(int(query["page"]))
        except Exception:
            continue
    return sorted(set(pages))


def _parse_fuzhou_number_rows(markup: str) -> dict[str, tuple[int, ...]]:
    rows: dict[str, tuple[int, ...]] = {}
    for body in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", markup):
        cells = [_plain(cell) for cell in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", body)]
        joined = " ".join(cells)
        issue_match = re.search(r"(?<!\d)(20\d{5})(?!\d)", joined)
        if not issue_match:
            continue
        numbers: list[int] = []
        for cell in cells:
            token = cell.strip()
            if re.fullmatch(r"0?[1-9]|[1-7]\d|80", token):
                numbers.append(int(token))
        if len(numbers) != 20 or len(set(numbers)) != 20 or not all(1 <= n <= 80 for n in numbers):
            continue
        issue = issue_match.group(1)
        value = tuple(numbers)
        previous = rows.get(issue)
        if previous is not None and previous != value:
            raise RuntimeError(f"Fuzhou official source conflict for issue {issue}")
        rows[issue] = value
    return rows


def _parse_jiangsu_issue_dates(markup: str) -> dict[str, str]:
    """Return issue -> Jiangsu publication date for issue-bound official CWL links.

    The date shown by the Jiangsu index is publication/republish metadata, not
    the canonical draw date.  Likewise the /c/YYYY/MM/DD/ component of a CWL
    article URL is publication metadata and is not used as an event date.
    Canonical Happy8 draw dates are derived separately from the nationally
    binding draw cadence plus Ministry of Finance market-closure calendar.
    """
    visible_dates: dict[str, str] = {}
    plain = _plain(markup)
    for match in re.finditer(
        r"(?:第\s*)?(20\d{5})\s*期[^0-9]{0,80}(20\d{2}-\d{2}-\d{2})",
        plain,
    ):
        issue, day = match.group(1), match.group(2)
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise RuntimeError(
                f"Jiangsu visible publication date invalid for issue {issue}: {day}"
            ) from exc
        previous = visible_dates.get(issue)
        if previous is not None and previous != day:
            raise RuntimeError(f"Jiangsu visible publication-date conflict for issue {issue}")
        visible_dates[issue] = day

    linked_issues: set[str] = set()
    for href, body in re.findall(
        r"(?is)<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        markup,
    ):
        label = _plain(body)
        if "快乐8" not in label:
            continue
        issue_match = re.search(r"(?<!\d)(20\d{5})(?!\d)", label)
        if not issue_match:
            continue
        target = html.unescape(href).strip()
        parsed = urlsplit(target)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in {
            "www.cwl.gov.cn",
            "cwl.gov.cn",
        }:
            continue
        # The linked national article is provenance for the same issue only.
        # Its path date is intentionally ignored: live evidence has shown that
        # article publication can be before/same/after the draw date.
        linked_issues.add(issue_match.group(1))

    pairs: dict[str, str] = {}
    for issue in sorted(linked_issues):
        day = visible_dates.get(issue)
        if day is not None:
            pairs[issue] = day
    return pairs


def _validate_jiangsu_publication_lag(issue: str, draw_day: str, publication_day: str) -> int:
    try:
        draw_date = datetime.strptime(draw_day, "%Y-%m-%d").date()
        published = datetime.strptime(publication_day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(
            f"Jiangsu publication-lag date invalid for {issue}: "
            f"draw={draw_day} publication={publication_day}"
        ) from exc
    lag_days = (published - draw_date).days
    # Current official diagnostic corpus spans 0, +1 and +2 day local
    # publication lags.  Negative lags or >=3 days are treated as semantic
    # mismatch and fail closed rather than being silently accepted.
    if lag_days < 0 or lag_days > 2:
        raise RuntimeError(
            f"Jiangsu publication lag outside frozen bound for {issue}: "
            f"draw={draw_day} publication={publication_day} lag_days={lag_days}"
        )
    return lag_days

def fetch_provincial_composite_full_history() -> tuple[
    list[Draw], SourceReceipt, dict[str, bytes], list[dict[str, Any]]
]:
    fuzhou_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.jxfzfc.cn/",
    }
    jiangsu_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
        "Referer": JIANGSU_URL,
    }

    raw_sources: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    number_map: dict[str, tuple[int, ...]] = {}
    date_map: dict[str, str] = {}
    observed_publication_map: dict[str, str] = {}

    # Draw numbers come from the Fuzhou official history. Canonical draw dates
    # are deterministically derived from the nationally binding Ministry of
    # Finance lottery-market closure calendar. The Jiangsu official archive is
    # an independent issue-existence/provenance crosscheck; its visible dates
    # are publication metadata and are validated only for a frozen 0..2-day lag
    # after the derived draw date. CWL URL path dates are never treated as draw
    # dates.
    first_fuzhou = NET.get(
        FUZHOU_HISTORY_URL,
        params={"play": "kl8", "sid": "new", "page": "1"},
        headers=fuzhou_headers,
        timeout=(10, 30),
        allow_redirects=True,
    )
    first_fuzhou_raw = _validate_html_response(first_fuzhou)
    if not _official_host(str(first_fuzhou.url), {"www.jxfzfc.cn", "jxfzfc.cn"}):
        raise RuntimeError("Fuzhou Happy8 history response left official HTTPS host")
    first_fuzhou_text = _decode_html(first_fuzhou_raw)
    if FUZHOU_AUTHORITY_MARKER not in _plain(first_fuzhou_text):
        raise RuntimeError("Fuzhou official authority marker missing")
    fuzhou_pages = _pagination_from_links(first_fuzhou_text, source="fuzhou")
    fuzhou_max = max(fuzhou_pages, default=1)
    if fuzhou_max < 21 or fuzhou_max > 30:
        raise RuntimeError(f"Fuzhou Happy8 pagination outside frozen bounds: {fuzhou_max}")

    for page_no in range(1, fuzhou_max + 1):
        if page_no == 1:
            response, raw, markup = first_fuzhou, first_fuzhou_raw, first_fuzhou_text
        else:
            response = NET.get(
                FUZHOU_HISTORY_URL,
                params={"play": "kl8", "sid": "new", "page": str(page_no)},
                headers=fuzhou_headers,
                timeout=(10, 30),
                allow_redirects=True,
            )
            raw = _validate_html_response(response)
            if not _official_host(str(response.url), {"www.jxfzfc.cn", "jxfzfc.cn"}):
                raise RuntimeError("Fuzhou Happy8 history response left official HTTPS host")
            markup = _decode_html(raw)
            if FUZHOU_AUTHORITY_MARKER not in _plain(markup):
                raise RuntimeError(f"Fuzhou authority marker missing on page {page_no}")

        rows = _parse_fuzhou_number_rows(markup)
        if not rows:
            raise RuntimeError(f"Fuzhou Happy8 page {page_no} contained no valid rows")
        for issue, numbers in rows.items():
            previous = number_map.get(issue)
            if previous is not None and previous != numbers:
                raise RuntimeError(f"Fuzhou cross-page conflict for issue {issue}")
            number_map[issue] = numbers
        filename = f"fuzhou_page_{page_no:03d}.html"
        raw_sources[filename] = raw
        manifest.append({
            "source": "jiangxi_fuzhou_welfare_lottery",
            "page": page_no,
            "filename": filename,
            "url": str(response.url),
            "http_status": int(response.status_code),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "row_count": len(rows),
            "first_issue": min(rows),
            "last_issue": max(rows),
        })

    number_issues = set(number_map)
    if not number_issues or min(number_issues) != HAPPY8_HISTORY_START_ISSUE:
        raise RuntimeError(
            f"provincial official history does not start at {HAPPY8_HISTORY_START_ISSUE}"
        )
    if len(number_issues) < 2000:
        raise RuntimeError(f"provincial official history too short: {len(number_issues)}")

    date_map = {issue: _market_calendar_date_for_issue(issue) for issue in number_issues}
    if date_map.get(HAPPY8_HISTORY_START_ISSUE) != HAPPY8_HISTORY_START_DATE:
        raise RuntimeError(
            f"market-calendar start mismatch: issue={HAPPY8_HISTORY_START_ISSUE} "
            f"expected={HAPPY8_HISTORY_START_DATE} "
            f"actual={date_map.get(HAPPY8_HISTORY_START_ISSUE)}"
        )

    calendar_contract = {
        "schema": "happy8-market-calendar-contract-v1",
        "derivation": "daily_draws_excluding_mof_market_closures",
        "launch_issue": HAPPY8_HISTORY_START_ISSUE,
        "launch_date": HAPPY8_HISTORY_START_DATE,
        "closure_windows": HAPPY8_MARKET_CLOSURES,
        "source_urls": HAPPY8_MARKET_CALENDAR_SOURCES,
    }
    calendar_raw = json.dumps(
        calendar_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    raw_sources["mof_market_calendar_contract.json"] = calendar_raw
    manifest.append({
        "source": "ministry_of_finance_lottery_market_calendar",
        "filename": "mof_market_calendar_contract.json",
        "url": " + ".join(
            HAPPY8_MARKET_CALENDAR_SOURCES[y]
            for y in sorted(HAPPY8_MARKET_CALENDAR_SOURCES)
        ),
        "http_status": None,
        "sha256": hashlib.sha256(calendar_raw).hexdigest(),
        "bytes": len(calendar_raw),
        "row_count": len(date_map),
        "first_issue": min(date_map),
        "last_issue": max(date_map),
        "date_contract": "daily_draws_excluding_official_market_closure_windows",
    })

    first_jiangsu = NET.get(
        JIANGSU_HISTORY_URL,
        params={"locale": "zh-CN", "lottery_type_id": "17", "page": "1", "periods": ""},
        headers=jiangsu_headers,
        timeout=(10, 30),
        allow_redirects=True,
    )
    first_jiangsu_raw = _validate_html_response(first_jiangsu)
    if not _official_host(str(first_jiangsu.url), {"www.jslottery.com"}):
        raise RuntimeError("Jiangsu Happy8 history response left official HTTPS host")
    first_jiangsu_text = _decode_html(first_jiangsu_raw)
    jiangsu_pages = _pagination_from_links(first_jiangsu_text, source="jiangsu")
    jiangsu_max = max(jiangsu_pages, default=1)
    if jiangsu_max < 100 or jiangsu_max > 150:
        raise RuntimeError(f"Jiangsu Happy8 pagination outside frozen bounds: {jiangsu_max}")

    for page_no in range(1, jiangsu_max + 1):
        if page_no == 1:
            response, raw, markup = first_jiangsu, first_jiangsu_raw, first_jiangsu_text
        else:
            response = NET.get(
                JIANGSU_HISTORY_URL,
                params={
                    "locale": "zh-CN",
                    "lottery_type_id": "17",
                    "page": str(page_no),
                    "periods": "",
                },
                headers=jiangsu_headers,
                timeout=(10, 30),
                allow_redirects=True,
            )
            raw = _validate_html_response(response)
            if not _official_host(str(response.url), {"www.jslottery.com"}):
                raise RuntimeError("Jiangsu Happy8 history response left official HTTPS host")
            markup = _decode_html(raw)

        rows = _parse_jiangsu_issue_dates(markup)
        if not rows:
            raise RuntimeError(f"Jiangsu Happy8 page {page_no} contained no issue-date rows")
        for issue, publication_day in rows.items():
            previous = observed_publication_map.get(issue)
            if previous is not None and previous != publication_day:
                raise RuntimeError(
                    f"Jiangsu cross-page publication-date conflict for issue {issue}"
                )
            observed_publication_map[issue] = publication_day
            expected_day = date_map.get(issue)
            if expected_day is not None:
                _validate_jiangsu_publication_lag(issue, expected_day, publication_day)
        filename = f"jiangsu_history_page_{page_no:03d}.html"
        raw_sources[filename] = raw
        manifest.append({
            "source": "jiangsu_welfare_lottery",
            "page": page_no,
            "filename": filename,
            "url": str(response.url),
            "http_status": int(response.status_code),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "row_count": len(rows),
            "first_issue": min(rows),
            "last_issue": max(rows),
            "date_contract": "jiangsu_visible_publication_date_bound_to_issue_and_official_cwl_link",
        })

    observed_issues = set(observed_publication_map)
    crosschecked_issues = number_issues & observed_issues
    missing_index_issues = sorted(number_issues - observed_issues)
    extra_index_issues = sorted(observed_issues - number_issues)
    if extra_index_issues:
        raise RuntimeError(
            f"Jiangsu official archive contains issues missing from Fuzhou number history: "
            f"{extra_index_issues[:20]}"
        )
    if len(missing_index_issues) > 20:
        raise RuntimeError(
            f"Jiangsu official archive gap safety bound exceeded: "
            f"{len(missing_index_issues)} missing issues"
        )
    if len(crosschecked_issues) < int(len(number_issues) * 0.99):
        raise RuntimeError(
            f"official date crosscheck coverage too low: "
            f"crosschecked={len(crosschecked_issues)} numbers={len(number_issues)}"
        )

    previous_issue: str | None = None
    previous_day = None
    for issue in sorted(date_map):
        current_day = datetime.strptime(date_map[issue], "%Y-%m-%d").date()
        if previous_day is not None and current_day <= previous_day:
            raise RuntimeError(
                f"market-calendar dates are not strictly increasing: "
                f"{previous_issue}={previous_day.isoformat()} then "
                f"{issue}={current_day.isoformat()}"
            )
        previous_issue, previous_day = issue, current_day

    manifest.append({
        "source": "jiangsu_welfare_lottery_crosscheck",
        "filename": "derived_from_jiangsu_history_pages",
        "url": JIANGSU_HISTORY_URL,
        "http_status": 200,
        "sha256": _sha256_json({
            "crosschecked_issues": sorted(crosschecked_issues),
            "missing_index_issues": missing_index_issues,
        }),
        "bytes": 0,
        "row_count": len(crosschecked_issues),
        "first_issue": min(crosschecked_issues),
        "last_issue": max(crosschecked_issues),
        "date_contract": "mof_calendar_is_canonical;_jiangsu_publication_lag_must_be_0_to_2_days",
        "missing_index_count": len(missing_index_issues),
        "missing_index_issues": missing_index_issues,
    })

    ordered: list[Draw] = []
    for issue in sorted(number_issues):
        ordered.append(Draw.from_values(issue, date_map[issue], number_map[issue]))

    latest_day = datetime.strptime(ordered[-1].draw_date, "%Y-%m-%d").date()
    age = (date.today() - latest_day).days
    if age < 0 or age > 7:
        raise RuntimeError(f"provincial official latest draw is stale/future: age_days={age}")

    receipt = SourceReceipt(
        source="jiangxi_fuzhou_numbers_plus_mof_calendar_crosschecked_jiangsu",
        url=f"{FUZHOU_HISTORY_URL} + MOF market-calendar notices + {JIANGSU_HISTORY_URL}",
        http_status=200,
        fetched_at=_utc_now(),
        raw_sha256=_sha256_json(manifest),
        bytes=sum(int(item["bytes"]) for item in manifest),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
    )
    return ordered, receipt, raw_sources, manifest


def fetch_jiangsu_latest() -> tuple[Draw, SourceReceipt, bytes]:
    response = NET.get(JIANGSU_URL, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = _validate_html_response(response)
    response.encoding = response.encoding or "utf-8"
    draw = parse_jiangsu_latest(response.text)
    receipt = SourceReceipt(
        source="jiangsu_welfare_lottery",
        url=JIANGSU_URL,
        http_status=int(response.status_code),
        fetched_at=_utc_now(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        draw_count=1,
        latest_issue=draw.issue,
        status="PASS",
    )
    return draw, receipt, raw


def build_official_snapshot() -> tuple[dict[str, Any], dict[str, bytes]]:
    history_error: str | None = None
    try:
        history, history_receipt, raw_sources, manifest = fetch_national_full_history()
        history_source = "national_welfare_lottery"
        verification = "CWL_FULL_HISTORY_PLUS_JIANGSU_CURRENT"
    except Exception as national_exc:
        history_error = f"{type(national_exc).__name__}: {national_exc}"
        try:
            history, history_receipt, raw_sources, manifest = fetch_shanghai_full_history()
            history_source = "shanghai_welfare_lottery"
            verification = "SHANGHAI_FULL_HISTORY_PLUS_JIANGSU_CURRENT"
        except Exception as shanghai_exc:
            shanghai_error = f"{type(shanghai_exc).__name__}: {shanghai_exc}"
            try:
                history, history_receipt, raw_sources, manifest = fetch_provincial_composite_full_history()
                history_source = "jiangxi_fuzhou_numbers_plus_mof_calendar_crosschecked_jiangsu"
                verification = "FUZHOU_NUMBERS_PLUS_MOF_MARKET_CALENDAR_CROSSCHECKED_JIANGSU_AND_CURRENT_NUMBERS"
            except Exception as composite_exc:
                raise RuntimeError(
                    "Happy8 full-history official sources unavailable; "
                    f"CWL={history_error}; Shanghai={shanghai_error}; "
                    f"ProvincialComposite={type(composite_exc).__name__}: {composite_exc}"
                ) from composite_exc

    jiangsu, jiangsu_receipt, jiangsu_raw = fetch_jiangsu_latest()
    latest = history[-1]
    if jiangsu.issue != latest.issue:
        raise RuntimeError(
            f"independent official sources latest issue mismatch: history={latest.issue} Jiangsu={jiangsu.issue}"
        )
    if jiangsu.numbers != latest.numbers:
        raise RuntimeError(f"independent official sources conflict on {latest.issue}")

    age = (date.today() - datetime.strptime(latest.draw_date, "%Y-%m-%d").date()).days
    if age < 0 or age > 7:
        raise RuntimeError(f"official Happy8 latest draw is stale/future: age_days={age}")

    payload = [d.to_dict() for d in history]
    canonical_hash = _sha256_json(payload)
    report = {
        "schema": "happy8-staging-official-network-v4",
        "status": "PASS",
        "latest": latest.to_dict(),
        "history_count": len(history),
        "draws": payload,
        "canonical_hash": canonical_hash,
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "history_source": history_source,
        "history_raw_manifest": manifest,
        "source_receipts": [history_receipt.to_dict(), jiangsu_receipt.to_dict()],
        "verification": verification,
        "source_errors": (
            {"national_welfare_lottery": history_error}
            if history_source == "shanghai_welfare_lottery" and history_error
            else (
                {
                    "national_welfare_lottery": history_error,
                    "shanghai_welfare_lottery": locals().get("shanghai_error"),
                }
                if history_source == "jiangxi_fuzhou_numbers_plus_mof_calendar_crosschecked_jiangsu"
                else {}
            )
        ),
        "note": (
            "Fail-closed official network gate: CWL kl8 is primary full-history source; "
            "Shanghai is first official fallback; the second fallback uses official Jiangxi-Fuzhou draw numbers "
            "with draw dates derived from the frozen Ministry of Finance lottery-market closure calendar. "
            "Every available issue-bound Jiangsu CWL announcement date must agree, archive omissions are "
            "bounded and recorded, and Jiangsu current numbers crosscheck the accepted history source. "
            "Portfolio Final still requires Windows/Exact EXE/GUI/Same Hash and repository independence."
        ),
    }
    # Backward-compatible alias for existing Shanghai storage/tests when fallback is used.
    if history_source == "shanghai_welfare_lottery":
        report["shanghai_raw_manifest"] = manifest
    raw_sources["jiangsu_welfare_lottery.html"] = jiangsu_raw
    return report, raw_sources

def real_network_snapshot() -> dict[str, Any]:
    report, _ = build_official_snapshot()
    return report
