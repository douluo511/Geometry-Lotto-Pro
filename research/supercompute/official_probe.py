"""Official public-source intake with original response bytes and fail-closed status.

SSQ: two independent official provincial centres (Shanghai/Hebei).
DLT: Gansu official history + Jiangsu official per-issue announcement:
the Jiangsu history-list 'publication date' is NOT treated as draw_date.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse

import requests

from research.supercompute.official_prospective import (
    MAX_BYTES, check_draw, create_once, latest_consensus, receipt, utc_now,
)

ROOT = Path(__file__).resolve().parents[2]
PROBE_VERSION = "OFFICIAL_PUBLIC_SOURCE_INTAKE_20261112_V1"
JS_LIST_URL = "https://api.js-lottery.com/wfzq/dlt/data"
GANSU_LATEST_URL = "https://www.gstc.org.cn/wanfa/dlt"
ALLOWED_JS_HOSTS = {"www.js-lottery.com", "api.js-lottery.com"}


class IntakeError(RuntimeError):
    pass


def plain(raw):
    if isinstance(raw, bytes):
        decoded = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                decoded = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if decoded is None:
            raise IntakeError("official page charset unavailable")
        raw = decoded
    raw = re.sub(r"(?is)<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>",
                 " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


class RawStore:
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.raw_dir = self.out / "raw"
        self.raw_dir.mkdir()
        self.attempts = []

    def save(self, source, url, status, raw, *, parser):
        if len(raw) > MAX_BYTES:
            raise IntakeError("oversized official response")
        hashed = hashlib.sha256(raw).hexdigest()
        if raw:
            path = self.raw_dir / (hashed + ".bin")
            if path.exists():
                if path.read_bytes() != raw:
                    raise IntakeError("SHA256 storage conflict")
            else:
                with path.open("xb") as file:
                    file.write(raw)
        entry = {
            "source": source, "url": url, "http_status": status,
            "sha256": hashed, "bytes": len(raw),
            "parser_version": parser,
            "fetched_at_utc_untrusted": utc_now().isoformat(),
        }
        self.attempts.append(entry)
        return entry

    def native(self, meta, raw):
        return self.save(meta.get("source", "UNKNOWN"),
                         meta.get("url", "UNKNOWN"),
                         int(meta.get("http_status", 200)),
                         bytes(raw), parser=PROBE_VERSION + "/NATIVE")


def limited_get(url, store, source, *, hosts):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in hosts:
        raise IntakeError("URL not on approved official HTTPS host")
    session = requests.Session()
    try:
        response = session.get(url, timeout=(8, 18), allow_redirects=False,
                               headers={
                                   "User-Agent": "Mozilla/5.0 (compatible; GLP-OfficialResearch/1.0)",
                                   "Accept": "text/html,application/xhtml+xml",
                               })
        raw = bytes(response.content[:MAX_BYTES + 1])
        entry = store.save(source, url, int(response.status_code), raw,
                           parser=PROBE_VERSION)
        if response.status_code != 200:
            raise IntakeError("source HTTP " + str(response.status_code))
        if len(raw) > MAX_BYTES or not raw:
            raise IntakeError("official HTTP body empty or over limit")
        if "html" not in response.headers.get("Content-Type", "").lower():
            raise IntakeError("unexpected media type")
        return raw, entry
    except requests.RequestException as error:
        store.attempts.append({
            "source": source, "url": url, "http_status": 0,
            "error": type(error).__name__ + ": " + str(error)[:320],
            "parser_version": PROBE_VERSION,
            "fetched_at_utc_untrusted": utc_now().isoformat(),
        })
        raise IntakeError("official network request failed") from error
    finally:
        session.close()


def js_listing_latest(raw):
    """Read issue and detail link; never interpret 发布日期 as 开奖日期."""
    markup = raw.decode("utf-8-sig", errors="strict")
    if "大乐透" not in plain(markup) or "发布日期" not in plain(markup):
        raise IntakeError("unrecognized Jiangsu listing or publication header")
    candidates = []
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", markup):
        visible = plain(row)
        m = re.search(r"(?<!\d)(26\d{3})(?!\d)", visible)
        if not m:
            continue
        numbers = re.findall(r"(?<!\d)(\d{2})(?!\d)", visible[m.end():])
        if len(numbers) != 7:
            raise IntakeError("Jiangsu listing numbers ambiguous")
        anchor = re.search(r"""(?is)<a\b[^>]*href\s*=\s*["']([^"']+)["']""", row)
        if not anchor:
            raise IntakeError("Jiangsu official detail link absent")
        candidates.append({
            "issue": m.group(1), "front": sorted(map(int, numbers[:5])),
            "back": sorted(map(int, numbers[5:])),
            "href": html.unescape(anchor.group(1)),
        })
    if not candidates:
        raise IntakeError("no parseable Jiangsu draw listing")
    if len({x["issue"] for x in candidates}) != len(candidates):
        raise IntakeError("duplicate listing issue")
    return max(candidates, key=lambda x: int(x["issue"]))


def parse_jiangsu_detail(raw):
    text = plain(raw)
    issue = re.search(r"超级大乐透第\s*(26\d{3})\s*期开奖公告", text)
    day = re.search(
        r"开奖日期\s*[:：]\s*(20\d{2})\s*(?:年|-)\s*(\d{1,2})\s*(?:月|-)\s*(\d{1,2})\s*日?",
        text)
    balls = re.search(
        r"本期开奖号码\s*[:：]\s*((?:(?:\d{2})\s+){6}\d{2})(?!\d)", text)
    if not issue or not day or not balls:
        raise IntakeError("Jiangsu announcement missing issue/draw date/numbers")
    numbers = [int(x) for x in re.findall(
        r"(?<!\d)\d{2}(?!\d)", balls.group(1))]
    if len(numbers) != 7:
        raise IntakeError("Jiangsu seven balls ambiguous")
    return check_draw("dlt", {
        "issue": issue.group(1),
        "draw_date": f"{int(day.group(1)):04d}-{int(day.group(2)):02d}-{int(day.group(3)):02d}",
        "front": sorted(numbers[:5]), "back": sorted(numbers[5:]),
    })


def parse_gansu_latest(raw):
    """Accept only latest Gansu official home panel, not its stale history."""
    text = plain(raw)
    found = re.search(
        r"超级大乐透\s*(26\d{3})\s*期\s*开奖日期\s*[:：]\s*"
        r"(20\d{2}-\d{2}-\d{2}).{0,90}?开奖号码\s*[:：]\s*"
        r"((?:(?:\d{2})\s+){6}\d{2})(?!\d)", text)
    if not found:
        raise IntakeError("Gansu homepage lacks one explicit issue/date/result")
    nums = [int(x) for x in re.findall(r"(?<!\d)\d{2}(?!\d)", found.group(3))]
    if len(nums) != 7:
        raise IntakeError("Gansu current result must contain exactly seven numbers")
    return check_draw("dlt", {"issue": found.group(1),
                               "draw_date": found.group(2),
                               "front": sorted(nums[:5]),
                               "back": sorted(nums[5:])})


def probe_dlt(store):
    sources = []
    try:
        raw, evidence = limited_get(
            GANSU_LATEST_URL, store, "GANSU_SPORT",
            hosts={"www.gstc.org.cn"})
        latest = parse_gansu_latest(raw)
        sources.append({
            "source_id": "GANSU_SPORT", "status": "PASS",
            "draw": latest, "raw_records": [evidence],
        })
    except Exception as error:
        store.attempts.append({
            "source": "GANSU_SPORT", "status": "BLOCKED",
            "error": type(error).__name__ + ": " + str(error)[:600],
        })
    try:
        listing, list_meta = limited_get(
            JS_LIST_URL, store, "JIANGSU_SPORT", hosts=ALLOWED_JS_HOSTS)
        selected = js_listing_latest(listing)
        detail_url = urljoin(JS_LIST_URL, selected["href"])
        detail, detail_meta = limited_get(
            detail_url, store, "JIANGSU_SPORT", hosts=ALLOWED_JS_HOSTS)
        official = parse_jiangsu_detail(detail)
        if (selected["issue"] != official["issue"]
                or selected["front"] != official["front"]
                or selected["back"] != official["back"]):
            raise IntakeError("Jiangsu listing and announcement disagree")
        sources.append({
            "source_id": "JIANGSU_SPORT", "status": "PASS",
            "draw": official, "raw_records": [list_meta, detail_meta],
        })
    except Exception as error:
        store.attempts.append({
            "source": "JIANGSU_SPORT", "status": "BLOCKED",
            "error": type(error).__name__ + ": " + str(error)[:600],
        })
    return sources


def probe_ssq(store):
    # Dedicated process per game prevents two unrelated glp packages colliding.
    sys.path.insert(0, str(ROOT / "SSQ/SSQ"))
    from glp.sources import fetch_hebei_latest, fetch_shanghai_history
    sources = []
    for label, function in (
            ("SHANGHAI_FULI", fetch_shanghai_history),
            ("HEBEI_FULI", fetch_hebei_latest)):
        first = len(store.attempts)
        try:
            item = function(record_raw=store.native)
            last = item[0][-1].to_dict() if label == "SHANGHAI_FULI" else item[0].to_dict()
            kept = [
                x for x in store.attempts[first:]
                if x.get("sha256") and x.get("http_status") == 200
            ]
            if not kept:
                raise IntakeError("native official adapter did not preserve raw bytes")
            sources.append({
                "source_id": label, "status": "PASS",
                "draw": last, "raw_records": kept,
            })
        except Exception as error:
            store.attempts.append({
                "source": label, "status": "BLOCKED",
                "error": type(error).__name__ + ": " + str(error)[:600],
            })
    return sources


def probe_game(game, out):
    if game not in ("ssq", "dlt"):
        raise ValueError("unsupported lottery")
    store = RawStore(out)
    try:
        sources = probe_ssq(store) if game == "ssq" else probe_dlt(store)
        if len(sources) != 2:
            raise IntakeError("only " + str(len(sources)) + " official centres parsed")
        agreement = latest_consensus(game, sources, observed_at=utc_now())
        create_once(store.out / "verified_latest.json", agreement)
        status = "TWO_OFFICIAL_CENTRE_CONSENSUS"
        outcome = {
            "latest": agreement["draw"],
            "source_sha256": agreement["sha256"],
        }
    except Exception as error:
        status = "SOURCE_BLOCKED"
        outcome = {"reason": type(error).__name__ + ": " + str(error)[:1000]}
    report = receipt({
        "schema": "SSQDLT_OFFICIAL_INGEST_ATTEMPT_V1",
        "observed_at_utc_untrusted": utc_now().isoformat(),
        "game": game, "status": status,
        "attempts": store.attempts,
        "result": outcome,
        "formal_A": 0, "edge": "NO_EDGE",
        "not_a_predraw_forecast": True,
    })
    create_once(store.out / "attempt.json", report)
    return {
        "game": game, "status": status, "result": outcome,
        "attempt_sha256": report["sha256"], "formal_A": 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", choices=("ssq", "dlt"), required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    result = probe_game(args.game, args.out)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # An honest SOURCE_BLOCKED status produces an archived failure receipt.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
