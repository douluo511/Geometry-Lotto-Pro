"""Verify actual, completed GitHub schedule executions and 44-model outcome loop.

This verification queries GitHub's REST API for every independently persisted
run_id rather than trusting a local event=schedule argument. PR tests,
workflow_dispatch runs, in-progress schedules and remote failures cannot count.
A successful mock/PR run is never evidence of a genuine unattended trigger.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from research.supercompute.v47_live_ledger import ROOT, read, verify

WORKFLOW_PATH = ".github/workflows/v47-official-live-cycle.yml"
DEFAULT_REPO = "douluo511/Geometry-Lotto-Pro"


def github_run(run_id, repo=DEFAULT_REPO, token=None, timeout=15):
    if repo != DEFAULT_REPO or type(run_id) is not int or run_id <= 0:
        raise ValueError("unexpected GitHub repo or run ID")
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "SSQDLT-V47-Schedule-Evidence-Auditor",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as result:
        if result.status != 200:
            raise ValueError("unexpected workflow run HTTP status")
        return json.loads(result.read(300000))


def check_genuine_event(event, api):
    """Fail closed on impostor events, preserve legitimate unfinished runs."""
    run_id = event["run_id"]
    if (type(run_id) is not int or
            event.get("event") != "schedule" or
            event.get("branch") != "main" or
            type(event.get("run_attempt")) is not int):
        raise ValueError("non-schedule or malformed persisted record")
    if api.get("id") != run_id:
        raise ValueError("GitHub run ID does not match persisted ID")
    if (api.get("event") != "schedule"
            or api.get("head_branch") != "main"
            or api.get("head_sha") != event["code_sha"]
            or api.get("run_attempt") != event["run_attempt"]
            or str(api.get("path", "")).split("@")[0] != WORKFLOW_PATH):
        raise ValueError("API record is not the expected genuine GitHub schedule")
    return api.get("status") == "completed" and api.get("conclusion") == "success"


def assess(events, fetch):
    confirmed, pending, rejected = [], [], []
    frozen = set()
    inherited = set()
    scores = set()
    for event in events:
        run_id = event.get("run_id")
        try:
            api = fetch(run_id)
            completed_success = check_genuine_event(event, api)
        except (ValueError, KeyError, urllib.error.URLError, TimeoutError) as err:
            rejected.append({"run_id": run_id,
                             "status": "UNVERIFIED",
                             "reason": type(err).__name__,
                             "message": str(err)[:180]})
            continue
        if not completed_success:
            pending.append({"run_id": run_id,
                            "status": str(api.get("status")),
                            "conclusion": str(api.get("conclusion"))})
            continue
        confirmed.append(run_id)
        for item in event.get("hedge44_generated", []):
            if item.get("count") == 22 and item.get("game") in ("ssq", "dlt"):
                frozen.add(item["game"])
                if item.get("previous_champion_inherited") is True:
                    inherited.add(item["game"])
        for item in event.get("hedge44_scored", []):
            if item.get("count") == 22 and item.get("game") in ("ssq", "dlt"):
                scores.add(item["game"])
    requirements = {
        "two_completed_independent_github_schedule_events": len(confirmed) >= 2,
        "two_games_22_each_frozen_in_genuine_schedule": frozen == {"ssq", "dlt"},
        "later_genuine_generation_reused_both_prior_genomes": inherited == {"ssq", "dlt"},
        "both_games_22_each_postdraw_issuer_scored": scores == {"ssq", "dlt"},
    }
    return {
        "schema": "SSQDLT_V47_LIVE_P0_ACCEPTANCE_V1",
        "status": "PASS" if all(requirements.values()) else "PENDING",
        "confirmed_count": len(confirmed),
        "confirmed_schedule_run_ids": sorted(confirmed),
        "not_completed": pending,
        "api_unverified_or_rejected": rejected,
        "requirements": requirements,
        "windows_host_reboot_test": "UNVERIFIED",
        "signed_issuer_result": False,
        "trusted_external_predraw_seal": False,
        "prediction_edge": "NO_EDGE",
    }


def audit(worktree, repo=DEFAULT_REPO, token=None, fetch=None):
    # Untrusted or incomplete local filesystem must fail, never be accepted.
    integrity = verify(worktree)
    event_dir = Path(worktree) / ROOT / "events"
    events = [read(p) for p in sorted(event_dir.glob("*.json"))] \
        if event_dir.exists() else []
    if len(events) != integrity["count"]:
        raise ValueError("verified event count differs from event contents")
    if fetch is None:
        fetch = lambda run_id: github_run(run_id, repo=repo, token=token)
    decision = assess(events, fetch)
    decision["local_chain_verified"] = integrity["status"] == "PASS"
    decision["local_chain_count"] = integrity["count"]
    decision["last_chain_hash"] = integrity["last_hash"]
    return decision


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    outcome = audit(args.ledger, repo=args.repo,
                    token=os.environ.get("GITHUB_TOKEN"))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as target:
            target.write((json.dumps(outcome, sort_keys=True,
                                     ensure_ascii=False) + "\n").encode())
    print("V47_LIVE_P0_ACCEPTANCE=" + json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
