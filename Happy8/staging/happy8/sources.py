from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .domain import Draw
from .net_client import NetClient


NATIONAL_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
SHANGHAI_HISTORY_URL = "https://www.swlc.net.cn/lottery/kl8.html"
HAPPY8_HISTORY_START_ISSUE = "2020001"
JIANGSU_URL = "https://www.jslottery.com/"
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
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.cwl.gov.cn/"

    while True:
        params = _national_params(page, page_size)
        response = NET.get(NATIONAL_URL, params=params, headers=headers, timeout=(10, 30), allow_redirects=True)
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
        raw_sha256=_sha256_json(manifest),
        bytes=sum(int(x["bytes"]) for x in manifest),
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
            raise RuntimeError(
                "Happy8 full-history official sources unavailable; "
                f"CWL={history_error}; Shanghai={type(shanghai_exc).__name__}: {shanghai_exc}"
            ) from shanghai_exc

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
        "source_errors": {"national_welfare_lottery": history_error} if history_error else {},
        "note": (
            "Fail-closed official network gate: CWL kl8 is primary full-history source; "
            "Shanghai official full history is fallback only; Jiangsu independently crosschecks current draw. "
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
