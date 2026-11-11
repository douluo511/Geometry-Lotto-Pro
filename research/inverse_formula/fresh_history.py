"""Fail-closed official provincial lottery draw synchronization (research only).

Uses the visible historical tables of Shanghai Welfare Lottery (SSQ) and
Jiangsu Sports Lottery (DLT). HTML changes, source disagreement, stale
publication or missing intervening issues abort BEFORE any paid API call.
No V4.7 files are edited. Never silently fills an unavailable result.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta, time, timezone
from html.parser import HTMLParser
from pathlib import Path

from research.inverse_formula.probe import Draw, Game, SSQ, DLT, load_history

SOURCES = {
    "SSQ": "https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
    "DLT": "https://api.js-lottery.com/wfzq/dlt/data",
}
CHINA = timezone(timedelta(hours=8))


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", " ".join(self.cell)).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def _balls(cell: str, count: int) -> tuple[int, ...] | None:
    clean = re.sub(r"\s+", "", cell)
    if re.fullmatch(r"\d{" + str(2 * count) + r"}", clean):
        return tuple(int(clean[i:i+2]) for i in range(0, len(clean), 2))
    return None


def parse_official_rows(html: str, game: Game) -> list[dict]:
    parser = _TableRows()
    parser.feed(html)
    records: dict[int, dict] = {}
    for cells in parser.rows:
        date_cells = [c for c in cells if re.search(r"20\d{2}-\d{2}-\d{2}", c)]
        issue_pattern = r"20\d{5}" if game.name == "SSQ" else r"\d{5}"
        issue_cells = [c for c in cells if re.fullmatch(issue_pattern, c)]
        if not date_cells or not issue_cells:
            continue
        issue = int(issue_cells[0])
        date_str = re.search(r"20\d{2}-\d{2}-\d{2}", date_cells[0]).group()
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if game.name == "SSQ":
            reds = [(i, _balls(c, 6)) for i, c in enumerate(cells)]
            reds = [(i, values) for i, values in reds if values is not None]
            if len(reds) != 1 or reds[0][0] + 1 >= len(cells):
                raise ValueError("ambiguous official SSQ winning cells")
            front = reds[0][1]
            back = _balls(cells[reds[0][0] + 1], 1)
        else:
            seven = [_balls(c, 7) for c in cells]
            seven = [v for v in seven if v is not None]
            if len(seven) != 1:
                raise ValueError("ambiguous official DLT winning cells")
            front, back = seven[0][:5], seven[0][5:]
        if back is None:
            raise ValueError("missing official back numbers")
        if (len(front) != game.front_pick or len(back) != game.back_pick
                or tuple(sorted(set(front))) != front
                or tuple(sorted(set(back))) != back
                or any(not 1 <= n <= game.front_max for n in front)
                or any(not 1 <= n <= game.back_max for n in back)):
            raise ValueError("invalid official table ticket")
        item = {"issue": issue, "date": date_str,
                "front": list(front), "back": list(back)}
        if issue in records and records[issue] != item:
            raise ValueError("conflicting official duplicate issue")
        records[issue] = item
    if not records:
        raise ValueError("could not parse any official draw table rows")
    return [records[x] for x in sorted(records)]


def expected_last_published_date(game: Game, now: datetime):
    """Only published draw days past 22:30 Beijing time are mandatory."""
    local = now.astimezone(CHINA)
    weekdays = {1, 3, 6} if game.name == "SSQ" else {0, 2, 5}
    for delta in range(10):
        date = local.date() - timedelta(days=delta)
        if date.weekday() in weekdays and (
                delta > 0 or local.time() >= time(22, 30)):
            return date
    raise AssertionError("no scheduled draw day found")


def fetch_official_html(game: Game) -> tuple[str, str]:
    url = SOURCES[game.name]
    req = urllib.request.Request(url, headers={
        "User-Agent": "SSQDLT-Research-Auditor/1.0 (readonly)",
        "Accept": "text/html",
    })
    # Network-only retries; never retry a paid model call. A transient
    # official issuer outage must not lead to silent use of stale fixtures.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=18) as response:
                if response.url.split("/")[2].lower() != url.split("/")[2].lower():
                    raise RuntimeError(
                        "official source redirected to another domain")
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("official page exceeds size cap")
            return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise RuntimeError(
                    "official source unreachable after 3 free HTTP attempts") from None
            time.sleep(1 + attempt)
    raise AssertionError("unreachable official-source fetch state")


def _line(row: Draw) -> str:
    return (f"{row.issue}:" + "".join(f"{n:02d}" for n in row.front)
            + "+" + "".join(f"{n:02d}" for n in row.back))


def sync_fixture(history: Path, game: Game, destination: Path, *,
                 html: str | None = None, now: datetime | None = None) -> dict:
    """Update a temporary copy of research history, validating all overlaps."""
    if now is None:
        now = datetime.now(CHINA)
    if html is None:
        html, page_sha = fetch_official_html(game)
    else:
        page_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    official = parse_official_rows(html, game)
    last = official[-1]
    published = datetime.strptime(last["date"], "%Y-%m-%d").date()
    if published > now.astimezone(CHINA).date():
        raise ValueError("official draw date is in the future")
    if published < expected_last_published_date(game, now):
        raise ValueError("official table is stale; stop before model calls")
    known, old_hash = load_history(history, game)
    old = {row.issue: row for row in known}
    incoming = {r["issue"]: Draw(r["issue"], tuple(r["front"]), tuple(r["back"]))
                for r in official}
    overlap = set(old) & set(incoming)
    if not overlap:
        raise ValueError("no overlap with existing research fixture")
    if any(old[i] != incoming[i] for i in overlap):
        raise ValueError("official result conflicts with known fixture")
    if last["issue"] < known[-1].issue:
        raise ValueError("official table is behind existing fixture")
    new = []
    for issue in range(known[-1].issue + 1, last["issue"] + 1):
        if issue not in incoming:
            raise ValueError("missing consecutive official issue in update")
        new.append(incoming[issue])
    merged = known + new
    if destination.exists():
        raise FileExistsError("refusing to overwrite research history")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(";".join(_line(row) for row in merged) + "\n",
                           encoding="utf-8", newline="\n")
    confirmed, sha = load_history(destination, game)
    if confirmed != merged:
        raise AssertionError("roundtrip history checksum failed")
    return {
        "game": game.name, "source_url": SOURCES[game.name],
        "source_html_sha256": page_sha, "old_fixture_sha256": old_hash,
        "merged_history_sha256": sha, "verified_overlap_count": len(overlap),
        "new_issues": len(new), "asof_issue": merged[-1].issue,
        "target_issue": merged[-1].issue + 1,
        "latest_published_date": last["date"],
        "official_page_fetched_utc": now.astimezone(timezone.utc).isoformat(),
        "source_authentication": "PUBLIC_PROVINCIAL_ISSUER_PAGE_NOT_INDEPENDENT_ATTESTATION",
        "no_edge": True,
    }
