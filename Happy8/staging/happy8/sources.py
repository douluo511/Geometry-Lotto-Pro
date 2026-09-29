from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .domain import Draw
from .net_client import NetClient


SHANGHAI_URL = "https://www.swlc.net.cn/lottery/kl8.html?limit=100&view=previous"
JIANGSU_URL = "https://www.jslottery.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8Evidence/0.2",
    "Accept": "text/html,application/xhtml+xml",
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
    nums = tuple(int(digits[i:i+2]) for i in range(0, 40, 2))
    return nums


def parse_shanghai_history(text: str) -> list[Draw]:
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
    if len(draws) < 20:
        raise RuntimeError(f"Shanghai official history parsed only {len(draws)} draws")
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
    # The current Jiangsu home page does not expose a machine-readable draw date
    # alongside the row. Use issue identity + numbers only for independent crosscheck.
    return Draw.from_values(issue, date.today().isoformat(), nums)


def fetch_shanghai() -> tuple[list[Draw], SourceReceipt]:
    response = NET.get(SHANGHAI_URL, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = _validate_html_response(response)
    response.encoding = response.encoding or "utf-8"
    draws = parse_shanghai_history(response.text)
    receipt = SourceReceipt(
        source="shanghai_welfare_lottery",
        url=SHANGHAI_URL,
        http_status=int(response.status_code),
        fetched_at=_utc_now(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        draw_count=len(draws),
        latest_issue=draws[-1].issue,
        status="PASS",
    )
    return draws, receipt


def fetch_jiangsu_latest() -> tuple[Draw, SourceReceipt]:
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
    return draw, receipt


def real_network_snapshot() -> dict[str, Any]:
    shanghai, shanghai_receipt = fetch_shanghai()
    jiangsu, jiangsu_receipt = fetch_jiangsu_latest()
    latest = shanghai[-1]
    if jiangsu.issue != latest.issue:
        raise RuntimeError(
            f"independent official sources latest issue mismatch: "
            f"Shanghai={latest.issue} Jiangsu={jiangsu.issue}"
        )
    if jiangsu.numbers != latest.numbers:
        raise RuntimeError(f"independent official sources conflict on {latest.issue}")
    age = (date.today() - datetime.strptime(latest.draw_date, "%Y-%m-%d").date()).days
    if age < 0 or age > 7:
        raise RuntimeError(f"official Happy8 latest draw is stale/future: age_days={age}")
    return {
        "schema": "happy8-staging-official-network-v1",
        "status": "PASS",
        "latest": latest.to_dict(),
        "history_count": len(shanghai),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "source_receipts": [shanghai_receipt.to_dict(), jiangsu_receipt.to_dict()],
        "note": "staging network gate only; portfolio Final still requires independent repository and full history/science/Windows gates",
    }
