from __future__ import annotations

import html as _html
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable, Iterable

import requests

from glp.net_client import NetClient
from glp.constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL
from glp.domain import CanonicalDataset, Draw, SourceReceipt
from glp.util import canonical_json, sha256_bytes, sha256_json, utc_now


class SourceError(RuntimeError):
    pass


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeometryLottoProSSQ/8.3",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
}
TIMEOUT = (20, 30)
NET = NetClient(connect_timeout=20, read_timeout=30, max_attempts=3)


def _issue(value: object) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"\d{5}", s):
        s = "20" + s
    if not re.fullmatch(r"20\d{5}", s):
        raise SourceError(f"非法双色球期号: {value!r}")
    return s


def _date(value: object) -> str:
    s = str(value or "")
    m = re.search(r"(20\d{2})[-/](\d{2})[-/](\d{2})", s)
    if not m:
        raise SourceError(f"非法开奖日期: {value!r}")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _balls(value: object, count: int) -> list[int]:
    if isinstance(value, (list, tuple)):
        nums = [int(x) for x in value]
    else:
        s = str(value or "").strip()
        # Shanghai renders the six reds as a 12-digit compact cell.
        if count == 6 and re.fullmatch(r"\d{12}", s):
            nums = [int(s[i:i + 2]) for i in range(0, 12, 2)]
        else:
            nums = [int(x) for x in re.findall(r"\d{1,2}", s)]
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


def _text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        decoded = None
        for enc in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                decoded = raw.decode(enc)
                break
            except UnicodeDecodeError:
                pass
        text = decoded if decoded is not None else raw.decode("utf-8", errors="replace")
    else:
        text = raw
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


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
        raw_sha256=sha256_bytes(detail.encode("utf-8")),
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


def fetch_national_page(page_no: int) -> tuple[list[Draw], bytes, int]:
    response = NET.get(NATIONAL_URL, params=_national_params(page_no), headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    raw = bytes(response.content)
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            raise SourceError("中国福彩网主源返回非 JSON") from exc
    if not isinstance(payload, dict):
        raise SourceError("中国福彩网主源结构改变")
    state = payload.get("state", 0)
    try:
        state_ok = int(state) == 0
    except Exception:
        state_ok = str(state).upper() in {"OK", "PASS", "SUCCESS"}
    rows = payload.get("result")
    if not state_ok or not isinstance(rows, list):
        raise SourceError("中国福彩网主源状态或结构改变")
    draws: list[Draw] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            draws.append(_draw(row.get("code"), row.get("date"), row.get("red"), row.get("blue")))
        except (SourceError, TypeError, ValueError):
            continue
    if not draws:
        raise SourceError("中国福彩网主源未解析到双色球记录")
    page_num = payload.get("pageNum")
    if page_num is None:
        total = payload.get("total")
        page_num = math.ceil(int(total) / 100) if total else 1
    try:
        pages = max(1, int(page_num))
    except Exception as exc:
        raise SourceError("中国福彩网页数无效") from exc
    return draws, raw, pages


def fetch_national_history(progress: Callable[[str], None] | None = None) -> tuple[list[Draw], SourceReceipt, list[dict]]:
    first, raw_first, pages = fetch_national_page(1)
    page_draws: dict[int, list[Draw]] = {1: first}
    raw_manifest = [{"page": 1, "sha256": sha256_bytes(raw_first), "bytes": len(raw_first)}]
    if progress:
        progress(f"中国福彩网主源：1/{pages} 页")
    if pages > 1:
        max_workers = min(6, pages - 1)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fetch_national_page, p): p for p in range(2, pages + 1)}
            for future in as_completed(futures):
                p = futures[future]
                draws, raw, reported_pages = future.result()
                if reported_pages != pages:
                    raise SourceError("中国福彩网分页数量在请求期间发生变化")
                page_draws[p] = draws
                raw_manifest.append({"page": p, "sha256": sha256_bytes(raw), "bytes": len(raw)})
                if progress:
                    progress(f"中国福彩网主源：{len(page_draws)}/{pages} 页")
    unique: dict[str, Draw] = {}
    for p in sorted(page_draws):
        for d in page_draws[p]:
            prev = unique.get(d.issue)
            if prev is not None and not _same_draw(prev, d):
                raise SourceError(f"中国福彩网主源同一期数据自相矛盾: {d.issue}")
            unique[d.issue] = d
    ordered = sorted(unique.values(), key=lambda d: (d.draw_date, d.issue))
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
    # Current official page table: issue | date(day) | 12 compact red digits | 2 blue digits.
    compact = re.compile(r"(20\d{5})\s+(20\d{2}-\d{2}-\d{2})(?:\([^)]*\))?\s+(\d{12})\s+(\d{2})(?!\d)")
    for m in compact.finditer(text):
        try:
            draws.append(_draw(m.group(1), m.group(2), m.group(3), m.group(4)))
        except SourceError:
            pass
    if draws:
        return sorted({d.issue: d for d in draws}.values(), key=lambda d: (d.draw_date, d.issue))

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
        for start in range(max(0, min(4, len(nums) - 6)) + 1):
            group = nums[start:start + 7]
            if len(group) < 7:
                break
            try:
                draws.append(_draw(im.group(0), dm.group(0), group[:6], [group[6]]))
                break
            except SourceError:
                continue
    if not draws:
        raise SourceError("上海福彩双色球专页解析失败")
    return sorted({d.issue: d for d in draws}.values(), key=lambda d: (d.draw_date, d.issue))


def fetch_shanghai_history() -> tuple[list[Draw], SourceReceipt, bytes]:
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.swlc.net.cn/"
    response = NET.get(SHANGHAI_URL, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    raw = bytes(response.content)
    draws = parse_shanghai_history(raw)
    receipt = _response_receipt(
        "official_shanghai_L1", response, raw, len(draws), draws[-1].issue,
        "上海市福利彩票发行中心 双色球往期开奖专页",
    )
    return draws, receipt, raw


def _hebei_home_snapshot(raw: bytes | str) -> dict:
    # Parse only the draw panel. News headlines contain unrelated prize amounts.
    markup = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
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
    for i in range(max(1, len(nums) - 6)):
        group = nums[i:i + 7]
        if len(group) < 7:
            break
        reds, blue = group[:6], group[6]
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


def fetch_hebei_latest() -> tuple[Draw, SourceReceipt, dict]:
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.yzfcw.com/"
    home_response = NET.get(HEBEI_URL, headers=headers, timeout=TIMEOUT)
    home_response.raise_for_status()
    announce_response = NET.get(HEBEI_ANNOUNCE_URL, headers=headers, timeout=TIMEOUT)
    announce_response.raise_for_status()
    home_raw = bytes(home_response.content)
    announce_raw = bytes(announce_response.content)
    draw = parse_hebei_latest(home_raw, announce_raw)
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
) -> tuple[CanonicalDataset, dict]:
    receipts: list[SourceReceipt] = []
    errors: dict[str, str] = {}
    national_draws: list[Draw] | None = None
    shanghai_draws: list[Draw] | None = None
    hebei_draw: Draw | None = None
    raw_manifest: list[dict] = []

    if progress:
        progress("真实官方网络：连接中国福彩网主源…")
    try:
        national_draws, receipt, raw_manifest = fetch_national_history(progress)
        receipts.append(receipt)
    except Exception as exc:
        errors["national"] = f"{type(exc).__name__}: {exc}"
        receipts.append(_failed_receipt("official_cwl_L0", errors["national"]))

    if progress:
        progress("真实官方网络：连接上海福彩双色球专页…")
    try:
        shanghai_draws, receipt, _ = fetch_shanghai_history()
        receipts.append(receipt)
    except Exception as exc:
        errors["shanghai"] = f"{type(exc).__name__}: {exc}"
        receipts.append(_failed_receipt("official_shanghai_L1", errors["shanghai"]))

    if progress:
        progress("真实官方网络：连接河北福彩双色球专页…")
    try:
        hebei_draw, receipt, _ = fetch_hebei_latest()
        receipts.append(receipt)
    except Exception as exc:
        errors["hebei"] = f"{type(exc).__name__}: {exc}"
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
        # Hardened fallback: do not turn a temporary CWL API 403 into an app-wide outage.
        # It is allowed only when the trusted baseline overlaps Shanghai's official
        # 100-draw window, and Shanghai's newest draw independently matches Hebei.
        if shanghai_draws is None or hebei_draw is None:
            raise SourceError("中国福彩主源不可用时，上海+河北双官方补偿链必须同时可用；诊断=" + json.dumps(errors, ensure_ascii=False))
        if not _same_draw(shanghai_draws[-1], hebei_draw):
            raise SourceError(
                f"省级双官方源最新期冲突，拒绝更新: Shanghai={shanghai_draws[-1].issue} Hebei={hebei_draw.issue}"
            )
        canonical_draws, overlap = _merge_trusted_baseline(baseline_draws or (), shanghai_draws)
        crosscheck_count = overlap + 1
        verification = "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS"

    if not canonical_draws:
        raise SourceError("Canonical Dataset 为空")
    for i in range(len(canonical_draws) - 1):
        if canonical_draws[i].draw_date >= canonical_draws[i + 1].draw_date:
            raise SourceError("Canonical Dataset 日期非严格递增")

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
        "schema": "official-source-evidence-v8.3",
        "game": "SSQ",
        "fetched_at": utc_now(),
        "canonical_hash": canonical_hash,
        "draw_count": len(canonical_draws),
        "latest": canonical_draws[-1].to_dict(),
        "crosscheck_count": int(crosscheck_count),
        "crosscheck_status": "PASS",
        "verification": verification,
        "source_receipts": [asdict(r) for r in receipts],
        "source_errors": errors,
        "national_raw_manifest": raw_manifest,
        "canonical_payload_sha256": sha256_bytes(canonical_json(draw_dicts).encode("utf-8")),
    }
    return dataset, evidence
