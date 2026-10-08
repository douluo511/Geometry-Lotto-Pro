"""GitHub Actions push-only SSQ Freeze contract (STAGING, no writer permission).

This script must run from a real GitHub push into the dedicated evidence branch.
It checks the GitHub API server timestamp for the *running* workflow and the
exact checked-out Git commit's one new Freeze. It deliberately does NOT decide
official outcomes, count prospective replays, or authorize model promotion.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "SSQ" / "SSQ"))

from glp.net_client import NetClient  # noqa: E402
from glp.prospective_github_receipt import (  # noqa: E402
    _API, _BRANCH, _REPO, _WORKFLOW, _json_get, _utc,
    _validate_frozen_prediction_payload, _verify_append_only_branch,
)

_FREEZE = re.compile(r"SSQ/prospective_ledger/freezes/(20[0-9]{5})\.json\Z")


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME")
    branch = os.environ.get("GITHUB_REF_NAME")
    source_sha = os.environ.get("GITHUB_SHA", "")
    run_str = os.environ.get("GITHUB_RUN_ID", "")
    if event != "push" or branch != _BRANCH or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("SSQ real pre-draw evidence must be a push to dedicated branch")
    if not run_str.isdecimal() or int(run_str) <= 0:
        raise ValueError("invalid GitHub run id")

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != source_sha:
        raise ValueError("SSQ evidence workflow checkout is not the exact event head")
    parents = subprocess.check_output(
        ["git", "show", "-s", "--format=%P", "HEAD"], cwd=ROOT, text=True
    ).strip().split()
    if len(parents) != 1:
        raise ValueError("SSQ Freeze commit must have one parent (no merge/initial reset)")
    files = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=ROOT, text=True,
    ).strip().splitlines()
    if len(files) != 1 or not _FREEZE.fullmatch(files[0]):
        raise ValueError("SSQ Freeze commit must add one issue-specific JSON and nothing else")
    path = files[0]
    issue = _FREEZE.fullmatch(path).group(1)
    # Never update an older Freeze after the fact. The parent tree must not have it.
    existed = subprocess.run(
        ["git", "cat-file", "-e", f"{parents[0]}:{path}"],
        cwd=ROOT, capture_output=True, check=False,
    )
    if existed.returncode == 0:
        raise ValueError("SSQ Freeze record existed in parent commit; overwrites prohibited")
    raw = (ROOT / path).read_bytes()
    if not raw or len(raw) > 50000:
        raise ValueError("SSQ Freeze file empty or oversized")
    try:
        prediction = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("SSQ Freeze file is not valid JSON") from exc

    client = NetClient(connect_timeout=8, read_timeout=15, max_attempts=2, max_redirects=0)
    run = _json_get(client, f"{_API}/actions/runs/{int(run_str)}")
    if (
        run.get("id") != int(run_str)
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") != _REPO
        or run.get("event") != "push"
        or run.get("head_branch") != _BRANCH
        or run.get("head_sha") != head
        or run.get("path") != _WORKFLOW
        or run.get("status") != "in_progress"
    ):
        raise ValueError("SSQ GH push attestation lacks exact server run/branch binding")
    created_at = _utc(run.get("created_at"))
    ancestry = _verify_append_only_branch(client, head, issue)
    pred, model_commit, target_date = _validate_frozen_prediction_payload(
        prediction, issue, created_at,
    )
    print(json.dumps({
        "schema": "ssq-frozen-push-candidate-v1",
        "status": "VALIDATION_ONLY",
        "github_run_id": int(run_str),
        "github_server_created_at": run["created_at"],
        "exact_commit": head,
        "target_issue": issue,
        "target_date": target_date,
        "model_source_commit": model_commit,
        "trusted_ancestry": ancestry,
        "freeze_hash": pred["freeze_hash"],
        "qualified_count": 0,
        "promotion_authorized": False,
        "official_actual_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
