"""Bounded, resumable-offline SZSE diagnostic capture, never PIT qualification.

Each independently hash-bound shard emits all its requested rows, raw bytes when
received, and exact errors for missing rows. Historical index is only the frozen
URL denominator; every article capture is a fresh first-party HTTP request.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BASE = HERE / "stock_szse_suspension_detail_corpus.py"
ARCHIVE_COUNT = 1849
ARCHIVE_SHA256 = "589fddec93bb26e05a067824dbca352129e2dc5db3c2f0027abd3a1d54ffad6e"
FROZEN_START = "20180101"
FROZEN_END = "20260930"
SHARD_SIZE = 100
MAX_ATTEMPTS = 3
MAX_WORKERS = 2
MAX_BYTES = 2_000_000
SHA = re.compile(r"^[a-f0-9]{64}$")
IDENT = re.compile(r"^/disclosure/notice/temp/t(20\d{6})_[A-Za-z0-9]+\.html$")
LOCAL = threading.local()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def load_detail():
    spec = importlib.util.spec_from_file_location("bounded_szse_detail", BASE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_archive(obj: dict):
    if obj.get("schema") != "stock-szse-suspension-static-archive-v1":
        raise ValueError("wrong frozen archive schema")
    if obj.get("frozen_window") != {"start": FROZEN_START, "end": FROZEN_END}:
        raise ValueError("frozen interval mismatch")
    corpus = obj.get("corpus")
    if not isinstance(corpus, dict):
        raise ValueError("missing corpus")
    rows = corpus.get("events")
    if not isinstance(rows, list) or len(rows) != ARCHIVE_COUNT:
        raise ValueError("1849 official URL denominator missing")
    if corpus.get("event_rows") != ARCHIVE_COUNT or corpus.get("unique_article_links") != ARCHIVE_COUNT:
        raise ValueError("source coverage mismatch")
    if corpus.get("canonical_sha256") != ARCHIVE_SHA256 or canonical(rows) != ARCHIVE_SHA256:
        raise ValueError("frozen source content hash mismatch")
    if obj.get("adjudication", {}).get("official_static_archive_pagination") != "PASS":
        raise ValueError("frozen archive provenance not qualified")
    keys = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("non-object source row")
        url, day = row.get("url"), row.get("date")
        parsed = urlparse(str(url))
        match = IDENT.fullmatch(parsed.path)
        if (parsed.scheme != "https" or parsed.hostname not in ("szse.cn", "www.szse.cn")
                or parsed.username or parsed.password or parsed.port or parsed.query
                or parsed.fragment or not match or match.group(1) != day
                or not FROZEN_START <= day <= FROZEN_END):
            raise ValueError("unqualified source URL or date")
        keys.append((day, url))
    if len(set(keys)) != ARCHIVE_COUNT or len({u for _, u in keys}) != ARCHIVE_COUNT:
        raise ValueError("duplicate notice identity")
    return rows


def session_get(url, **kwargs):
    session = getattr(LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        LOCAL.session = session
    return session.get(url, **kwargs)


def capture(index: int, item: dict, raw_dir: Path, getter=None, sleep=None, parser=None):
    getter = getter or session_get
    sleep = sleep or time.sleep
    parser = parser or load_detail()
    url = item["url"]
    attempts = []
    row = {
        "index": index, "archive_date": item["date"], "url": url,
        "archive_identity_source": item.get("identity_source"),
        "status": "NOT VERIFIED", "attempts": attempts,
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        observed = {"attempt": attempt, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            response = getter(
                url, headers={
                    "User-Agent": parser.UA,
                    "Referer": "https://www.szse.cn/disclosure/notice/temp/",
                    "Accept": "text/html,application/xhtml+xml",
                }, timeout=(8, 25), allow_redirects=True,
            )
            raw = response.content
            resolved = str(response.url)
            parsed = urlparse(resolved)
            observed.update({
                "http_status": response.status_code, "resolved_url": resolved,
                "content_type": str(response.headers.get("Content-Type", "")),
                "bytes": len(raw), "sha256": digest(raw),
            })
            attempts.append(observed)
            if (parsed.scheme != "https" or parsed.hostname not in ("szse.cn", "www.szse.cn")
                    or parsed.username or parsed.password or parsed.port):
                raise RuntimeError("off-host or non-HTTPS redirect")
            if response.status_code != 200:
                raise RuntimeError("source HTTP status not 200")
            if not raw or len(raw) > MAX_BYTES:
                raise RuntimeError("empty or oversized source")
            ctype = str(response.headers.get("Content-Type", "")).lower()
            if not (ctype.startswith("text/html") or ctype.startswith("application/xhtml+xml")):
                raise RuntimeError("source Content-Type not HTML")
            text = parser.decode_response(response)
            body, selector = parser.extract_primary_article(BeautifulSoup(text, "html.parser"))
            if not selector or len(body) < 25:
                raise RuntimeError("missing scoped first-party primary article")
            # The saved raw response is the evidence authority; hashes alone are not.
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_name = f"{index:04d}_{observed['sha256']}.html"
            path = raw_dir / raw_name
            temp = raw_dir / (raw_name + ".tmp")
            temp.write_bytes(raw)
            temp.replace(path)
            if digest(path.read_bytes()) != observed["sha256"]:
                raise RuntimeError("raw evidence write/read mismatch")
            observed["status"] = "PASS"
            row.update({
                "status": "PASS", "source_sha256": observed["sha256"],
                "raw_path": str(path), "raw_bytes": len(raw),
                "article_selector": selector,
                "article_body_sha256": digest(body.encode("utf-8")),
                "article_body_chars": len(body),
                "source_type": "fresh_official_HTTP",
            })
            break
        except Exception as exc:
            observed["error"] = f"{type(exc).__name__}: {exc}"
            # If HTTP was seen, keep that exact attempted response hash even on failure.
            if attempt < MAX_ATTEMPTS:
                jitter = int(hashlib.sha256(url.encode("utf-8")).hexdigest()[:2], 16) / 1024
                sleep(0.5 * (2 ** (attempt - 1)) + jitter)
    return row


def run(archive: dict, shard_index: int, raw_dir: Path, getter=None, sleep=None, parser=None):
    rows = validate_archive(archive)
    shard_count = (ARCHIVE_COUNT + SHARD_SIZE - 1) // SHARD_SIZE
    if not isinstance(shard_index, int) or not 0 <= shard_index < shard_count:
        raise ValueError("shard index outside frozen 1849 denominator")
    start = shard_index * SHARD_SIZE
    chosen = list(enumerate(rows[start:min(start + SHARD_SIZE, ARCHIVE_COUNT)], start))
    # Exactly this interval; no smaller denominator to mask unavailable articles.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future = [executor.submit(capture, i, item, raw_dir, getter, sleep, parser)
                  for i, item in chosen]
        result = [f.result() for f in future]
    result.sort(key=lambda x: x["index"])
    verified = sum(row["status"] == "PASS" for row in result)
    outputs = {
        "schema": "stock-szse-frozen-shard-fresh-network-v1",
        "input_source": "historical_hash_frozen_URL_INDEX_not_current_network",
        "input_archive_canonical_sha256": ARCHIVE_SHA256,
        "full_frozen_denominator": ARCHIVE_COUNT,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "start": start, "end_exclusive": start + len(chosen),
        "requested": len(chosen), "verified": verified,
        "missing": len(chosen) - verified,
        "records": result,
        "adjudication": {
            "shard_http_primary_body": "PASS" if verified == len(chosen) else "NOT VERIFIED",
            "entire_1849_current_network": "NOT VERIFIED",
            "qualified_actual_effective_transitions": "NOT VERIFIED",
            "historical_daily_st_suspension_pit_sse_szse_bse": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
    }
    return outputs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--shard-index", type=int, required=True)
    p.add_argument("--raw-dir", type=Path, default=Path("szse_shard_raw"))
    p.add_argument("--report", type=Path, default=Path("szse_shard_report.json"))
    a = p.parse_args()
    source = json.loads(a.archive.read_text(encoding="utf-8"))
    report = run(source, a.shard_index, a.raw_dir)
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "shard_index": a.shard_index, "requested": report["requested"],
        "verified": report["verified"], "missing": report["missing"],
        "adjudication": report["adjudication"],
    }, sort_keys=True))
    return 0 if report["missing"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
