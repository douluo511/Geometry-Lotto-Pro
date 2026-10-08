"""Verify ALL 19 current-run shard reports and raw bytes; never certify daily PIT."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from stock_szse_bounded_shard import (
    ARCHIVE_COUNT, ARCHIVE_SHA256, SHARD_SIZE, canonical,
    digest, load_detail, validate_archive,
)
from bs4 import BeautifulSoup

SHA = re.compile(r"^[a-f0-9]{64}$")
RAW_NAME = re.compile(r"^szse_shard_raw/[0-9]{4}_[123]_[a-f0-9]{64}\.html$")


def merge(archive: dict, parts: Path):
    baseline = validate_archive(archive)
    count = (ARCHIVE_COUNT + SHARD_SIZE - 1) // SHARD_SIZE
    found = sorted(p for p in parts.iterdir() if p.is_dir() and p.name.startswith("shard-"))
    expected_names = {f"shard-{i:02d}" for i in range(count)}
    if {p.name for p in found} != expected_names or len(found) != count:
        raise ValueError("missing, duplicate, or unexpected shard: 19/19 required")
    detail = load_detail()
    source_records = []
    raw_hashes = set()
    for shard_id in range(count):
        folder = parts / f"shard-{shard_id:02d}"
        manifest = json.loads((folder / "szse_shard_report.json").read_text(encoding="utf-8"))
        lo = shard_id * SHARD_SIZE
        hi = min(lo + SHARD_SIZE, ARCHIVE_COUNT)
        count_here = hi - lo
        if (manifest.get("schema") != "stock-szse-frozen-shard-fresh-network-v1"
                or manifest.get("input_archive_canonical_sha256") != ARCHIVE_SHA256
                or manifest.get("input_source") != "historical_hash_frozen_URL_INDEX_not_current_network"
                or manifest.get("full_frozen_denominator") != ARCHIVE_COUNT
                or manifest.get("shard_index") != shard_id
                or manifest.get("shard_count") != count
                or manifest.get("start") != lo or manifest.get("end_exclusive") != hi
                or manifest.get("requested") != count_here
                or manifest.get("verified") != count_here or manifest.get("missing") != 0
                or not isinstance(manifest.get("records"), list)
                or len(manifest["records"]) != count_here):
            raise ValueError(f"shard {shard_id}: incomplete or altered manifest")
        a = manifest.get("adjudication", {})
        if (a.get("shard_http_primary_body") != "PASS"
                or a.get("entire_1849_current_network") != "NOT VERIFIED"
                or a.get("historical_daily_st_suspension_pit_sse_szse_bse") != "NOT VERIFIED"
                or a.get("advanced_business") != "NOT VERIFIED" or a.get("final_gate") != "FAIL"):
            raise ValueError(f"shard {shard_id}: invalid final-gate boundary")
        for pos, row in enumerate(manifest["records"]):
            absolute = lo + pos
            base = baseline[absolute]
            name = row.get("raw_path")
            if (row.get("index") != absolute or row.get("archive_date") != base["date"]
                    or row.get("url") != base["url"] or row.get("status") != "PASS"
                    or row.get("source_type") != "fresh_official_HTTP"
                    or not isinstance(name, str) or not RAW_NAME.fullmatch(name)):
                raise ValueError(f"shard {shard_id}: source identity or raw path mismatch at {absolute}")
            check = folder / name
            if not check.is_file() or check.is_symlink() or not check.resolve().is_relative_to(folder.resolve()):
                raise ValueError("raw evidence file missing, symlinked or outside shard")
            raw = check.read_bytes()
            sha = digest(raw)
            attempts = row.get("attempts", [])
            if (not SHA.fullmatch(str(row.get("source_sha256") or ""))
                    or sha != row["source_sha256"] or row.get("raw_bytes") != len(raw)
                    or not attempts or len(attempts) > 3
                    or attempts[-1].get("status") != "PASS"
                    or attempts[-1].get("sha256") != sha
                    or attempts[-1].get("http_status") != 200
                    or attempts[-1].get("raw_path") != name
                    or [x.get("attempt") for x in attempts] != list(range(1, len(attempts)+1))):
                raise ValueError(f"source bytes/attempt ledger mismatch {absolute}")
            if not SHA.fullmatch(str(row.get("article_body_sha256") or "")):
                raise ValueError(f"unbound article body digest {absolute}")
            # Independently replay the named first-party parser against the saved
            # response bytes, not a purported text excerpt or another source URL.
            ctype = str(attempts[-1].get("content_type") or "")
            match = re.search(r"charset\s*=\s*([A-Za-z0-9_-]+)", ctype, flags=re.I)
            encoding = match.group(1) if match else None
            decoded = detail.decode_response(SimpleNamespace(content=raw, encoding=encoding))
            text, selector = detail.extract_primary_article(BeautifulSoup(decoded, "html.parser"))
            if (selector != row.get("article_selector")
                    or digest(text.encode("utf-8")) != row["article_body_sha256"]
                    or len(text) != row.get("article_body_chars")
                    or len(text) < 25):
                raise ValueError(f"reparsed actual article differs from stored evidence {absolute}")
            if sha in raw_hashes:
                raise ValueError("different URLs returned indistinguishable raw HTML")
            raw_hashes.add(sha)
            source_records.append({
                "index": absolute, "url": row["url"], "archive_date": row["archive_date"],
                "raw_sha256": sha, "body_sha256": row["article_body_sha256"],
                "article_selector": selector,
            })
    if len(source_records) != ARCHIVE_COUNT:
        raise ValueError("full 1849 frozen source coverage not complete")
    result = {
        "schema": "stock-szse-1849-fresh-raw-source-merge-v1",
        "source_frozen_denominator": ARCHIVE_COUNT,
        "shards_verified": count,
        "raw_response_sha256_unique": len(raw_hashes),
        "source_records_sha256": canonical(source_records),
        "evidence": source_records,
        "adjudication": {
            "full_1849_official_HTTP_and_scoped_primary_body": "PASS",
            "instrument_asof_lifecycle": "NOT VERIFIED",
            "actual_effective_resumption": "NOT VERIFIED",
            "intraday_vs_full_day_suspension": "NOT VERIFIED",
            "sse_szse_bse_daily_st_suspension_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
    }
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--parts", type=Path, required=True)
    p.add_argument("--report", type=Path, default=Path("szse_1849_merged_source.json"))
    a = p.parse_args()
    report = merge(json.loads(a.archive.read_text(encoding="utf-8")), a.parts)
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "shards_verified": report["shards_verified"],
        "raw_response_sha256_unique": report["raw_response_sha256_unique"],
        "source_records_sha256": report["source_records_sha256"],
        "adjudication": report["adjudication"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
