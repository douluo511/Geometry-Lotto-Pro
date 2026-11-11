"""P0 acceptance: independently cross-check persisted Git receipts with Actions API.

READ-ONLY. GitHub API is external event evidence; this is not a trusted
pre-draw timestamp, V4.7 prediction, full durable Windows-host proof, or edge.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from research.p0_scheduler.runner import REL, _read, verify

REPOSITORY = "douluo511/Geometry-Lotto-Pro"
WORKFLOW_ID = 414851175
WORKFLOW_PATH = ".github/workflows/ssqdlt-p0-scheduler.yml"
P0_BRANCH = "ssqdlt-p0-ledger-v1"


def selected_receipts(ledger_root: Path, verified_state: dict, *,
                      max_scheduled: int = 6) -> list[dict]:
    """Read remote-persisted chain, then audit recent relevant event receipts."""
    if max_scheduled < 2:
        raise ValueError("need at least two schedule records to certify P0")
    events = verified_state["events"]
    scheduled = []
    manual = []
    for item in events:
        receipt = _read(ledger_root / REL / item["path"])
        if receipt["run_id"] != item["run_id"] or receipt["sha256"] != item["sha256"]:
            raise ValueError("ledger index / receipt mismatch")
        (scheduled if receipt["trigger"] == "schedule" else manual).append(receipt)
    chosen = scheduled[-max_scheduled:] + manual[-2:]
    return sorted(chosen, key=lambda x: x["sequence"])


def assess(state: dict, receipts: list[dict],
           actions_runs: dict[str, dict]) -> dict:
    """Pure, fail-closed rules: only GitHub-confirmed completed schedules count."""
    if state["count"] < len(receipts):
        raise ValueError("invalid evidence sample")
    confirmed = 0
    in_progress = 0
    failed = []
    restored = False
    last_id = state["events"][-1]["run_id"] if state["events"] else None
    examined = []
    for receipt in receipts:
        run_id = receipt["run_id"]
        remote = actions_runs.get(run_id)
        if not isinstance(remote, dict):
            raise ValueError(f"missing verified Actions API record for run {run_id}")
        if (remote.get("id") != int(run_id)
                or remote.get("event") != receipt["trigger"]):
            raise ValueError("Actions event mismatch")
        if (remote.get("workflow_id") != WORKFLOW_ID
                or remote.get("path") != WORKFLOW_PATH
                or remote.get("head_branch") != "main"):
            raise ValueError("Actions workflow identity mismatch")
        if (remote.get("head_sha") != receipt.get("workflow_commit_sha")
                or remote.get("run_attempt", 0) < receipt.get("run_attempt", 1)):
            raise ValueError("Actions code identity or attempt mismatch")
        if (receipt.get("run_url")
                != f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"):
            raise ValueError("Actions URL identity mismatch")
        if receipt.get("restored_previous_events") != receipt["sequence"] - 1:
            raise ValueError("remote prefix restoration count mismatch")

        status, conclusion = remote.get("status"), remote.get("conclusion")
        if status == "completed":
            if conclusion == "success":
                if receipt["trigger"] == "schedule":
                    confirmed += 1
                    restored |= receipt["restored_previous_events"] >= 1
                outcome = "CONFIRMED_COMPLETED"
            else:
                failed.append(run_id)
                outcome = "FAILED_OR_NOT_SUCCESSFUL"
        elif status in ("queued", "in_progress", "waiting", "requested", "pending"):
            if conclusion is not None:
                raise ValueError("unfinished Actions run has conclusion")
            if receipt["trigger"] == "schedule":
                in_progress += 1
            outcome = "PENDING"
        else:
            raise ValueError("unknown Actions run status")
        examined.append({"run_id": run_id,
                         "trigger": receipt["trigger"],
                         "verification": outcome})

    passed = confirmed >= 2 and restored and not failed
    return {
        "gate": "P0_REMOTE_GITHUB_SCHEDULE_V1",
        "provider": "GITHUB_ACTIONS",
        "status": "FAIL" if failed else ("PASS" if passed else "UNVERIFIED"),
        "total_persisted_events": state["count"],
        "total_self_reported_schedules": state["scheduled_observed"],
        "externally_audited_events": len(receipts),
        "confirmed_scheduled_completed": confirmed,
        "scheduled_pending": in_progress,
        "remote_restore_observed": restored,
        "latest_recorded_run_id": last_id,
        "failed_run_ids": failed,
        "audited_runs": examined,
        "two_schedule_events_completed_and_restored": passed,
        "real_windows_cold_boot_verified": False,
        "prospective_lottery_cycle_verified": False,
        "official_v47_changed_by_this_verifier": False,
        "paid_model_calls_by_this_verifier": 0,
        "limitations": (
            "GitHub Actions metadata plus Git ledger only; not a formal "
            "prediction seal, official source proof or physical Windows reboot"
        ),
    }


def _github_run(run_id: str) -> dict:
    """Allowlisted read-only GitHub endpoint. No paid provider calls."""
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}"
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SSQDLT-P0-readonly-acceptance/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200:
                    raise RuntimeError("GitHub Actions API returned non-200")
                body = response.read(256 * 1024 + 1)
                if len(body) > 256 * 1024:
                    raise ValueError("Actions API response unexpectedly large")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError("Actions API object expected")
                return result
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError("GitHub Actions API unavailable; cannot certify") from last_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    state = verify(args.ledger)
    receipts = selected_receipts(args.ledger, state)
    runs = {item["run_id"]: _github_run(item["run_id"]) for item in receipts}
    report = assess(state, receipts, runs)
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
