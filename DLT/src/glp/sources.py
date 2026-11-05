from __future__ import annotations

import base64
import html
from html.parser import HTMLParser
import json
import re
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable

import requests

from .constants import NATIONAL_URL
from .net_client import NetClient
from .domain import CanonicalDataset, Draw, SourceReceipt
from .util import canonical_json, sha256_bytes, sha256_json, utc_now

JIANGSU_DATA_PAGE = "https://api.js-lottery.com/wfzq/dlt/data"
JIANGSU_LIST_URL = "https://api.js-lottery.com/Lottery/_ListData"
GANSU_HISTORY_URL = "https://www.gstc.org.cn/wanfa/dlt_history"
GANSU_JSON_URL = "https://www.gstc.org.cn/workapi/prize_history_list"

# Sporttery's WAF has periodically rejected otherwise-valid desktop requests.
# Keep two explicit official-site profiles and fail closed if both fail.
NATIONAL_HEADER_PROFILES = (
    {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://m.lottery.gov.cn/",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.lottery.gov.cn/",
    },
)
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
PARSER_VERSION = "dlt-source-parser-v4-gansu-date-uniqueness"

JIANGSU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://www.js-lottery.com/",
}
GANSU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.gstc.org.cn/",
}


class SourceError(RuntimeError):
    pass


class GansuApiUnavailable(SourceError):
    """Only the first POST transport/non-200 permits the original HTML fallback."""


def _gansu_adjacent(newer: Draw, older: Draw) -> bool:
    """Require literal descending draw identities, including annual rollover."""
    if newer.draw_date <= older.draw_date:
        return False
    if newer.issue[:2] == older.issue[:2]:
        return int(newer.issue) == int(older.issue) + 1
    return int(newer.issue[:2]) == int(older.issue[:2]) + 1 and newer.issue[2:] == "001"


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("甘肃 JSON 对象包含重复键: " + key)
        result[key] = value
    return result


def parse_gansu_json_page(raw: bytes) -> tuple[list[Draw], dict]:
    """Parse literal draw fields in the observed official history contract."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise SourceError("甘肃 JSON 响应字节无效")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict) or payload.get("code") != "000000":
            raise ValueError("response code")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("data object")
        counts = [data.get("total_page_count"), data.get("total_record_count")]
        if any(not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value)
               for value in counts):
            raise ValueError("pagination types")
        pages, total = map(int, counts)
        if pages != (total + 19) // 20:
            raise ValueError("conflicting totals")
        rows = data.get("prize_history_list")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20 or len(rows) > total:
            raise ValueError("row list")
        draws = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("row object")
            day, issue, balls = (row.get(key) for key in ("prize_time", "issue_num", "prize_num"))
            if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
                raise ValueError("literal ISO draw date")
            date.fromisoformat(day)
            if not isinstance(issue, str) or not re.fullmatch(r"[0-9]{5}", issue):
                raise ValueError("literal issue")
            if not isinstance(balls, list) or len(balls) != 7 or any(
                    not isinstance(ball, str) or not re.fullmatch(r"[0-9]{2}", ball) for ball in balls):
                raise ValueError("literal balls")
            nums = tuple(map(int, balls))
            draw = Draw(issue=issue, draw_date=day, front=nums[:5], back=nums[5:])
            draw.validate()
            if draws and not _gansu_adjacent(draws[-1], draw):
                raise ValueError("duplicate or shifted row order")
            draws.append(draw)
        return draws, {"pages": pages, "total": total}
    except SourceError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise SourceError("甘肃 JSON 历史结构或开奖字段非法: " + str(exc)) from exc


def fetch_gansu_history_json(limit: int = 140):
    """Fetch exactly seven pages, once each; retain the unchanged HTML interface."""
    if type(limit) is not int or limit != 140:
        raise SourceError("甘肃 JSON 历史仅支持完整 140 期/7 页")
    all_draws, manifest = [], []
    totals = None
    for page in range(1, 8):
        body = json.dumps({"type_id": "001", "page_no": page, "page_size": 20},
                          separators=(",", ":")).encode("utf-8")
        try:
            response = requests.post(
                GANSU_JSON_URL, data=body,
                headers={**GANSU_HEADERS, "Content-Type": "application/json", "Accept": "application/json"},
                timeout=(10, 30), allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            error = GansuApiUnavailable if page == 1 else SourceError
            raise error(f"甘肃 JSON 第 {page} 页传输失败") from exc
        if int(response.status_code) != 200:
            # Redirects are never a fallback: the intake guard records and refuses
            # them, and standalone calls also never forward their request body.
            error = GansuApiUnavailable if page == 1 and not 300 <= int(response.status_code) < 400 else SourceError
            raise error(f"甘肃 JSON 第 {page} 页 HTTP {response.status_code}")
        raw = bytes(response.content)
        meta = _validate_response(response, raw, expected="json")
        request = getattr(response, "request", None)
        if request is not None and (request.method != "POST" or request.url != GANSU_JSON_URL or request.body != body):
            raise SourceError("甘肃 JSON 实际请求与固定请求不一致")
        if meta["final_url"] != GANSU_JSON_URL:
            raise SourceError("甘肃 JSON 响应地址改变")
        draws, pagination = parse_gansu_json_page(raw)
        if len(draws) != 20 or pagination["total"] < 140 or (totals is not None and totals != pagination):
            raise SourceError("甘肃 JSON 分页数量或总数改变")
        if all_draws and not _gansu_adjacent(all_draws[-1], draws[0]):
            raise SourceError("甘肃 JSON 重复或移动分页")
        totals = pagination
        all_draws.extend(draws)
        meta.update({"source_identity": "official_gansu_sporttery", "requested_url": GANSU_JSON_URL,
                     "page": page, **pagination, "request_method": "POST",
                     "request_body_base64": base64.b64encode(body).decode("ascii"),
                     "request_body_sha256": sha256_bytes(body)})
        manifest.append(meta)
    ordered = list(reversed(all_draws))
    receipt = SourceReceipt(source="gansu", fetched_at=utc_now(), http_status=200,
                            raw_sha256=sha256_bytes("".join(item["sha256"] for item in manifest).encode()),
                            draw_count=140, latest_issue=ordered[-1].issue, status="PASS",
                            detail="甘肃官方 JSON 历史 7 页/140 期；同一来源 corroborator")
    return ordered, receipt, manifest


def _attempts(response) -> list[dict]:
    value = getattr(response, "glp_attempts", ())
    return [dict(x) for x in value] if value else []


def _validate_response(response, raw: bytes, *, expected: str) -> dict:
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise SourceError(f"HTTP status not acceptable: {status}")
    final_url = str(getattr(response, "url", "") or "")
    if final_url and not final_url.startswith("https://"):
        raise SourceError(f"HTTPS 请求被降级到非 HTTPS 地址: {final_url}")
    if not raw:
        raise SourceError("官方源返回空响应")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise SourceError(f"官方源响应过大: {len(raw)} bytes")
    ctype = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
    if expected == "json" and "json" not in ctype:
        raise SourceError(f"Content-Type 非 JSON: {ctype or 'missing'}")
    if expected == "html_or_json" and not any(x in ctype for x in ("text/html", "application/xhtml+xml", "json")):
        raise SourceError(f"Content-Type 非 HTML/JSON: {ctype or 'missing'}")
    return {
        "http_status": status,
        "content_type": ctype,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "body_b64": base64.b64encode(raw).decode("ascii"),
        "fetched_at": utc_now(),
        "final_url": final_url or None,
        "parser_version": PARSER_VERSION,
        "validation_result": "PASS",
        "attempts": _attempts(response),
    }


def _response_fingerprint(response: requests.Response) -> str:
    ctype = response.headers.get("Content-Type", "")
    body_hash = sha256_bytes(response.content)
    return f"status={response.status_code} content_type={ctype!r} bytes={len(response.content)} sha256={body_hash}"


def _parse_result(issue: str, draw_date: str, text: str) -> Draw:
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if len(nums) != 7:
        raise SourceError(f"{issue} 开奖号码不是 7 个: {text}")
    draw = Draw(issue=str(issue), draw_date=str(draw_date)[:10], front=tuple(sorted(nums[:5])), back=tuple(sorted(nums[5:])))
    draw.validate()
    return draw


def _national_get(params: dict[str, str], session: requests.Session | None = None):
    client = NET if session is None else NetClient(connect_timeout=10, read_timeout=30, max_attempts=3, session=session)
    failures: list[str] = []
    for variant_index, profile in enumerate(NATIONAL_HEADER_PROFILES, start=1):
        try:
            response = client.get(NATIONAL_URL, params=params, headers=profile, timeout=(10, 30), allow_redirects=True)
            raw = bytes(response.content)
            meta = _validate_response(response, raw, expected="json")
            meta.update({
                "source_identity": "official_sporttery_national",
                "request_variant": variant_index,
                "requested_url": NATIONAL_URL,
            })
            return response, meta
        except Exception as exc:
            failures.append(f"variant={variant_index} {type(exc).__name__}: {exc}")
    raise SourceError("国家体彩请求失败（同一官方源的请求变体均失败）: " + " | ".join(failures[-4:]))


def fetch_national_page(page_no: int, session: requests.Session | None = None):
    params = {"gameNo": "85", "provinceId": "0", "pageSize": "100", "isVerify": "1", "pageNo": str(page_no)}
    response, response_meta = _national_get(params, session)
    raw = bytes(response.content)
    try:
        payload = response.json()
    except Exception as exc:
        raise SourceError("国家体彩接口返回非 JSON: " + _response_fingerprint(response)) from exc
    if payload.get("success") is not True and str(payload.get("errorCode", "0")) not in {"0", "None"}:
        raise SourceError(f"国家体彩接口拒绝请求: {payload.get('errorCode')} {payload.get('errorMessage','')}")
    value = payload.get("value") or {}
    rows = value.get("list") or value.get("records") or []
    if not isinstance(rows, list):
        raise SourceError("国家体彩记录列表结构改变")
    if page_no == 1 and not rows:
        raise SourceError("国家体彩第一页为空，拒绝把空响应当作成功")
    draws: list[Draw] = []
    seen_issues: set[str] = set()
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceError(f"国家体彩第 {row_index} 行不是对象，拒绝部分解析")
        try:
            draw = _parse_result(
                str(row.get("lotteryDrawNum")),
                str(row.get("lotteryDrawTime")),
                str(row.get("lotteryDrawResult")),
            )
        except Exception as exc:
            raise SourceError(f"国家体彩第 {row_index} 行非法，拒绝跳过坏行: {exc}") from exc
        if draw.issue in seen_issues:
            raise SourceError(f"国家体彩单页出现重复期号: {draw.issue}")
        seen_issues.add(draw.issue)
        draws.append(draw)
    page_count = int(value.get("pages") or value.get("pageCount") or 1)
    total = int(value.get("total") or value.get("totalCount") or len(draws))
    response_meta.update({"page": int(page_no), "pages": page_count, "total": total})
    return draws, raw, {"pages": page_count, "total": total, "response": _response_fingerprint(response), "evidence": response_meta}


def fetch_national_history(progress: Callable[[str], None] | None = None):
    first, raw_first, meta = fetch_national_page(1)
    pages = int(meta["pages"])
    if pages < 1 or pages > 100:
        raise SourceError(f"国家体彩分页数异常: {pages}")
    if progress:
        progress(f"国家体彩主源：1/{pages} 页")
    page_results: dict[int, tuple[list[Draw], bytes, dict]] = {1: (first, raw_first, meta["evidence"])}
    # Keep concurrency conservative to reduce WAF/rate-limit failures.
    if pages > 1:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_national_page, p): p for p in range(2, pages + 1)}
            done = 1
            for future in as_completed(futures):
                p = futures[future]
                draws, raw, page_meta = future.result()
                if int(page_meta["pages"]) != pages:
                    raise SourceError("国家体彩分页数量在请求期间发生变化")
                if int(page_meta["total"]) != int(meta["total"]):
                    raise SourceError("国家体彩总记录数在请求期间发生变化")
                page_results[p] = (draws, raw, page_meta["evidence"])
                done += 1
                if progress and (done == pages or done % 5 == 0):
                    progress(f"国家体彩主源：{done}/{pages} 页")
    all_draws = [d for p in sorted(page_results) for d in page_results[p][0]]
    unique: dict[str, Draw] = {}
    for draw in all_draws:
        if draw.issue in unique:
            if unique[draw.issue].to_dict() != draw.to_dict():
                raise SourceError(f"国家体彩同一期数据自相矛盾: {draw.issue}")
            raise SourceError(f"国家体彩跨页出现重复期号: {draw.issue}")
        unique[draw.issue] = draw
    ordered = sorted(unique.values(), key=lambda d: (d.draw_date, d.issue))
    if not ordered:
        raise SourceError("国家体彩历史为空")
    if meta["total"] and abs(int(meta["total"]) - len(ordered)) > 1:
        raise SourceError(f"主源总数不一致: API={meta['total']} 唯一记录={len(ordered)}")
    raw_manifest = [
        {"page": p, **page_results[p][2]}
        for p in sorted(page_results)
    ]
    receipt = SourceReceipt(
        source="national", fetched_at=utc_now(), http_status=200,
        raw_sha256=sha256_bytes("".join(x["sha256"] for x in raw_manifest).encode()),
        draw_count=len(ordered), latest_issue=ordered[-1].issue, status="PASS",
        detail=f"官方分页 {pages} 页，总数与唯一记录一致；WAF-aware headers",
    )
    return ordered, receipt, raw_manifest


# Reuse the independently regression-tested V4.7 structural date-semantics guard.
# This application parser is also used outside the research Harness.
class _JiangsuDateTables(HTMLParser):
    """Associate literal legacy-parser rows with their own table and columns.

    Structural ambiguity is rejected, rather than applying browser HTML repair
    rules to decide which date header an otherwise parseable row belongs to.
    """

    def __init__(self, text):
        # Parse original markup; decode entities only as cell text. Decoding the
        # whole response first could manufacture structural tags from text.
        super().__init__(convert_charrefs=True)
        self.text = text
        # HTMLParser's getpos() advances lines only at LF, unlike splitlines().
        self.offsets = [0] + [match.end() for match in re.finditer("\n", text)]
        self.stack, self.rows_at, self.contexts = [], {}, []
        self.ambiguous_context = False

    _INERT = {"script", "style", "textarea", "title", "template", "select",
              "option", "noscript", "xmp", "iframe", "noembed", "noframes",
              "plaintext"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}
    _SECTIONS = {"thead", "tbody", "tfoot"}

    def handle_starttag(self, tag, attrs):
        if tag == "plaintext":
            # HTML plaintext has no effective closing tag.
            self.ambiguous_context = True
        unsafe = (tag in self._INERT or any(name in {"hidden", "inert"} for name, _ in attrs)
                  or self.ambiguous_context
                  or any(blocked for _, blocked in self.contexts))
        if tag not in self._VOID:
            self.contexts.append((tag, unsafe))
        if self.stack and unsafe:
            self.stack[-1]["invalid"] = True
        if tag == "table":
            if self.stack:
                self.stack[-1]["invalid"] = True
            self.stack.append({"rows": [], "row": None, "cell": None,
                               "invalid": bool(self.stack) or unsafe,
                               "closed": False, "section": None})
        elif self.stack:
            table = self.stack[-1]
            if tag == "tr":
                if table["row"] is not None or table["cell"] is not None:
                    table["invalid"] = True
                row = {"table": table, "cells": [], "closed": False,
                       "index": len(table["rows"])}
                table["rows"].append(row)
                table["row"], table["cell"] = row, None
                line, col = self.getpos()
                self.rows_at[self.offsets[line - 1] + col] = row
            elif tag in {"td", "th"}:
                if table["row"] is None or table["cell"] is not None:
                    table["invalid"] = True
                if table["row"] is not None:
                    cell = {"tag": tag, "text": [], "closed": False,
                            "inline": [], "attrs": attrs}
                    table["row"]["cells"].append(cell)
                    table["cell"] = cell
            elif tag in self._SECTIONS and table["cell"] is None:
                if table["row"] is not None or table["section"] is not None:
                    table["invalid"] = True
                table["section"] = tag
            elif table["cell"] is not None:
                if tag not in {"span", "b", "strong", "em", "i", "u", "small", "a",
                               "font", "br", "wbr"}:
                    table["invalid"] = True
                if tag not in {"br", "wbr"}:
                    table["cell"]["inline"].append(tag)
            else:
                table["invalid"] = True

    def handle_startendtag(self, tag, attrs):
        # In HTML, '/>' does not close a non-void container. In particular it
        # cannot end a textarea/template/hidden ancestor before candidate rows.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        line, col = self.getpos()
        start = self.offsets[line - 1] + col
        if not re.match(r"</" + re.escape(tag) + r"[ \t\r\n\f]*>",
                        self.text[start:], re.I):
            # HTMLParser repairs '</ textarea>' into an end-tag callback even
            # though HTML leaves the container open. Accept only the supported
            # literal closing grammar, without attributes or a solidus suffix.
            self.ambiguous_context = True
            if self.stack:
                self.stack[-1]["invalid"] = True
            return
        for index in range(len(self.contexts) - 1, -1, -1):
            if self.contexts[index][0] == tag:
                if any(blocked for _, blocked in self.contexts[index + 1:]):
                    # A stray ancestor close cannot release an active unsafe
                    # descendant; reject subsequent evidence in this response.
                    self.ambiguous_context = True
                del self.contexts[index:]
                break
        if not self.stack:
            return
        table = self.stack[-1]
        if tag == "table":
            if (table["row"] is not None or table["cell"] is not None
                    or table["section"] is not None):
                table["invalid"] = True
            table["closed"] = True
            self.stack.pop()
        elif tag == "tr":
            if table["row"] is None or table["cell"] is not None:
                table["invalid"] = True
            if table["row"] is not None:
                table["row"]["closed"] = True
            table["row"], table["cell"] = None, None
        elif tag in {"td", "th"}:
            cell = table["cell"]
            if cell is None or cell["tag"] != tag or cell["inline"]:
                table["invalid"] = True
            if cell is not None:
                cell["closed"] = True
            table["cell"] = None
        elif tag in self._SECTIONS and table["cell"] is None:
            if table["row"] is not None or table["section"] != tag:
                table["invalid"] = True
            table["section"] = None
        elif table["cell"] is not None:
            inline = table["cell"]["inline"]
            if not inline or inline.pop() != tag:
                table["invalid"] = True
        else:
            table["invalid"] = True

    def handle_data(self, data):
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"]["text"].append(data)

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")


def _verify_jiangsu_draw_date_columns(text):
    """Reject publication dates before the old parser can call them draw dates.

    Match exactly the candidate shape consumed by the installed legacy parser;
    bind each match to its structural row, table, and first three columns. A
    header in another table, a comment, or a later row cannot authorize it.
    """
    pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
        r"<td[^>]*>\s*(\d{5})\s*</td>\s*"
        r"<td[^>]*>\s*([\d\s]+?)\s*</td>", re.I | re.S,
    )
    candidates = list(pattern.finditer(text))
    decoded_candidates = list(pattern.finditer(html.unescape(text)))
    unverified = "JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"
    if ([match.groups() for match in candidates]
            != [match.groups() for match in decoded_candidates]):
        raise SourceError(unverified)
    if not candidates:
        return  # Empty terminal pages are not draw evidence.
    parser = _JiangsuDateTables(text)
    parser.feed(text)
    parser.close()
    tables = {}

    def labels(row):
        return ["".join("".join(cell["text"]).split()) for cell in row["cells"]]

    def positional(row):
        return (row["closed"] and len(row["cells"]) >= 3
                and all(cell["closed"] and not cell["inline"]
                        and all(name not in {"rowspan", "colspan"} or value == "1"
                                for name, value in cell["attrs"])
                        for cell in row["cells"]))

    for match in candidates:
        row = parser.rows_at.get(match.start())
        if row is None or not positional(row):
            raise SourceError(unverified)
        table = row["table"]
        if table["invalid"] or not table["closed"]:
            raise SourceError(unverified)
        if labels(row)[:3] != ["".join(value.split()) for value in match.groups()]:
            raise SourceError(unverified)
        tables.setdefault(id(table), (table, []))[1].append(row)
    draw_headers = {"开奖日期", "开奖时间"}
    publication_headers = {"发布日期", "发布时间", "公告日期", "公告时间"}
    issue_headers = {"期号", "开奖期号"}
    result_headers = {"开奖号码", "开奖结果"}
    for table, rows in tables.values():
        candidate_ids = {id(row) for row in rows}
        # Every other row must be a verified header. Unknown replacement schemas
        # and footer rows cannot silently inherit an earlier header's meaning.
        headers = [row for row in table["rows"]
                   if id(row) not in candidate_ids]
        if any(labels(row) and labels(row)[0] in publication_headers for row in headers):
            raise SourceError("JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE")
        if (not headers or min(row["index"] for row in headers) >= min(row["index"] for row in rows)
                or any(not positional(row) or len(labels(row)) < 3
                       or labels(row)[0] not in draw_headers
                       or labels(row)[1] not in issue_headers
                       or labels(row)[2] not in result_headers for row in headers)):
            raise SourceError(unverified)


def _parse_jiangsu_html(text: str) -> list[Draw]:
    _verify_jiangsu_draw_date_columns(text)
    text = html.unescape(text)
    # Main public history page: date, 5-digit issue, seven whitespace-separated numbers.
    row_pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
        r"<td[^>]*>\s*(\d{5})\s*</td>\s*"
        r"<td[^>]*>\s*([\d\s]+?)\s*</td>", re.I | re.S,
    )
    draws: list[Draw] = []
    seen: dict[str, Draw] = {}
    for row_index, (day, issue, result) in enumerate(row_pattern.findall(text)):
        try:
            draw = _parse_result(issue, day, result)
        except Exception as exc:
            raise SourceError(f"江苏体彩候选开奖行 {row_index} 非法，拒绝跳过坏行: {exc}") from exc
        previous = seen.get(draw.issue)
        if previous is not None:
            if previous.to_dict() != draw.to_dict():
                raise SourceError(f"江苏体彩同一期数据冲突: {draw.issue}")
            raise SourceError(f"江苏体彩出现重复期号: {draw.issue}")
        seen[draw.issue] = draw
        draws.append(draw)
    return sorted(draws, key=lambda d: (d.draw_date, d.issue))



def _decode_html(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceError("官方 HTML 响应编码不可验证")


def fetch_jiangsu_history(progress: Callable[[str], None] | None = None, page_size: int = 100):
    page_size = max(20, min(int(page_size), 100))
    page_results: dict[int, tuple[list[Draw], dict]] = {}
    seen: dict[str, Draw] = {}
    empty_after_data = False

    for page_index in range(1, 80):
        response = NET.get(
            JIANGSU_LIST_URL,
            params={"itemType": "lo", "pageIndex": str(page_index), "pageSize": str(page_size)},
            headers={**JIANGSU_HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": JIANGSU_DATA_PAGE},
            timeout=(10, 30),
            allow_redirects=True,
        )
        raw = bytes(response.content)
        meta = _validate_response(response, raw, expected="html_or_json")
        meta.update({
            "source_identity": "official_jiangsu_sporttery",
            "requested_url": JIANGSU_LIST_URL,
            "page": page_index,
            "page_size": page_size,
        })
        draws = _parse_jiangsu_html(_decode_html(raw))
        if not draws:
            if page_index == 1:
                raise SourceError("江苏体彩历史接口第一页未解析到大乐透记录")
            empty_after_data = True
            break

        for draw in draws:
            previous = seen.get(draw.issue)
            if previous is not None:
                if previous.to_dict() != draw.to_dict():
                    raise SourceError(f"江苏体彩跨页同一期数据冲突: {draw.issue}")
                raise SourceError(f"江苏体彩跨页重复期号: {draw.issue}")
            seen[draw.issue] = draw
        page_results[page_index] = (draws, meta)

        if progress and (page_index == 1 or page_index % 5 == 0):
            progress(f"江苏体彩官方历史：已抓取 {len(seen)} 期")

        if len(draws) < page_size:
            empty_after_data = True
            break

    if not empty_after_data:
        raise SourceError("江苏体彩历史分页超过安全上限，拒绝部分历史")
    ordered = sorted(seen.values(), key=lambda d: (d.draw_date, d.issue))
    if len(ordered) < 600:
        raise SourceError(f"江苏体彩完整历史不足科学验证最低要求: {len(ordered)} < 600")
    if ordered != sorted(ordered, key=lambda d: (d.draw_date, d.issue)):
        raise SourceError("江苏体彩历史排序异常")

    evidence_pages = [{"page": p, **page_results[p][1]} for p in sorted(page_results)]
    receipt = SourceReceipt(
        source="jiangsu_full",
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256=sha256_bytes("".join(x["sha256"] for x in evidence_pages).encode()),
        draw_count=len(ordered),
        latest_issue=ordered[-1].issue,
        status="PASS",
        detail=f"江苏体彩官方分页完整历史 {len(evidence_pages)} 页/{len(ordered)} 期",
    )
    return ordered, receipt, evidence_pages


def _parse_gansu_history(text: str) -> list[Draw]:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain).strip()
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2})\s+(\d{5})\s+((?:(?:\d{2})\s*){7})(?!\d)"
    )
    draws: list[Draw] = []
    seen: dict[str, Draw] = {}
    seen_dates: dict[str, str] = {}
    for row_index, (day, issue, compact) in enumerate(pattern.findall(plain)):
        nums = re.findall(r"\d{2}", compact)
        if len(nums) != 7:
            raise SourceError(f"甘肃体彩候选开奖行 {row_index} 号码数量异常")
        try:
            draw = _parse_result(issue, day, " ".join(nums))
        except Exception as exc:
            raise SourceError(f"甘肃体彩候选开奖行 {row_index} 非法: {exc}") from exc
        previous = seen.get(draw.issue)
        if previous is not None:
            if previous.to_dict() != draw.to_dict():
                raise SourceError(f"甘肃体彩同一期数据冲突: {draw.issue}")
            raise SourceError(f"甘肃体彩重复期号: {draw.issue}")
        earlier_issue = seen_dates.get(draw.draw_date)
        if earlier_issue is not None and earlier_issue != draw.issue:
            raise SourceError(
                f"GANSU_DUPLICATE_DRAW_DATE: date={draw.draw_date} "
                f"issues={earlier_issue},{draw.issue}"
            )
        seen_dates[draw.draw_date] = draw.issue
        seen[draw.issue] = draw
        draws.append(draw)
    return sorted(draws, key=lambda d: (d.draw_date, d.issue))


def fetch_gansu_recent(limit: int = 20):
    response = NET.get(GANSU_HISTORY_URL, headers=GANSU_HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    meta = _validate_response(response, raw, expected="html_or_json")
    meta.update({
        "source_identity": "official_gansu_sporttery",
        "requested_url": GANSU_HISTORY_URL,
    })
    draws = _parse_gansu_history(_decode_html(raw))
    if len(draws) < 10:
        raise SourceError(f"甘肃体彩历史页可核对记录不足: {len(draws)}")
    draws = draws[-max(10, min(int(limit), len(draws))):]
    receipt = SourceReceipt(
        source="gansu",
        fetched_at=utc_now(),
        http_status=int(response.status_code),
        raw_sha256=sha256_bytes(raw),
        draw_count=len(draws),
        latest_issue=draws[-1].issue,
        status="PASS",
        detail=f"甘肃省体育彩票管理中心官方历史页最近 {len(draws)} 期",
    )
    return draws, receipt, meta


def fetch_jiangsu_recent(limit: int = 100):
    failures: list[str] = []
    # Prefer the public history page because it is the user-visible official surface.
    for url, params, extra_headers in (
        (JIANGSU_DATA_PAGE, None, {}),
        (JIANGSU_LIST_URL, {"itemType": "lo", "pageIndex": "1", "pageSize": str(max(10, min(limit, 100)))}, {"X-Requested-With": "XMLHttpRequest", "Referer": JIANGSU_DATA_PAGE}),
    ):
        headers = dict(JIANGSU_HEADERS)
        headers.update(extra_headers)
        try:
            response = NET.get(url, params=params, headers=headers, timeout=(10, 30), allow_redirects=True)
            raw = bytes(response.content)
            raw_meta = _validate_response(response, raw, expected="html_or_json")
            raw_meta.update({
                "source_identity": "official_jiangsu_sporttery",
                "requested_url": url,
            })
            response.encoding = response.encoding or "utf-8"
            draws = _parse_jiangsu_html(response.text)
            if len(draws) < 10:
                failures.append(url + f" parsed={len(draws)} " + _response_fingerprint(response))
                continue
            draws = draws[-max(10, min(limit, 100)):]
            receipt = SourceReceipt(
                source="jiangsu", fetched_at=utc_now(), http_status=response.status_code,
                raw_sha256=sha256_bytes(response.content), draw_count=len(draws), latest_issue=draws[-1].issue,
                status="PASS", detail=f"江苏体彩官方历史页解析成功: {url}",
            )
            return draws, receipt, raw_meta
        except Exception as exc:
            failures.append(url + f" {type(exc).__name__}: {exc}")
    raise SourceError("江苏体彩两个官方路径均失败: " + " | ".join(failures[-4:]))


def _validate_freshness(draws: list[Draw], max_age_days: int = 7) -> None:
    if not draws:
        raise SourceError("官方数据为空，无法验证时效")
    latest = datetime.strptime(draws[-1].draw_date[:10], "%Y-%m-%d").date()
    age = (date.today() - latest).days
    if age < 0:
        raise SourceError(f"官方数据最新日期来自未来: {latest.isoformat()}")
    if age > max_age_days:
        raise SourceError(f"官方数据过期: latest={latest.isoformat()} age_days={age} > {max_age_days}")


def _crosscheck(primary: list[Draw], secondary: list[Draw], minimum: int = 10) -> int:
    sm = {d.issue: d for d in secondary}
    overlap = [d for d in primary if d.issue in sm]
    if len(overlap) < minimum:
        raise SourceError(f"两个独立官方来源共同期号不足: {len(overlap)} < {minimum}")
    mismatches = [d.issue for d in overlap if d.to_dict() != sm[d.issue].to_dict()]
    if mismatches:
        raise SourceError("独立官方来源冲突，拒绝更新: " + ", ".join(mismatches[:10]))
    if primary[-1].issue != secondary[-1].issue:
        raise SourceError(
            f"独立官方来源最新期不一致，拒绝更新: primary={primary[-1].issue}, secondary={secondary[-1].issue}"
        )
    return len(overlap)


def build_canonical(progress: Callable[[str], None] | None = None):
    national_failure: str | None = None
    national = None
    try:
        national, national_receipt, raw_manifest = fetch_national_history(progress)
    except Exception as exc:
        national_failure = f"{type(exc).__name__}: {exc}"

    if national is not None:
        _validate_freshness(national)
        if progress:
            progress("江苏体彩交叉验证中")
        jiangsu, jiangsu_receipt, jiangsu_raw_evidence = fetch_jiangsu_recent(100)
        _validate_freshness(jiangsu)
        overlap_count = _crosscheck(national, jiangsu, 10)
        primary = national
        receipts = [national_receipt, jiangsu_receipt]
        source_mode = "national_plus_jiangsu"
        source_evidence = {
            "national_raw_manifest": raw_manifest,
            "jiangsu_raw_evidence": jiangsu_raw_evidence,
        }
    else:
        if progress:
            progress("国家体彩接口不可用，切换江苏完整历史 + 甘肃独立官方历史页")
        jiangsu_full, jiangsu_receipt, jiangsu_pages = fetch_jiangsu_history(progress)
        _validate_freshness(jiangsu_full)
        gansu, gansu_receipt, gansu_evidence = fetch_gansu_recent(20)
        _validate_freshness(gansu)
        overlap_count = _crosscheck(jiangsu_full, gansu, 10)
        primary = jiangsu_full
        receipts = [jiangsu_receipt, gansu_receipt]
        source_mode = "jiangsu_full_plus_gansu"
        source_evidence = {
            "national_failure": national_failure,
            "jiangsu_full_raw_manifest": jiangsu_pages,
            "gansu_raw_evidence": gansu_evidence,
        }

    payload = [d.to_dict() for d in primary]
    canonical_hash = sha256_json(payload)
    dataset = CanonicalDataset(
        draws=primary,
        canonical_hash=canonical_hash,
        receipts=receipts,
        crosscheck_count=overlap_count,
        crosscheck_status="PASS",
    )
    evidence = {
        "fetched_at": utc_now(),
        "canonical_hash": canonical_hash,
        "draw_count": len(primary),
        "latest": primary[-1].to_dict(),
        "freshness_gate": "PASS",
        "crosscheck_count": overlap_count,
        "crosscheck_status": "PASS",
        "network_gate": "PASS",
        "source_mode": source_mode,
        "schema": "dlt-official-source-evidence-v3",
        "parser_version": PARSER_VERSION,
        "source_receipts": [asdict(x) for x in dataset.receipts],
        **source_evidence,
        "canonical_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
    }
    return dataset, evidence
