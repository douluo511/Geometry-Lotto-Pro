"""Issuer-HTML physical draw observations; research only, never a forecast.

Every attempted issue gets a create-only receipt. Original response bytes are
content-addressed. Structural parsing fails closed and keeps order distinct
from the official sorted combination. Publication/redemption dates are NEVER
substituted for the explicit draw-date field.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from research.supercompute.automation.physical_transport import (
    TransportExhausted, dlt_fetch,
)

PARSER = "GD_DLT_PHYSICAL_ANNOUNCEMENT_V1"
HOST = "www.gdlottery.cn"
MAX_BYTES = 1_200_000
ISSUE = re.compile(r"\d{5}\Z")
NUM = re.compile(r"(?<!\d)\d{1,2}(?!\d)")


class Blocked(ValueError):
    """A failed source/parsing/immutability gate."""


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"td", "th", "tr", "br", "p", "div", "li"}:
            self.chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th", "tr", "p", "div", "li"}:
            self.chunks.append(" ")


def source_url(issue: str) -> str:
    if not isinstance(issue, str) or not ISSUE.fullmatch(issue):
        raise Blocked("ISSUE_FORMAT_INVALID")
    return f"https://{HOST}/f_html/kjgg/P085_{issue}.html"


def _numbers(fragment: str, expected: int) -> tuple[int, ...]:
    # Reject extra digits or unexpected stray text in the official draw cells.
    values = tuple(map(int, NUM.findall(fragment)))
    if len(values) != expected:
        raise Blocked("DRAW_BALL_COUNT_INVALID")
    remaining = NUM.sub("", fragment)
    if re.search(r"[^\s:：,，;；|前区后区]", remaining):
        raise Blocked("DRAW_BALL_TEXT_INVALID")
    return values


def _ball_domain(values: tuple[int, ...], high: int) -> bool:
    return len(set(values)) == len(values) and all(1 <= n <= high for n in values)


def parse_announcement(raw: bytes, expected_issue: str) -> dict:
    source_url(expected_issue)
    if not raw or len(raw) > MAX_BYTES:
        raise Blocked("SOURCE_BYTES_INVALID")
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise Blocked("SOURCE_ENCODING_INVALID") from exc
    # Remove script/style content before reading visible official page text.
    decoded = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", decoded,
                     flags=re.I | re.S)
    parser = PlainText()
    parser.feed(decoded)
    parser.close()
    text = re.sub(r"\s+", " ", "".join(parser.chunks)).strip()
    headings = re.findall(r"第(\d{5})期开奖公告", text)
    if expected_issue not in headings or set(headings) != {expected_issue}:
        raise Blocked("ANNOUNCEMENT_ISSUE_MISMATCH")
    matches = re.findall(r"开奖日期\s*[：:]?\s*(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?", text)
    if len(matches) != 1:
        raise Blocked("DRAW_DATE_MISSING_OR_AMBIGUOUS")
    try:
        draw_date = date(*map(int, matches[0])).isoformat()
    except ValueError as exc:
        raise Blocked("DRAW_DATE_INVALID") from exc
    groups = re.findall(r"本期使用第\s*(\d{1,2})\s*套摇奖球", text)
    if len(groups) != 1 or not 1 <= int(groups[0]) <= 9:
        raise Blocked("BALL_GROUP_MISSING_OR_AMBIGUOUS")
    order = re.findall(r"本期出球顺序\s*[：:]?\s*(.*?)\s*本期开奖号码\s*[：:]?", text)
    sorted_fields = re.findall(r"本期开奖号码\s*[：:]?\s*(.*?)\s*本期中奖情况", text)
    if len(order) != 1 or len(sorted_fields) != 1:
        raise Blocked("DRAW_FIELDS_MISSING_OR_AMBIGUOUS")
    # The two cells from each row contain 5 front and 2 back numbers.
    ordered = _numbers(order[0], 7)
    ascending = _numbers(sorted_fields[0], 7)
    front, back = ordered[:5], ordered[5:]
    sorted_front, sorted_back = ascending[:5], ascending[5:]
    if (not _ball_domain(front, 35) or not _ball_domain(back, 12)
            or sorted_front != tuple(sorted(front))
            or sorted_back != tuple(sorted(back))):
        raise Blocked("DRAW_DOMAIN_OR_ORDER_CONFLICT")
    return {
        "schema": PARSER,
        "game": "DLT",
        "issue": expected_issue,
        "draw_date": draw_date,
        "ball_group": int(groups[0]),
        "front_order": list(front),
        "back_order": list(back),
        "front_sorted": list(sorted_front),
        "back_sorted": list(sorted_back),
    }


def _sealed_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, allow_nan=False,
                       sort_keys=True, indent=2) + "\n").encode("utf-8")


def _create_once(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # x/b means O_EXCL; an existing value is never silently replaced.
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        return True
    except FileExistsError:
        if path.read_bytes() == data:
            return False
        raise Blocked("IMMUTABLE_FILE_CONFLICT")


def fetch_http(url: str) -> tuple[int, str, bytes]:
    request = Request(url, headers={
        "User-Agent": "Geometry-Lotto-Pro-Physical-Audit/1.0",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.geturl(), response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        return exc.code, exc.geturl(), exc.read(MAX_BYTES + 1)


def collect(issue: str, ledger: Path, *, fetcher=dlt_fetch) -> dict:
    url = source_url(issue)
    observed_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema": PARSER,
        "issue": issue,
        "requested_url": url,
        "observed_at_utc": observed_at,
        "parser_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "http_status": None,
        "transport_attempts": [],
        "response_sha256": None,
        "final_url": None,
        "status": "BLOCKED",
        "reason": None,
        "formal_A": 0,
        "predictive_edge": "NO_EDGE",
    }
    try:
        fetched = fetcher(url)
        if len(fetched) == 5:
            http_status, final_url, raw, receipt["transport_attempts"] = fetched[:4]
            for digest, body in fetched[4].items():
                if sha256(body).hexdigest() != digest:
                    raise Blocked("TRANSPORT_RAW_HASH_MISMATCH")
                _create_once(ledger / "raw" / (digest + ".bin"), body)
        elif len(fetched) == 4:
            http_status, final_url, raw, receipt["transport_attempts"] = fetched
        else:
            http_status, final_url, raw = fetched
        receipt["http_status"] = http_status
        receipt["final_url"] = final_url
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
            raise Blocked("HTTP_RESPONSE_BYTES_INVALID")
        digest = sha256(raw).hexdigest()
        receipt["response_sha256"] = digest
        _create_once(ledger / "raw" / (digest + ".bin"), raw)
        parts = urlsplit(final_url)
        if parts.scheme != "https" or parts.hostname not in (HOST, "gdlottery.cn") or parts.path != urlsplit(url).path:
            raise Blocked("UNTRUSTED_SOURCE_REDIRECT")
        if http_status != 200:
            raise Blocked("OFFICIAL_HTTP_NON_200")
        parsed = parse_announcement(raw, issue)
        parsed.update({"source_url": final_url, "source_sha256": digest})
        target = ledger / "draws" / (issue + ".json")
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            # Same issue + same physical fields, even if page boilerplate changes.
            keys = ("game", "issue", "draw_date", "ball_group", "front_order",
                    "back_order", "front_sorted", "back_sorted")
            if any(parsed[k] != existing.get(k) for k in keys):
                raise Blocked("DRAW_OBSERVATION_CONFLICT")
            receipt["status"] = "MATCHED_EXISTING"
        else:
            if not _create_once(target, _sealed_bytes(parsed)):
                raise Blocked("DRAW_CREATE_RACE")
            receipt["status"] = "RECORDED"
    except Exception as exc:
        if isinstance(exc, TransportExhausted):
            receipt["transport_attempts"] = exc.attempts
            for digest, body in exc.raw_bodies.items():
                if sha256(body).hexdigest() != digest:
                    raise Blocked("TRANSPORT_RAW_HASH_MISMATCH")
                _create_once(ledger / "raw" / (digest + ".bin"), body)
            if exc.attempts:
                last = exc.attempts[-1]
                receipt["http_status"] = last.get("http_status")
                receipt["final_url"] = last.get("final_url")
                receipt["response_sha256"] = last.get("response_sha256")
        receipt["status"] = "BLOCKED"
        receipt["reason"] = str(exc) if isinstance(exc, Blocked) else "NETWORK_OR_IO_FAILURE:" + type(exc).__name__
    finally:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = ledger / "attempts" / issue / (stamp + "-" + uuid4().hex + ".json")
        _create_once(target, _sealed_bytes(receipt))
    return receipt


def verify(ledger: Path) -> dict:
    checked = 0
    for path in (ledger / "draws").glob("*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        digest = item.get("source_sha256", "")
        raw_path = ledger / "raw" / (digest + ".bin")
        if (not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not raw_path.is_file()
                or sha256(raw_path.read_bytes()).hexdigest() != digest):
            raise Blocked("MISSING_OR_TAMPERED_SOURCE_BYTES")
        parsed = parse_announcement(raw_path.read_bytes(), item["issue"])
        if any(item.get(key) != value for key, value in parsed.items()):
            raise Blocked("TAMPERED_DRAW_RECORD")
        if path.name != item["issue"] + ".json":
            raise Blocked("DRAW_FILENAME_MISMATCH")
        checked += 1
    for path in (ledger / "attempts").glob("*/*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        digest = row.get("response_sha256")
        if digest:
            raw = ledger / "raw" / (digest + ".bin")
            if not raw.is_file() or sha256(raw.read_bytes()).hexdigest() != digest:
                raise Blocked("TAMPERED_ATTEMPT_SOURCE")
    return {"schema": PARSER, "draws_verified": checked,
            "formal_A": 0, "predictive_edge": "NO_EDGE"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.ledger), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.issue:
        parser.error("at least one explicit --issue is required; never infer issue IDs")
    failed = False
    for issue in args.issue:
        result = collect(issue, args.ledger)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        failed |= result["status"] == "BLOCKED"
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
