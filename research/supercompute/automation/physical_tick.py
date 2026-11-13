"""One bounded unattended historical-ingestion tick (not a lottery forecast).

Run on an evidence Git worktree, not the source repository's main branch.
The caller is responsible for committing/pushing then independently reloading.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from research.supercompute.automation.ssq_physical_source import (
    URL as SSQ_URL, collect as collect_ssq, parse_public_table,
)
from research.supercompute.automation.dlt_physical_source import (
    collect as collect_dlt, _create_once, _sealed_bytes,
)
from research.supercompute.automation.official_source_gate import official_rows
from research.supercompute.automation.physical_transport import (
    ssq_fetch, TransportExhausted,
)
from research.supercompute.automation.physical_ledger_db import sync

PROTOCOL = "SSQDLT_PHYSICAL_UNATTENDED_TICK_V1"
REL = Path("research/physical_evidence_v1")
KNOWN_SSQ_ISSUE = "2026130"
DLT_FIRST = 26001
DLT_LAST_CANDIDATE = 26135


def _recorded_issues(ledger: Path) -> set[str]:
    return {p.stem for p in (ledger / "draws").glob("*.json")}


def _attempt_too_recent(ledger: Path, issue: str, now: datetime,
                        cooldown: timedelta) -> bool:
    for path in (ledger / "attempts" / issue).glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            observed = datetime.fromisoformat(row["observed_at_utc"])
            if observed.tzinfo and timedelta(0) <= (now - observed) < cooldown:
                return True
        except (KeyError, TypeError, ValueError):
            # Malformed evidence must not silently force a new attempt.
            raise ValueError("INVALID_PERSISTED_ATTEMPT_TIMESTAMP")
    return False


def _candidate_dlt(root: Path, now: datetime) -> str | None:
    present = _recorded_issues(root)
    for n in range(DLT_FIRST, DLT_LAST_CANDIDATE + 1):
        issue = str(n)
        if issue in present:
            continue
        if not _attempt_too_recent(root, issue, now, timedelta(hours=6)):
            return issue
    return None


def tick(repo_ledger: Path, *, max_ssq_new=8,
         ssq_network=ssq_fetch, dlt_collector=collect_dlt, now=None) -> dict:
    if not 1 <= max_ssq_new <= 50:
        raise ValueError("SSQ_BATCH_OUT_OF_RANGE")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("OBSERVATION_CLOCK_MUST_BE_TIMEZONE_AWARE")
    root = repo_ledger / REL
    ssq = root / "SSQ"
    dlt = root / "DLT"
    actions = []
    raw_ssq = None
    try:
        raw_ssq = ssq_network(SSQ_URL)
        official = official_rows(raw_ssq[2], "SSQ")
        ranked = sorted(official, key=lambda r: r.issue, reverse=True)
        if not ranked:
            raise ValueError("OFFICIAL_SSQ_WINDOW_EMPTY")
        issues = [r.issue for r in ranked if r.issue not in _recorded_issues(ssq)]
        for issue in issues[:max_ssq_new]:
            # One observed HTTP response supplies the rows; no repeated GETs.
            receipt = collect_ssq(issue, ssq, fetcher=lambda _url, response=raw_ssq: response)
            actions.append({"game": "SSQ", "issue": issue,
                            "status": receipt["status"], "reason": receipt["reason"]})
    except Exception as exc:
        # Preserve failed source discovery as an explicit attempt. Do not
        # manufacture a draw or infer the next official issue.
        known = sorted(_recorded_issues(ssq), reverse=True)
        issue = known[0] if known else KNOWN_SSQ_ISSUE
        def blocked(_url):
            if raw_ssq is not None:
                return raw_ssq
            raise exc
        receipt = collect_ssq(issue, ssq, fetcher=blocked)
        actions.append({"game": "SSQ", "issue": issue,
                        "status": receipt["status"], "reason": receipt["reason"]})
    next_dlt = _candidate_dlt(dlt, current)
    if next_dlt:
        receipt = dlt_collector(next_dlt, dlt)
        actions.append({"game": "DLT", "issue": next_dlt,
                        "status": receipt["status"], "reason": receipt["reason"]})
    else:
        actions.append({"game": "DLT", "status": "NO_ELIGIBLE_CANDIDATE",
                        "reason": "BOUNDED_RANGE_OR_COOLDOWN"})
    db_report = sync(root, root / "physical_history.sqlite3")
    tick_receipt = {
        "schema": PROTOCOL,
        "observed_utc": current.isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_event": os.environ.get("GITHUB_EVENT_NAME"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "actions": actions,
        "db_counts": db_report["counts"],
        "formal_A": 0,
        "edge": "NO_EDGE",
        "remote_commit_verified": False,
        "actual_schedule_verified": False,
    }
    stamp = current.strftime("%Y%m%dT%H%M%S%fZ")
    fname = f"{stamp}-{uuid4().hex}.json"
    _create_once(root / "ticks" / fname, _sealed_bytes(tick_receipt))
    return {"status": "LOCAL_TICK_NOT_YET_REMOTE_DURABLE",
            "receipt": f"ticks/{fname}", "counts": db_report["counts"],
            "actions": actions, "formal_A": 0, "edge": "NO_EDGE"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    if args.verify_only:
        root = args.ledger / REL
        report = sync(root, root / "physical_history.sqlite3")
        # This only verifies restored content. It does not authenticate
        # the GitHub event or predraw source publication time.
        print(json.dumps({"status": "RESTORED_SQLITE_CHECKED",
                          **report}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(tick(args.ledger), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
