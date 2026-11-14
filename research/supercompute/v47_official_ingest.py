"""Read two real provincial lottery publisher HTML tables with strict evidence.

Fetches do not authenticate a signed issuer feed. HTTPS, publisher domain,
response digest, issuer-table overlap and chronological continuity are checked.
Non-200, timeouts, unexpected HTML or conflicts write create-only failures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from research.supercompute.v47_models import canonical, validate_history, validate_ticket

SOURCES = {
    "ssq": ("https://www.swlc.net.cn/lottery/ssq.html?limit=100&view=previous",
            "www.swlc.net.cn"),
    "dlt": ("https://www.js-lottery.com/wfzq/dlt/data", "www.js-lottery.com"),
}
PARSER_ID = "v47-provincial-html-table-v1"
MAX_RESPONSE_BYTES = 3_000_000
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
TWO_DIGIT = re.compile(r"\d{2}")


class ResultTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None and self.cell is None:
            self.cell = []
            self.depth = 1
        elif self.cell is not None:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.cell is not None:
            self.depth -= 1
            if tag == "td" and self.depth <= 0:
                self.row.append("".join(self.cell).strip())
                self.cell = None
                self.depth = 0
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def parse_publisher_table(game, raw):
    if game not in SOURCES:
        raise ValueError("unknown lottery")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("official publisher HTML too large")
    doc = ResultTable()
    doc.feed(raw.decode("utf-8-sig", errors="strict"))
    rows = []
    for cells in doc.rows:
        if game == "ssq":
            if len(cells) < 4 or not re.fullmatch(r"20\d{5}", cells[0]):
                continue
            match = DATE.search(cells[1])
            red = [int(x) for x in TWO_DIGIT.findall(cells[2])]
            blue = [int(x) for x in TWO_DIGIT.findall(cells[3])]
            issue = cells[0]
            if not match or len(red) != 6 or len(blue) != 1:
                raise ValueError("malformed SSQ issuer row " + issue)
            front, back = red, blue
        else:
            if (len(cells) < 3 or not DATE.fullmatch(cells[0])
                    or not re.fullmatch(r"\d{5}", cells[1])):
                continue
            match = DATE.search(cells[0])
            balls = [int(x) for x in TWO_DIGIT.findall(cells[2])]
            issue = cells[1]
            if len(balls) != 7:
                raise ValueError("malformed DLT issuer row " + issue)
            front, back = balls[:5], balls[5:]
        row = {"issue": issue, "draw_date": match.group(1),
               "front": front, "back": back}
        validate_ticket(row, game)
        rows.append(row)
    if not rows:
        raise ValueError("no legal draws in publisher table " + game)
    if len(set(r["issue"] for r in rows)) != len(rows):
        raise ValueError("duplicate publisher issue")
    return sorted(rows, key=lambda r: int(r["issue"]))


def fetch_publisher(game, *, timeout=16):
    url, domain = SOURCES[game]
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; SSQDLT-V47-Research-Audit/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        effective = resp.geturl()
        actual_domain = urllib.parse.urlsplit(effective).hostname
        content_type = resp.headers.get("Content-Type", "").split(";")[0].lower()
        if (status != 200 or actual_domain != domain
                or content_type not in ("text/html", "application/xhtml+xml")):
            raise ValueError("untrusted issuer HTTP response/domain/content-type")
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("issuer response too large")
    return raw, {"source_url": url, "effective_url": effective,
                 "http_status": status, "content_type": content_type,
                 "raw_sha256": hashlib.sha256(raw).hexdigest(),
                 "bytes": len(raw), "fetched_utc": datetime.now(timezone.utc).isoformat(),
                 "parser_id": PARSER_ID}


def append_verified(base, fetched, game, *, minimum_overlap=3):
    validate_history(base, game)
    known = {str(x["issue"]): x for x in base}
    overlaps = [x for x in fetched if x["issue"] in known]
    if len(overlaps) < minimum_overlap:
        raise ValueError("insufficient overlap with frozen history")
    for row in overlaps:
        if any(known[row["issue"]][key] != row[key]
               for key in ("front", "back", "draw_date")):
            raise ValueError("publisher/seed conflict at " + row["issue"])
    last_issue = int(base[-1]["issue"])
    new = [x for x in fetched if int(x["issue"]) > last_issue]
    for index, row in enumerate(new, 1):
        if (int(row["issue"]) != last_issue + index
                or row["draw_date"] <= (new[index - 2]["draw_date"]
                    if index > 1 else base[-1]["draw_date"])):
            raise ValueError("new published issues are not gap-free")
    joined = base + new
    validate_history(joined, game)
    return joined, {"overlap_count": len(overlaps),
                    "added_count": len(new),
                    "publisher_last_issue": fetched[-1]["issue"],
                    "merged_last_issue": joined[-1]["issue"],
                    "latest_issue_matched": fetched[-1]["issue"] == joined[-1]["issue"],
                    "new_target_issue": str(int(joined[-1]["issue"]) + 1)}


def _store(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(canonical(data))


def ingest(base_paths, out_dir, *, fetch=fetch_publisher, minimum_overlap=3):
    """All-or-nothing validated snapshot, partial failures never accepted."""
    root = Path(out_dir)
    base_hashes, joined, evidence = {}, {}, {}
    for game in ("ssq", "dlt"):
        try:
            base_raw = Path(base_paths[game]).read_bytes()
            base = json.loads(base_raw)["draws"]
            base_hashes[game] = hashlib.sha256(base_raw).hexdigest()
            raw, fetch_receipt = fetch(game)
            fetched = parse_publisher_table(game, raw)
            history, check = append_verified(
                base, fetched, game, minimum_overlap=minimum_overlap)
            joined[game] = history
            evidence[game] = {**fetch_receipt, **check,
                "history_sha256": hashlib.sha256(canonical(history)).hexdigest(),
                "source_review": "ISSUER_PUBLISHED_HTML_NOT_SIGNED_FEED"}
        except Exception as exc:
            diagnostics = {}
            if "raw" in locals() and isinstance(raw, bytes):
                title = re.search(br"<title[^>]*>([^<]{0,200})</title>",
                                  raw, re.IGNORECASE)
                diagnostics = {
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "response_bytes": len(raw),
                    "contains_expected_issue_2026": b"2026" in raw,
                    "html_title": (
                        title.group(1).decode("utf-8", errors="replace")
                        if title else None),
                }
            if "fetch_receipt" in locals():
                diagnostics["http_status"] = fetch_receipt.get("http_status")
                diagnostics["effective_url"] = fetch_receipt.get("effective_url")
            error = {"schema": "SSQDLT_V47_LIVE_FETCH_FAILURE_V1",
                     "game": game, "source_url": SOURCES[game][0],
                     "http_diagnostics": diagnostics,
                     "parser_id": PARSER_ID, "failure_type": type(exc).__name__,
                     "failure_message": str(exc)[:350],
                     "recorded_utc": datetime.now(timezone.utc).isoformat(),
                     "partial_results_accepted": False,
                     "official_source_verified": False}
            _store(root / "failure-receipt.json", error)
            raise
    snapshots = {}
    for game in ("ssq", "dlt"):
        content = {"game": game.upper(), "draws": joined[game],
                   "source_status": "PUBLISHER_HTML_OVERLAP_VERIFIED_NOT_SIGNED",
                   "source_receipt": evidence[game]}
        snapshots[game] = content
    receipt = {"schema": "SSQDLT_V47_LIVE_ISSUER_INGEST_V1",
               "status": "OVERLAP_VERIFIED",
               "publisher_issues_matched": True,
               "signed_official_data_verified": False,
               "games": evidence, "base_sha256": base_hashes}
    # Check absence of all output paths before writing.
    outputs = [root / (g + "-verified-history.json") for g in ("ssq","dlt")]
    outputs.append(root / "official-ingest-receipt.json")
    if any(x.exists() for x in outputs):
        raise FileExistsError("refuse to overwrite live issuer ingest")
    for game in ("ssq", "dlt"):
        _store(root / (game + "-verified-history.json"), snapshots[game])
    _store(root / "official-ingest-receipt.json", receipt)
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ssq-data", type=Path, required=True)
    p.add_argument("--dlt-data", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        result = ingest({"ssq": args.ssq_data, "dlt": args.dlt_data}, args.out_dir)
    except Exception as exc:
        print("V47_OFFICIAL_INGEST_FAIL=" + json.dumps({
            "exception": type(exc).__name__, "message": str(exc)[:400]}))
        raise
    print("V47_OFFICIAL_INGEST=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
