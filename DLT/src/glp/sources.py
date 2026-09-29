from __future__ import annotations

import base64
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

import requests

from .constants import NATIONAL_URL
from .net_client import NetClient
from .domain import CanonicalDataset, Draw, SourceReceipt
from .util import canonical_json, sha256_bytes, sha256_json, utc_now

JIANGSU_DATA_PAGE = "https://api.js-lottery.com/wfzq/dlt/data"
JIANGSU_LIST_URL = "https://api.js-lottery.com/Lottery/_ListData"

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
JIANGSU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://api.js-lottery.com/",
}


class SourceError(RuntimeError):
    pass


NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_LATEST_AGE_DAYS = 10


def _attempts(response) -> list[dict]:
    value = getattr(response, "glp_attempts", ())
    return [dict(x) for x in value] if value else []


def _validate_http_payload(response, raw: bytes, *, allowed_types: tuple[str, ...]) -> dict:
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        raise SourceError(f"HTTP status not acceptable: {status}")
    if not raw:
        raise SourceError("官方源返回空响应")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise SourceError(f"官方源响应过大: {len(raw)} bytes")
    ctype = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
    if not any(kind in ctype for kind in allowed_types):
        raise SourceError(f"Content-Type 不符合契约: {ctype or 'missing'}")
    return {
        "http_status": status,
        "content_type": ctype,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "attempts": _attempts(response),
        "body_b64": base64.b64encode(raw).decode("ascii"),
    }


def _validate_freshness(draws: list[Draw], source: str) -> dict:
    if not draws:
        raise SourceError(f"{source} 无可验证开奖记录")
    try:
        latest = datetime.strptime(draws[-1].draw_date, "%Y-%m-%d").date()
    except Exception as exc:
        raise SourceError(f"{source} 最新开奖日期非法") from exc
    age = (datetime.now(timezone.utc).date() - latest).days
    if age < -1:
        raise SourceError(f"{source} 最新开奖日期位于未来: {draws[-1].draw_date}")
    if age > MAX_LATEST_AGE_DAYS:
        raise SourceError(f"{source} 数据过旧: latest={draws[-1].draw_date} age_days={age}")
    return {"latest_date": draws[-1].draw_date, "age_days": age, "max_age_days": MAX_LATEST_AGE_DAYS}


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


def _national_get(params: dict[str, str], session: requests.Session | None = None) -> requests.Response:
    client = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3, session=session) if session is not None else NET
    failures: list[str] = []
    for profile_index, profile in enumerate(NATIONAL_HEADER_PROFILES, start=1):
        try:
            response = client.get(NATIONAL_URL, params=params, headers=profile, timeout=(10, 30), allow_redirects=True)
            raw = bytes(response.content)
            _validate_http_payload(response, raw, allowed_types=("json",))
            return response
        except Exception as exc:
            attempts = getattr(exc, "glp_attempts", ())
            failures.append(
                f"profile_variant={profile_index} {type(exc).__name__}: {exc}; attempts={list(attempts)}"
            )
    raise SourceError(
        "国家体彩同一官方源的请求变体全部失败（header profile 不是独立来源）: "
        + " | ".join(failures[-4:])
    )


def fetch_national_page(page_no: int, session: requests.Session | None = None):
    params = {"gameNo": "85", "provinceId": "0", "pageSize": "100", "isVerify": "1", "pageNo": str(page_no)}
    response = _national_get(params, session)
    raw = bytes(response.content)
    raw_meta = _validate_http_payload(response, raw, allowed_types=("json",))
    try:
        payload = response.json()
    except Exception as exc:
        raise SourceError("国家体彩接口返回非 JSON: " + _response_fingerprint(response)) from exc
    if payload.get("success") is not True and str(payload.get("errorCode", "0")) not in {"0", "None"}:
        raise SourceError(f"国家体彩接口拒绝请求: {payload.get('errorCode')} {payload.get('errorMessage','')}")
    value = payload.get("value") or {}
    rows = value.get("list") or value.get("records") or []
    draws = [
        _parse_result(str(row.get("lotteryDrawNum")), str(row.get("lotteryDrawTime")), str(row.get("lotteryDrawResult")))
        for row in rows
    ]
    if page_no == 1 and not draws:
        raise SourceError("国家体彩第一页为空，拒绝把空响应当作成功")
    page_count = int(value.get("pages") or value.get("pageCount") or 1)
    total = int(value.get("total") or value.get("totalCount") or len(draws))
    return draws, raw, {
        "pages": page_count,
        "total": total,
        "response": _response_fingerprint(response),
        "raw": raw_meta,
    }


def fetch_national_history(progress: Callable[[str], None] | None = None):
    first, raw_first, meta = fetch_national_page(1)
    pages = int(meta["pages"])
    if pages < 1 or pages > 100:
        raise SourceError(f"国家体彩分页数异常: {pages}")
    if progress:
        progress(f"国家体彩主源：1/{pages} 页")
    page_results: dict[int, tuple[list[Draw], bytes, dict]] = {1: (first, raw_first, meta)}
    # Keep concurrency conservative to reduce WAF/rate-limit failures.
    if pages > 1:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_national_page, p): p for p in range(2, pages + 1)}
            done = 1
            for future in as_completed(futures):
                p = futures[future]
                draws, raw, page_meta = future.result()
                if int(page_meta["pages"]) != pages or int(page_meta["total"]) != int(meta["total"]):
                    raise SourceError(f"国家体彩分页元数据在请求期间变化: page={p}")
                page_results[p] = (draws, raw, page_meta)
                done += 1
                if progress and (done == pages or done % 5 == 0):
                    progress(f"国家体彩主源：{done}/{pages} 页")
    all_draws = [d for p in sorted(page_results) for d in page_results[p][0]]
    seen: dict[str, Draw] = {}
    for draw in all_draws:
        if draw.issue in seen:
            raise SourceError(f"国家体彩分页出现重复期号: {draw.issue}")
        seen[draw.issue] = draw
    ordered = sorted(seen.values(), key=lambda d: (d.draw_date, d.issue))
    if not ordered:
        raise SourceError("国家体彩历史为空")
    if meta["total"] and int(meta["total"]) != len(ordered):
        raise SourceError(f"主源总数不一致: API={meta['total']} 唯一记录={len(ordered)}")
    if any(ordered[i].draw_date >= ordered[i + 1].draw_date for i in range(len(ordered) - 1)):
        raise SourceError("国家体彩开奖日期非严格递增")
    freshness = _validate_freshness(ordered, "国家体彩")
    raw_manifest = [
        {"page": p, **page_results[p][2]["raw"]}
        for p in sorted(page_results)
    ]
    receipt = SourceReceipt(
        source="national", fetched_at=utc_now(), http_status=200,
        raw_sha256=sha256_bytes("".join(x["sha256"] for x in raw_manifest).encode()),
        draw_count=len(ordered), latest_issue=ordered[-1].issue, status="PASS",
        detail=f"官方分页 {pages} 页，总数/唯一性/时序一致；freshness_days={freshness['age_days']}；header profiles are request variants only",
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
    draws = []
    for day, issue, result in row_pattern.findall(text):
        try:
            draws.append(_parse_result(issue, day, result))
        except Exception:
            continue
    return sorted({d.issue: d for d in draws}.values(), key=lambda d: (d.draw_date, d.issue))


def fetch_jiangsu_recent(limit: int = 100):
    failures: list[str] = []
    # Two paths on the same Jiangsu official domain are fallback paths, not
    # independent sources. Cross-source consensus is National vs Jiangsu.
    for path_index, (url, params, extra_headers) in enumerate((
        (JIANGSU_DATA_PAGE, None, {}),
        (JIANGSU_LIST_URL, {"itemType": "lo", "pageIndex": "1", "pageSize": str(max(10, min(limit, 100)))}, {"X-Requested-With": "XMLHttpRequest", "Referer": JIANGSU_DATA_PAGE}),
    ), start=1):
        headers = dict(JIANGSU_HEADERS)
        headers.update(extra_headers)
        try:
            response = NET.get(url, params=params, headers=headers, timeout=(10, 30), allow_redirects=True)
            raw = bytes(response.content)
            raw_meta = _validate_http_payload(
                response,
                raw,
                allowed_types=("text/html", "application/xhtml+xml", "json"),
            )
            encoding = getattr(response, "encoding", None) or "utf-8"
            try:
                text = raw.decode(encoding)
            except (LookupError, UnicodeDecodeError) as exc:
                raise SourceError(f"江苏体彩响应编码非法: {encoding}") from exc
            draws = _parse_jiangsu_html(text)
            if len(draws) < 10:
                raise SourceError(f"江苏体彩解析记录不足: {len(draws)}")
            draws = draws[-max(10, min(limit, 100)):]
            freshness = _validate_freshness(draws, "江苏体彩")
            receipt = SourceReceipt(
                source="jiangsu", fetched_at=utc_now(), http_status=int(response.status_code),
                raw_sha256=sha256_bytes(raw), draw_count=len(draws), latest_issue=draws[-1].issue,
                status="PASS",
                detail=f"江苏体彩官方路径 {path_index} 解析成功；freshness_days={freshness['age_days']}",
            )
            return draws, receipt, {"path_index": path_index, "url": url, **raw_meta}
        except Exception as exc:
            attempts = getattr(exc, "glp_attempts", ())
            failures.append(url + f" {type(exc).__name__}: {exc}; attempts={list(attempts)}")
    raise SourceError("江苏体彩同一官方源两个路径均失败: " + " | ".join(failures[-4:]))


def build_canonical(progress: Callable[[str], None] | None = None):
    national, national_receipt, raw_manifest = fetch_national_history(progress)
    if progress:
        progress("江苏体彩交叉验证中")
    jiangsu, jiangsu_receipt, jiangsu_raw = fetch_jiangsu_recent(100)
    jm = {d.issue: d for d in jiangsu}
    overlap = [d for d in national if d.issue in jm]
    if len(overlap) < 10:
        raise SourceError("两个官方来源没有足够可交叉核对的共同期号")
    mismatches = [d.issue for d in overlap if d.to_dict() != jm[d.issue].to_dict()]
    if mismatches:
        raise SourceError("官方来源冲突，拒绝更新: " + ", ".join(mismatches[:10]))
    if national[-1].issue != jiangsu[-1].issue:
        raise SourceError(f"官方来源最新期不一致，拒绝更新: 国家体彩={national[-1].issue}, 江苏体彩={jiangsu[-1].issue}")
    payload = [d.to_dict() for d in national]
    canonical_hash = sha256_json(payload)
    dataset = CanonicalDataset(
        draws=national, canonical_hash=canonical_hash,
        receipts=[national_receipt, jiangsu_receipt], crosscheck_count=len(overlap), crosscheck_status="PASS",
    )
    evidence = {
        "fetched_at": utc_now(), "canonical_hash": canonical_hash, "draw_count": len(national),
        "latest": national[-1].to_dict(), "crosscheck_count": len(overlap), "crosscheck_status": "PASS",
        "network_gate": "PASS",
        "source_receipts": [asdict(x) for x in dataset.receipts],
        "national_raw_manifest": raw_manifest,
        "jiangsu_raw_evidence": jiangsu_raw,
        "canonical_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
    }
    return dataset, evidence
