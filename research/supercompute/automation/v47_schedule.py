"""Durable, research-only V4.7 scheduled-run receipt ledger and independent audit.

No issuer API and no trusted predraw timestamp. Model forecasts remain
hypothetical; only a completed GitHub event=schedule may count as unattended.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request

from research.supercompute.v47_models import canonical

SCHEMA = "SSQDLT_V47_SCHEDULE_LEDGER_V1"
LEDGER = Path("research/v47_lab_ledger")
WORKFLOW = ".github/workflows/v47-model-lab-scheduled.yml"
REPO = "douluo511/Geometry-Lotto-Pro"
ZERO = "0" * 64


def digest(data):
    return hashlib.sha256(data).hexdigest()


def clean_state():
    return {"schema": SCHEMA, "count": 0, "last_run_id": None, "last_hash": ZERO}


def verify(working_tree, expected_run_id=None):
    """Verify the entire receipt chain and EVERY stored report, not just index."""
    folder = Path(working_tree) / LEDGER
    state_path = folder / "state.json"
    state = (json.loads(state_path.read_bytes()) if state_path.is_file()
             else clean_state())
    if state.get("schema") != SCHEMA:
        raise ValueError("ledger schema mismatch")
    records = (sorted((folder / "events").glob("*.json"))
               if (folder / "events").is_dir() else [])
    if len(records) != state.get("count"):
        raise ValueError("ledger event count mismatch")
    last_hash = ZERO
    last_id = None
    last_unified = None
    ids = set()
    for index, path in enumerate(records, 1):
        event = json.loads(path.read_bytes())
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        if (payload.get("schema") != SCHEMA or payload.get("sequence") != index
                or payload.get("event") != "schedule"
                or payload.get("workflow") != WORKFLOW
                or payload.get("branch") != "main"
                or payload.get("repository") != REPO
                or payload.get("previous_hash") != last_hash
                or type(payload.get("run_id")) is not int
                or payload["run_id"] <= 0
                or payload["run_id"] in ids
                or path.name != f"{index:08d}-{payload['run_id']}.json"):
            raise ValueError("event chain invalid")
        if event.get("event_hash") != digest(canonical(payload)):
            raise ValueError("event hash modified")
        report_path = folder / "reports" / f"{payload['run_id']}.json"
        if not report_path.is_file():
            raise ValueError("report missing")
        if digest(report_path.read_bytes()) != payload.get("report_sha256"):
            raise ValueError("report tampered")
        report = json.loads(report_path.read_bytes())
        check_report(report, allow_legacy_archive=True)
        if payload.get("unified_sha256"):
            unified_copy = folder / "reports" / f"{payload['run_id']}-unified.json"
            if (not unified_copy.is_file() or
                    digest(unified_copy.read_bytes()) != payload["unified_sha256"]):
                raise ValueError("unified forecast receipt tampered")
            check_unified_report(json.loads(unified_copy.read_bytes()))
            last_unified = payload["unified_sha256"]
        ids.add(payload["run_id"])
        last_id = payload["run_id"]
        last_hash = event["event_hash"]
    if last_unified is not None:
        latest = folder / "latest_unified.json"
        if not latest.is_file() or digest(latest.read_bytes()) != last_unified:
            raise ValueError("inherited last-champion index changed")
    if state.get("last_run_id") != last_id or state.get("last_hash") != last_hash:
        raise ValueError("ledger checkpoint not consistent")
    if expected_run_id is not None and int(expected_run_id) not in ids:
        raise ValueError("expected run absent from persisted ledger")
    return {"status": "PASS", "count": len(records), "last_run_id": last_id,
            "last_hash": last_hash, "run_ids": sorted(ids),
            "remote_persistence": expected_run_id is not None}


def check_report(report, allow_legacy_archive=False):
    if (report.get("schema") != "SSQDLT_11_COMPONENT_RESEARCH_V1"
            or report.get("edge") != "NO_EDGE"
            or report.get("formal_prediction") is not False
            or set(report.get("games", {})) != {"ssq", "dlt"}):
        raise ValueError("not an isolated two-game research report")
    for game, section in report["games"].items():
        if (section.get("source_status") != "REPOSITORY_HISTORICAL_NOT_LIVE_VERIFIED"
                or section.get("models", {}).get("edge") != "NO_EDGE"
                or section.get("models", {}).get("strictly_past_only") is not True
                or section.get("models", {}).get("independent_test_tail") is not True
                ):
            raise ValueError(f"missing research guard: {game}")
        models = section["models"].get("models", {})
        required = {"HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger"}
        legacy_ok = (allow_legacy_archive and len(models) >= 3
                     and {"HOT60", "EWMA"}.issubset(models))
        if set(models) != required and not legacy_ok:
            raise ValueError(f"missing current research models: {game}")




def check_unified_report(payload):
    """Validate inherited research output before it can enter evidence ledger."""
    if (payload.get("schema") != "SSQDLT_V47_UNIFIED_RUN_V1"
            or set(payload.get("games", {})) != {"ssq", "dlt"}
            or payload.get("edge") != "NO_EDGE"
            or payload.get("formal_prediction") is not False):
        raise ValueError("not a unified dual-game research report")
    required = {"1:HOT60", "2:EWMA", "3:ShrinkMix", "4:Pairwise-D2",
                "5:Challenger", "6:statistics", "7:combination_freeze_score",
                "8:geometry", "9:probability_simulation",
                "10:uncalibrated_physics", "11:M1_M2_M3"}
    families = {"HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger"}
    for game, report in payload["games"].items():
        if (report.get("game") != game
                or set(report.get("requirement_modules", [])) != required
                or set(report.get("model_family_tickets", {})) != families
                or len(report.get("proposed_tickets", [])) != 3
                or report.get("edge") != "NO_EDGE"
                or report.get("formal_prediction") is not False
                or report.get("evolution", {}).get("uses_future_draws") is not False):
            raise ValueError("incomplete unified research evidence: " + game)


def record(working_tree, report_path, run_id, run_attempt, commit_sha, event, unified_report_path=None):
    """Fail closed; record only a genuine claimed schedule (independent audit later)."""
    run_id = int(run_id)
    if (event != "schedule" or run_id <= 0 or int(run_attempt) < 1
            or len(commit_sha) != 40 or
            any(c not in "0123456789abcdef" for c in commit_sha.lower())):
        raise ValueError("invalid schedule context")
    report_data = Path(report_path).read_bytes()
    check_report(json.loads(report_data))
    unified_data = Path(unified_report_path).read_bytes() if unified_report_path else None
    if unified_data is not None:
        check_unified_report(json.loads(unified_data))
    state_info = verify(working_tree)
    if run_id in state_info["run_ids"]:
        raise ValueError("run already appended; rerun must not modify receipt")
    folder = Path(working_tree) / LEDGER
    sequence = state_info["count"] + 1
    payload = {"schema": SCHEMA, "sequence": sequence, "run_id": run_id,
               "run_attempt": int(run_attempt), "event": event,
               "workflow": WORKFLOW, "branch": "main", "repository": REPO,
               "code_sha": commit_sha, "report_sha256": digest(report_data),
               "previous_hash": state_info["last_hash"],
               "recorded_utc": datetime.now(timezone.utc).isoformat()}
    if unified_data is not None:
        payload["unified_sha256"] = digest(unified_data)
    receipt = {**payload, "event_hash": digest(canonical(payload))}
    report_copy = folder / "reports" / f"{run_id}.json"
    receipt_path = folder / "events" / f"{sequence:08d}-{run_id}.json"
    report_copy.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with report_copy.open("xb") as handle:
        handle.write(report_data)
    if unified_data is not None:
        unified_copy = folder / "reports" / f"{run_id}-unified.json"
        with unified_copy.open("xb") as handle:
            handle.write(unified_data)
        # latest file is a mutable index only; original per-run reports remain create-only.
        with (folder / "latest_unified.next.json").open("xb") as handle:
            handle.write(unified_data)
        os.replace(folder / "latest_unified.next.json", folder / "latest_unified.json")
    with receipt_path.open("xb") as handle:
        handle.write(canonical(receipt))
    state = {"schema": SCHEMA, "count": sequence,
             "last_run_id": run_id, "last_hash": receipt["event_hash"]}
    with (folder / "state.next.json").open("xb") as handle:
        handle.write(canonical(state))
    os.replace(folder / "state.next.json", folder / "state.json")
    result = verify(working_tree, expected_run_id=run_id)
    return result


def github_run(run_id, token):
    url = f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "Authorization": "Bearer " + token,
                      "User-Agent": "V47-Unattended-Research-Audit",
                      "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def audit(working_tree, token):
    """Require two externally confirmed COMPLETED SUCCESS schedule runs."""
    verified = verify(working_tree)
    folder = Path(working_tree) / LEDGER / "events"
    good, excluded = [], []
    for path in sorted(folder.glob("*.json")):
        event = json.loads(path.read_bytes())
        try:
            run = github_run(event["run_id"], token)
            path_in_run = str(run.get("path", "")).split("@")[0]
            if (run.get("id") == event["run_id"]
                    and run.get("event") == "schedule"
                    and run.get("status") == "completed"
                    and run.get("conclusion") == "success"
                    and run.get("head_branch") == "main"
                    and run.get("head_sha") == event["code_sha"]
                    and path_in_run == WORKFLOW
                    and run.get("repository", {}).get("full_name") == REPO):
                good.append(event["run_id"])
            else:
                excluded.append({"run_id": event["run_id"],
                                 "reason": "not externally verified completed schedule"})
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            excluded.append({"run_id": event["run_id"], "reason": type(exc).__name__})
    # A later successfully completed scheduled run must recover a prior hash.
    prior_recovered = len(good) >= 2 and verified["count"] >= 2
    return {"status": "PASS" if prior_recovered else "UNVERIFIED",
            "workflow": WORKFLOW,
            "scheduled_completed_success_count": len(set(good)),
            "scheduled_completed_success_run_ids": sorted(set(good)),
            "remote_ledger_verified": verified["status"] == "PASS",
            "prior_remote_prefix_recovered": prior_recovered,
            "excluded": excluded,
            "live_issuer_source_verified": False,
            "trusted_predraw_seal_verified": False,
            "physical_windows_restart_verified": False,
            "model_edge": "NO_EDGE"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("record")
    r.add_argument("--ledger", required=True, type=Path)
    r.add_argument("--report", required=True, type=Path)
    r.add_argument("--run-id", required=True, type=int)
    r.add_argument("--run-attempt", required=True, type=int)
    r.add_argument("--commit-sha", required=True)
    r.add_argument("--event", required=True)
    r.add_argument("--unified-report", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("--ledger", required=True, type=Path)
    v.add_argument("--expected-run-id", type=int)
    a = sub.add_parser("audit")
    a.add_argument("--ledger", required=True, type=Path)
    a.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.mode == "record":
        result = record(args.ledger, args.report, args.run_id, args.run_attempt,
                        args.commit_sha, args.event, args.unified_report)
    elif args.mode == "verify":
        result = verify(args.ledger, args.expected_run_id)
    else:
        result = audit(args.ledger, os.environ["GITHUB_TOKEN"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("xb") as output:
            output.write(canonical(result))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
