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
GANSU_HISTORY_URL = "https://www.gstc.org.cn/wanfa/dlt_history"

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
            response = sess.get(NATIONAL_URL, params=params, headers=profile, timeout=(8, 20), allow_redirects=True)
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


def _parse_gansu_html(text: str) -> list[Draw]:
    plain = html.unescape(text)
    plain = re.sub(r"<script[^>]*>.*?</script>", " ", plain, flags=re.I | re.S)
    plain = re.sub(r"<style[^>]*>.*?</style>", " ", plain, flags=re.I | re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)

    draws: list[Draw] = []
    # Gansu's public history surface renders date, five-digit issue and seven
    # two-digit balls. Some templates concatenate the seven balls into 14 digits.
    pattern = re.compile(
        r"(20\d{2}-\d{2}-\d{2})\s+(\d{5})\s+((?:\d{14})|(?:(?:\d{1,2})\s+){6}(?:\d{1,2}))"
    )
    for day, issue, result in pattern.findall(plain):
        try:
            if re.fullmatch(r"\d{14}", result):
                nums = [int(result[i:i+2]) for i in range(0, 14, 2)]
                result_text = " ".join(str(x) for x in nums)
            else:
                result_text = result
            draws.append(_parse_result(issue, day, result_text))
        except Exception:
            continue
    return sorted({d.issue: d for d in draws}.values(), key=lambda d: (d.draw_date, d.issue))


def fetch_gansu_recent(limit: int = 100):
    headers = {
        "User-Agent": JIANGSU_HEADERS["User-Agent"],
        "Accept": JIANGSU_HEADERS["Accept"],
        "Referer": "https://www.gstc.org.cn/",
    }
    response = requests.get(GANSU_HISTORY_URL, headers=headers, timeout=(10, 30), allow_redirects=True)
    if response.status_code >= 400:
        raise SourceError("甘肃体彩历史页失败: " + _response_fingerprint(response))
    response.encoding = response.encoding or "utf-8"
    draws = _parse_gansu_html(response.text)
    if len(draws) < 10:
        raise SourceError(f"甘肃体彩历史页解析不足10期: parsed={len(draws)} " + _response_fingerprint(response))
    draws = draws[-max(10, min(limit, 100)):]
    receipt = SourceReceipt(
        source="gansu",
        fetched_at=utc_now(),
        http_status=response.status_code,
        raw_sha256=sha256_bytes(response.content),
        draw_count=len(draws),
        latest_issue=draws[-1].issue,
        status="PASS",
        detail="甘肃省体育彩票管理中心超级大乐透历史开奖页",
    )
    return draws, receipt


def _validate_consensus(a: list[Draw], b: list[Draw], min_overlap: int = 10) -> list[Draw]:
    bm = {d.issue: d for d in b}
    overlap = [d for d in a if d.issue in bm]
    if len(overlap) < min_overlap:
        raise SourceError(f"两个官方省级来源共同期号不足: {len(overlap)} < {min_overlap}")
    mismatches = [d.issue for d in overlap if d.to_dict() != bm[d.issue].to_dict()]
    if mismatches:
        raise SourceError("两个官方省级来源冲突: " + ", ".join(mismatches[:10]))
    if a[-1].issue != b[-1].issue or a[-1].to_dict() != b[-1].to_dict():
        raise SourceError(
            f"两个官方省级来源最新期不一致: 江苏={a[-1].issue}, 甘肃={b[-1].issue}"
        )
    return overlap


def build_canonical(
    progress: Callable[[str], None] | None = None,
    baseline_draws: list[Draw] | None = None,
):
    if progress:
        progress("江苏体彩 + 甘肃体彩双官方实时交叉核验…")
    jiangsu, jiangsu_receipt = fetch_jiangsu_recent(100)
    gansu, gansu_receipt = fetch_gansu_recent(100)
    provincial_overlap = _validate_consensus(jiangsu, gansu, min_overlap=10)

    national: list[Draw] | None = None
    national_receipt: SourceReceipt | None = None
    raw_manifest: list[dict] = []
    national_error = ""
    try:
        if progress:
            progress("国家体彩主源实时验证…")
        national, national_receipt, raw_manifest = fetch_national_history(progress)
    except Exception as exc:
        national_error = f"{type(exc).__name__}: {exc}"
        national_receipt = SourceReceipt(
            source="national",
            fetched_at=utc_now(),
            http_status=0,
            raw_sha256=sha256_bytes(national_error.encode("utf-8")),
            draw_count=0,
            latest_issue="",
            status="FAIL",
            detail=national_error,
        )

    receipts: list[SourceReceipt] = [national_receipt, jiangsu_receipt, gansu_receipt]
    verification = ""
    canonical_draws: list[Draw]

    if national is not None:
        jm = {d.issue: d for d in jiangsu}
        gm = {d.issue: d for d in gansu}
        overlap = [d for d in national if d.issue in jm and d.issue in gm]
        if len(overlap) < 10:
            raise SourceError("国家体彩与双省级来源共同期号不足")
        mismatches = [
            d.issue for d in overlap
            if d.to_dict() != jm[d.issue].to_dict() or d.to_dict() != gm[d.issue].to_dict()
        ]
        if mismatches:
            raise SourceError("国家体彩与省级官方来源冲突: " + ", ".join(mismatches[:10]))
        if not (national[-1].issue == jiangsu[-1].issue == gansu[-1].issue):
            raise SourceError(
                f"三官方来源最新期不一致: 国家={national[-1].issue}, 江苏={jiangsu[-1].issue}, 甘肃={gansu[-1].issue}"
            )
        canonical_draws = national
        crosscheck_count = len(overlap)
        verification = "NATIONAL_PLUS_JIANGSU_GANSU_CONSENSUS"
    else:
        if not baseline_draws:
            raise SourceError("国家体彩不可用且没有可信历史基线，拒绝构造 Canonical")
        baseline = list(baseline_draws)
        for d in baseline:
            d.validate()
        if len({d.issue for d in baseline}) != len(baseline):
            raise SourceError("可信基线存在重复期号")
        if any(baseline[i].draw_date >= baseline[i+1].draw_date for i in range(len(baseline)-1)):
            raise SourceError("可信基线时间顺序异常")

        jm = {d.issue: d for d in jiangsu}
        gm = {d.issue: d for d in gansu}

        # Advance a stale trusted baseline only with consecutive draws that are
        # independently identical on BOTH official provincial surfaces.  This
        # closes the common case where the bundled baseline is one or a few
        # draws behind the live 10-draw public window without weakening the
        # >=10 overlap gate below.
        baseline_map = {d.issue: d for d in baseline}
        last = baseline[-1]
        candidates = [
            d for d in provincial_overlap
            if d.issue not in baseline_map and d.draw_date > last.draw_date
        ]
        candidates.sort(key=lambda d: (d.draw_date, d.issue))

        def _is_next_issue(previous: str, current: str) -> bool:
            if not (re.fullmatch(r"\d{5}", previous) and re.fullmatch(r"\d{5}", current)):
                return False
            py, ps = int(previous[:2]), int(previous[2:])
            cy, cs = int(current[:2]), int(current[2:])
            return (cy == py and cs == ps + 1) or (cy == py + 1 and cs == 1)

        for draw in candidates:
            if not _is_next_issue(last.issue, draw.issue):
                raise SourceError(
                    f"可信基线到双官方共识存在期号缺口: baseline={last.issue}, next={draw.issue}"
                )
            if draw.to_dict() != jm[draw.issue].to_dict() or draw.to_dict() != gm[draw.issue].to_dict():
                raise SourceError(f"双官方候选推进期冲突: {draw.issue}")
            baseline_map[draw.issue] = draw
            last = draw

        extended_baseline = sorted(baseline_map.values(), key=lambda d: (d.draw_date, d.issue))

        # The extended baseline must still agree with both live official
        # surfaces on at least ten common draws.  The threshold is unchanged.
        recent_common = [d for d in extended_baseline if d.issue in jm and d.issue in gm]
        if len(recent_common) < 10:
            raise SourceError("可信基线与双官方实时来源共同期号不足")
        conflicts = [
            d.issue for d in recent_common
            if d.to_dict() != jm[d.issue].to_dict() or d.to_dict() != gm[d.issue].to_dict()
        ]
        if conflicts:
            raise SourceError("可信基线与实时官方来源冲突: " + ", ".join(conflicts[:10]))

        baseline_map = {d.issue: d for d in extended_baseline}
        consensus_map = {
            d.issue: d for d in provincial_overlap
            if d.to_dict() == gm[d.issue].to_dict()
        }
        for issue, draw in consensus_map.items():
            if issue in baseline_map and baseline_map[issue].to_dict() != draw.to_dict():
                raise SourceError(f"官方实时数据与可信基线冲突: {issue}")
            baseline_map[issue] = draw
        canonical_draws = sorted(baseline_map.values(), key=lambda d: (d.draw_date, d.issue))
        if canonical_draws[-1].issue != jiangsu[-1].issue:
            raise SourceError(
                f"双官方共识未能把 Canonical 推进到最新期: canonical={canonical_draws[-1].issue}, official={jiangsu[-1].issue}"
            )
        crosscheck_count = len(provincial_overlap)
        verification = "TRUSTED_BASELINE_PLUS_JIANGSU_GANSU_CONSENSUS"

    payload = [d.to_dict() for d in canonical_draws]
    canonical_hash = sha256_json(payload)
    dataset = CanonicalDataset(
        draws=canonical_draws,
        canonical_hash=canonical_hash,
        receipts=receipts,
        crosscheck_count=crosscheck_count,
        crosscheck_status="PASS",
    )
    evidence = {
        "fetched_at": utc_now(),
        "canonical_hash": canonical_hash,
        "draw_count": len(canonical_draws),
        "latest": canonical_draws[-1].to_dict(),
        "crosscheck_count": crosscheck_count,
        "crosscheck_status": "PASS",
        "network_gate": "PASS",
        "verification": verification,
        "source_receipts": [asdict(x) for x in receipts],
        "national_raw_manifest": raw_manifest,
        "canonical_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
    }
    return dataset, evidence
