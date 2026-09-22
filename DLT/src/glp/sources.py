from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable

import requests

from .constants import NATIONAL_URL
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
    sess = session or requests.Session()
    failures: list[str] = []
    for profile in NATIONAL_HEADER_PROFILES:
        try:
            response = sess.get(NATIONAL_URL, params=params, headers=profile, timeout=(10, 30), allow_redirects=True)
            if response.status_code >= 400:
                failures.append(_response_fingerprint(response))
                continue
            # WAF pages can return 200 HTML; reject them before JSON parsing.
            ctype = response.headers.get("Content-Type", "").lower()
            if "json" not in ctype and not response.text.lstrip().startswith("{"):
                failures.append("non-json " + _response_fingerprint(response))
                continue
            return response
        except requests.RequestException as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
    raise SourceError("国家体彩请求失败（已尝试移动/桌面官方 Referer）: " + " | ".join(failures[-4:]))


def fetch_national_page(page_no: int, session: requests.Session | None = None):
    params = {"gameNo": "85", "provinceId": "0", "pageSize": "100", "isVerify": "1", "pageNo": str(page_no)}
    response = _national_get(params, session)
    raw = response.content
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
    return draws, raw, {"pages": page_count, "total": total, "response": _response_fingerprint(response)}


def fetch_national_history(progress: Callable[[str], None] | None = None):
    first, raw_first, meta = fetch_national_page(1)
    pages = int(meta["pages"])
    if pages < 1 or pages > 100:
        raise SourceError(f"国家体彩分页数异常: {pages}")
    if progress:
        progress(f"国家体彩主源：1/{pages} 页")
    page_results: dict[int, tuple[list[Draw], bytes]] = {1: (first, raw_first)}
    # Keep concurrency conservative to reduce WAF/rate-limit failures.
    if pages > 1:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_national_page, p): p for p in range(2, pages + 1)}
            done = 1
            for future in as_completed(futures):
                p = futures[future]
                draws, raw, _ = future.result()
                page_results[p] = (draws, raw)
                done += 1
                if progress and (done == pages or done % 5 == 0):
                    progress(f"国家体彩主源：{done}/{pages} 页")
    all_draws = [d for p in sorted(page_results) for d in page_results[p][0]]
    unique = {d.issue: d for d in all_draws}
    ordered = sorted(unique.values(), key=lambda d: (d.draw_date, d.issue))
    if not ordered:
        raise SourceError("国家体彩历史为空")
    if meta["total"] and abs(int(meta["total"]) - len(ordered)) > 1:
        raise SourceError(f"主源总数不一致: API={meta['total']} 唯一记录={len(ordered)}")
    raw_manifest = [{"page": p, "sha256": sha256_bytes(page_results[p][1]), "bytes": len(page_results[p][1])} for p in sorted(page_results)]
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
    draws = []
    for day, issue, result in row_pattern.findall(text):
        try:
            draws.append(_parse_result(issue, day, result))
        except Exception:
            continue
    return sorted({d.issue: d for d in draws}.values(), key=lambda d: (d.draw_date, d.issue))


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
            response = requests.get(url, params=params, headers=headers, timeout=(10, 30), allow_redirects=True)
            if response.status_code >= 400:
                failures.append(url + " " + _response_fingerprint(response))
                continue
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
            return draws, receipt
        except requests.RequestException as exc:
            failures.append(url + f" {type(exc).__name__}: {exc}")
    raise SourceError("江苏体彩两个官方路径均失败: " + " | ".join(failures[-4:]))


def build_canonical(progress: Callable[[str], None] | None = None):
    national, national_receipt, raw_manifest = fetch_national_history(progress)
    if progress:
        progress("江苏体彩交叉验证中")
    jiangsu, jiangsu_receipt = fetch_jiangsu_recent(100)
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
        "source_receipts": [asdict(x) for x in dataset.receipts], "national_raw_manifest": raw_manifest,
        "canonical_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
    }
    return dataset, evidence
