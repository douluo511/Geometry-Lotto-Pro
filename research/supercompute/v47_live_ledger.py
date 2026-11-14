"""Schedule-only, append-only remote ledger for real issue forecasts and scoring.

Separate from P0 schedule. An issuer HTML overlap is not an issuer signature,
and a machine UTC timestamp is not an independent predraw timestamp.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from research.supercompute.v47_models import canonical
from research.supercompute.v47_official_score import (
    score_issued_frozen, verify_publisher_history,
)

ROOT = Path("research/v47_live_ledger")
SCHEMA = "SSQDLT_V47_LIVE_LEDGER_V1"
ZERO = "0" * 64
WEEKDAYS = {"ssq": {1, 3, 6}, "dlt": {0, 2, 5}}
DRAW_TIME = {"ssq": time(21, 15), "dlt": time(21, 25)}
CST = ZoneInfo("Asia/Shanghai")


def digest(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def create(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(data)


def next_nominal_draw(last_published, game):
    d = date.fromisoformat(last_published) + timedelta(days=1)
    while d.weekday() not in WEEKDAYS[game]:
        d += timedelta(days=1)
    return datetime.combine(d, DRAW_TIME[game], tzinfo=CST)


def verify(worktree):
    root = Path(worktree) / ROOT
    state = read(root / "state.json") if (root / "state.json").is_file() else {
        "schema": SCHEMA, "count": 0, "last_hash": ZERO}
    if state.get("schema") != SCHEMA:
        raise ValueError("live ledger schema changed")
    records = sorted((root / "events").glob("*.json")) if (root / "events").exists() else []
    if state["count"] != len(records):
        raise ValueError("live ledger record count mismatch")
    last_hash, ids, last_report_sha = ZERO, set(), {}
    for count, path in enumerate(records, 1):
        e = read(path)
        payload = {k: v for k, v in e.items() if k != "event_hash"}
        if (payload.get("schema") != SCHEMA or payload.get("sequence") != count
                or payload.get("previous_hash") != last_hash
                or payload.get("event") != "schedule"
                or payload.get("branch") != "main"
                or not isinstance(payload.get("run_id"), int)
                or payload["run_id"] in ids
                or path.name != f"{count:08d}-{payload['run_id']}.json"
                or digest(canonical(payload)) != e.get("event_hash")):
            raise ValueError("live ledger hash chain conflict")
        for item in payload["files"]:
            rel = Path(item["path"])
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("invalid ledger path")
            actual = root / rel
            if not actual.is_file() or digest(actual.read_bytes()) != item["sha256"]:
                raise ValueError("published/frozen evidence modified: " + str(rel))
            if item["kind"] == "forecast_report":
                last_report_sha[item["game"]] = item["sha256"]
        ids.add(payload["run_id"])
        last_hash = e["event_hash"]
    if state["last_hash"] != last_hash:
        raise ValueError("checkpoint hash mismatch")
    for game, sha in last_report_sha.items():
        latest = root / f"latest_{game}.json"
        if not latest.is_file() or digest(latest.read_bytes()) != sha:
            raise ValueError("model lineage index tampered")
    return {"status": "PASS", "count": len(records), "last_hash": last_hash,
            "run_ids": sorted(ids)}


def record(worktree, source_dir, run_id, run_attempt, sha, event, now=None):
    if (event != "schedule" or int(run_id) <= 0 or int(run_attempt) < 1
            or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha)):
        raise ValueError("only a real schedule may be recorded")
    previous = verify(worktree)
    if int(run_id) in previous["run_ids"]:
        raise ValueError("repeated run id")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("naive timestamp")
    source_dir = Path(source_dir)
    publisher = read(source_dir / "official-ingest-receipt.json")
    if (publisher.get("schema") != "SSQDLT_V47_LIVE_ISSUER_INGEST_V1"
            or publisher.get("status") != "OVERLAP_VERIFIED"
            or set(publisher.get("games", {})) != {"ssq", "dlt"}):
        raise ValueError("two publisher source audit receipts are required")
    root = Path(worktree) / ROOT
    files, generated, scored, pending = [], [], [], []

    def archive(data, rel, kind, game=None):
        create(root / rel, data)
        item = {"kind": kind, "path": str(rel), "sha256": digest(data)}
        if game:
            item["game"] = game
        files.append(item)

    for game in ("ssq", "dlt"):
        raw = (source_dir / f"{game}-publisher-raw.html").read_bytes()
        if digest(raw) != publisher["games"][game]["raw_sha256"]:
            raise ValueError("issuer page bytes do not match receipt")
        archive(raw, Path("source") / f"{run_id}-{game}.html",
                "issuer_html", game)
    archive((source_dir / "official-ingest-receipt.json").read_bytes(),
            Path("source") / f"{run_id}-receipt.json", "issuer_receipt")

    for game in ("ssq", "dlt"):
        historical = source_dir / f"{game}-verified-history.json"
        rows, _ = verify_publisher_history(
            game, historical, source_dir / "official-ingest-receipt.json")
        last = max(rows.values(), key=lambda x: int(x["issue"]))
        target = str(int(last["issue"]) + 1)
        if publisher["games"][game]["new_target_issue"] != target:
            raise ValueError("target issue is not derived from issuer HTML")
        fpath = root / "forecasts" / f"{game}-{target}-v47-unified.json"
        cutoff = next_nominal_draw(last["draw_date"], game)
        if now.astimezone(CST) >= cutoff:
            pending.append({"game": game, "target": target,
                            "reason": "PUBLISHER_STALE_AFTER_NOMINAL_DRAW"})
            continue
        if fpath.exists():
            pending.append({"game": game, "target": target,
                            "reason": "EXISTING_FROZEN_PREDICTION"})
            continue
        output = root / "reports" / f"{game}-{target}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m",
                   "research.supercompute.v47_forecast", "generate",
                   "--game", game, "--" + game + "-data", str(historical),
                   "--" + game + "-target", target,
                   "--output", str(output),
                   "--freeze-dir", str(fpath.parent),
                   "--generations", "2", "--validation", "6",
                   "--holdout", "3", "--mc-trials", "300",
                   "--physics-steps", "30", "--seed", "2026"]
        prior = root / f"latest_{game}.json"
        if prior.is_file():
            command.extend(["--previous", str(prior)])
        subprocess.run(command, check=True, timeout=480,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        report = read(output)
        game_result = report.get("games", {}).get(game, {})
        if (set(report.get("games", {})) != {game}
                or game_result.get("ticket_count") != 11
                or len(game_result.get("validation", {}).get("M2", {})) != 11
                or len(game_result.get("validation", {}).get("M3", {})) != 11
                or read(fpath)["source"]["target_issue"] != target):
            raise ValueError("incomplete 11-model real issue freeze")
        body, frozen = output.read_bytes(), fpath.read_bytes()
        files.extend([
            {"kind": "forecast_report", "game": game,
             "path": str(Path("reports") / output.name),
             "sha256": digest(body)},
            {"kind": "frozen", "game": game,
             "path": str(Path("forecasts") / fpath.name),
             "sha256": digest(frozen)},
        ])
        generated.append({"game": game, "target": target,
                          "frozen_sha256": digest(frozen),
                          "before_nominal_draw": True})
        create(root / f"latest_{game}.next.json", body)
        os.replace(root / f"latest_{game}.next.json",
                   root / f"latest_{game}.json")

    for game in ("ssq", "dlt"):
        for frozen in sorted((root / "forecasts").glob(f"{game}-*-v47-unified.json")):
            result = score_issued_frozen(
                game, frozen,
                source_dir / f"{game}-verified-history.json",
                source_dir / "official-ingest-receipt.json")
            if result["status"] != "PUBLISHED_DRAW_SCORED":
                continue
            path = root / "scores" / f"{game}-{result['issue']}.json"
            if path.exists():
                continue
            body = canonical(result)
            archive(body, Path("scores") / path.name, "score", game)
            scored.append({"game": game, "issue": result["issue"],
                           "count": result["count"],
                           "before_nominal_draw": result["frozen_before_nominal_draw"]})

    sequence = previous["count"] + 1
    payload = {"schema": SCHEMA, "sequence": sequence,
               "run_id": int(run_id), "run_attempt": int(run_attempt),
               "event": "schedule", "branch": "main", "code_sha": sha,
               "previous_hash": previous["last_hash"],
               "recorded_utc": now.isoformat(), "files": files,
               "generated": generated, "scored": scored,
               "pending": pending, "signed_issuer_feed": False,
               "trusted_predraw_seal": False}
    eventdoc = {**payload, "event_hash": digest(canonical(payload))}
    archive_path = root / "events" / f"{sequence:08d}-{run_id}.json"
    create(archive_path, canonical(eventdoc))
    create(root / "state.next.json", canonical({
        "schema": SCHEMA, "count": sequence,
        "last_hash": eventdoc["event_hash"]}))
    os.replace(root / "state.next.json", root / "state.json")
    validated = verify(worktree)
    return {"status": validated["status"], "count": validated["count"],
            "generated": generated, "scored": scored, "pending": pending}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--ledger", type=Path, required=True)
    r = sub.add_parser("record")
    r.add_argument("--ledger", type=Path, required=True)
    r.add_argument("--source-dir", type=Path, required=True)
    r.add_argument("--run-id", type=int, required=True)
    r.add_argument("--run-attempt", type=int, required=True)
    r.add_argument("--commit-sha", required=True)
    r.add_argument("--event", required=True)
    args = p.parse_args(argv)
    if args.command == "verify":
        result = verify(args.ledger)
    else:
        result = record(args.ledger, args.source_dir, args.run_id,
                        args.run_attempt, args.commit_sha, args.event)
    print("V47_LIVE_LEDGER=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
