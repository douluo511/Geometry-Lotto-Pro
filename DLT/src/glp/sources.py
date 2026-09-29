from __future__ import annotations

import base64
import html
import re
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
GUANGDONG_ANNOUNCEMENT = "https://www.gdlottery.cn/f_html/kjgg/P085_{issue}.html"

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
PARSER_VERSION = "dlt-source-parser-v2-fail-closed"

JIANGSU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://www.js-lottery.com/",
}
GUANGDONG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.gdlottery.cn/",
}


class SourceError(RuntimeError):
    pass


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


def _parse_jiangsu_html(text: str) -> list[Draw]:
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


def _parse_guangdong_announcement(text: str, expected_issue: str) -> Draw:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain).strip()
    issue = str(expected_issue)
    if not re.search(rf"第\s*{re.escape(issue)}\s*期.*?开奖公告", plain):
        raise SourceError(f"广东体彩公告期号不匹配: expected={issue}")

    mdate = re.search(r"开奖日期\s*[:：]?\s*(\d{4})[年-](\d{1,2})[月-](\d{1,2})日?", plain)
    if not mdate:
        raise SourceError(f"广东体彩 {issue} 未解析到开奖日期")
    draw_date = f"{int(mdate.group(1)):04d}-{int(mdate.group(2)):02d}-{int(mdate.group(3)):02d}"

    marker = plain.find("本期开奖号码")
    if marker < 0:
        raise SourceError(f"广东体彩 {issue} 未找到本期开奖号码")
    tail = plain[marker + len("本期开奖号码"):]
    stop = tail.find("本期中奖情况")
    if stop >= 0:
        tail = tail[:stop]
    nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", tail)]
    if len(nums) < 7:
        raise SourceError(f"广东体彩 {issue} 开奖号码不足 7 个")
    return _parse_result(issue, draw_date, " ".join(f"{n:02d}" for n in nums[:7]))


def fetch_guangdong_issue(issue: str):
    url = GUANGDONG_ANNOUNCEMENT.format(issue=issue)
    response = NET.get(url, headers=GUANGDONG_HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    meta = _validate_response(response, raw, expected="html_or_json")
    meta.update({
        "source_identity": "official_guangdong_sporttery",
        "requested_url": url,
        "issue": str(issue),
    })
    draw = _parse_guangdong_announcement(_decode_html(raw), str(issue))
    return draw, meta


def fetch_guangdong_recent(reference: list[Draw], limit: int = 10):
    if len(reference) < limit:
        raise SourceError("广东体彩交叉验证缺少参考期次")
    selected = reference[-int(limit):]
    draws: list[Draw] = []
    evidence: list[dict] = []
    for ref in selected:
        draw, meta = fetch_guangdong_issue(ref.issue)
        draws.append(draw)
        evidence.append(meta)
    receipt = SourceReceipt(
        source="guangdong",
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256=sha256_bytes("".join(x["sha256"] for x in evidence).encode()),
        draw_count=len(draws),
        latest_issue=draws[-1].issue,
        status="PASS",
        detail=f"广东体彩官方逐期开奖公告 {len(draws)} 期",
    )
    return draws, receipt, evidence


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
    try:
        national, national_receipt, raw_manifest = fetch_national_history(progress)
        if progress:
            progress("江苏体彩交叉验证中")
        jiangsu, jiangsu_receipt, jiangsu_raw_evidence = fetch_jiangsu_recent(100)
        overlap_count = _crosscheck(national, jiangsu, 10)
        primary = national
        receipts = [national_receipt, jiangsu_receipt]
        source_mode = "national_plus_jiangsu"
        source_evidence = {
            "national_raw_manifest": raw_manifest,
            "jiangsu_raw_evidence": jiangsu_raw_evidence,
        }
    except Exception as exc:
        national_failure = f"{type(exc).__name__}: {exc}"
        if progress:
            progress("国家体彩接口不可用，切换江苏完整历史 + 广东独立官方公告")
        jiangsu_full, jiangsu_receipt, jiangsu_pages = fetch_jiangsu_history(progress)
        guangdong, guangdong_receipt, guangdong_evidence = fetch_guangdong_recent(jiangsu_full, 10)
        overlap_count = _crosscheck(jiangsu_full, guangdong, 10)
        primary = jiangsu_full
        receipts = [jiangsu_receipt, guangdong_receipt]
        source_mode = "jiangsu_full_plus_guangdong"
        source_evidence = {
            "national_failure": national_failure,
            "jiangsu_full_raw_manifest": jiangsu_pages,
            "guangdong_raw_manifest": guangdong_evidence,
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
