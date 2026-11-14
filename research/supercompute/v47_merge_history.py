"""Append vetted historical draw delta without rewriting seed inputs.

Recorded source URLs are provenance only, NOT cryptographic issuer attestations.
All outputs and SHA receipts are create-only. No missing draw can be imputed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from research.supercompute.v47_models import (
    SPECS, canonical, validate_history, validate_ticket,
)


def _load(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_delta(seed, delta, game):
    """Strict append-only issue/date/ball/URL checks on curated historical data."""
    if game not in SPECS:
        raise ValueError("unknown game")
    if str(seed.get("game", "")).lower() != game:
        raise ValueError("base game mismatch")
    base = seed["draws"]
    validate_history(base, game)
    if delta.get("schema") != "SSQDLT_V47_DRAW_DELTA_V1":
        raise ValueError("unknown delta schema")
    rows = delta.get("records", {}).get(game)
    if not isinstance(rows, list) or not rows:
        raise ValueError("no append records")
    first_expected = int(base[-1]["issue"]) + 1
    last_date = str(base[-1]["draw_date"])
    quality = Counter()
    merged = list(base)
    for i, record in enumerate(rows):
        expected_issue = str(first_expected + i)
        if str(record.get("issue")) != expected_issue:
            raise ValueError(f"draw issue gap/duplicate at {expected_issue}")
        if record.get("source_tier") not in (
                "ISSUER_PROVINCIAL", "SECONDARY_NOT_ISSUER_CONFIRMED"):
            raise ValueError("missing verified source tier")
        url = str(record.get("source_url", ""))
        if not url.startswith("https://") or "/" not in url[8:]:
            raise ValueError("missing citable source URL")
        if record["source_tier"] == "ISSUER_PROVINCIAL" and not (
            url.startswith("https://www.swlc.net.cn/")
            or url.startswith("https://api.js-lottery.com/")):
            raise ValueError("issuer provenance mismatch")
        current = {k: record[k] for k in ("issue", "draw_date", "front", "back")}
        validate_ticket(current, game)
        if current["draw_date"] <= last_date:
            raise ValueError("draw dates must increase")
        last_date = current["draw_date"]
        merged.append(current)
        quality[record["source_tier"]] += 1
    validate_history(merged, game)
    return merged, dict(quality)


def build(seed_paths, delta_path, output_dir):
    delta, delta_sha = _load(delta_path)
    paths, audits, contents = {}, {}, {}
    for game in ("ssq", "dlt"):
        seed, seed_sha = _load(seed_paths[game])
        records, quality = validate_delta(seed, delta, game)
        if str(delta["target_issues"][game]) != str(int(records[-1]["issue"]) + 1):
            raise ValueError("target not next issue")
        outfile = Path(output_dir) / f"{game}-merged-history.json"
        contents[game] = canonical({
            "game": game.upper(), "draws": records,
            "history_source_status": "CITED_NOT_LIVE_ISSUER_ATTESTED",
            "delta_sha256": delta_sha,
        })
        paths[game] = outfile
        audits[game] = {
            "last_original_issue": str(seed["draws"][-1]["issue"]),
            "last_merged_issue": str(records[-1]["issue"]),
            "total_draws": len(records),
            "added_draws": len(records) - len(seed["draws"]),
            "source_tier_counts": quality,
            "issuer_verified_in_this_job": False,
            "secondary_rows_require_confirmation":
                quality.get("SECONDARY_NOT_ISSUER_CONFIRMED", 0),
            "base_file_sha256": seed_sha,
            "merged_snapshot_sha256": hashlib.sha256(contents[game]).hexdigest(),
        }
    result = {"schema": "SSQDLT_V47_HISTORICAL_MERGE_RECEIPT_V1",
              "created_from": str(delta_path),
              "delta_sha256": delta_sha,
              "live_official_source_verified": False,
              "source_status": "HISTORICAL_CITED_WITH_SECONDARY_ROWS",
              "games": audits}
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    # Exclusive creates reject overwritten snapshots and receipts.
    for game in ("ssq", "dlt"):
        with paths[game].open("xb") as file:
            file.write(contents[game])
    with (Path(output_dir) / "merge-receipt.json").open("xb") as file:
        file.write(canonical(result))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ssq-seed", type=Path,
                   default=Path("SSQ/SSQ/resources/official_seed.json"))
    p.add_argument("--dlt-seed", type=Path,
                   default=Path("DLT/src/resources/official_seed.json"))
    p.add_argument("--delta", type=Path, default=Path(
        "research/supercompute/data/v47_20261114_draw_delta.json"))
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    report = build({"ssq": args.ssq_seed, "dlt": args.dlt_seed},
                   args.delta, args.output_dir)
    print("V47_MERGE_RECEIPT=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
