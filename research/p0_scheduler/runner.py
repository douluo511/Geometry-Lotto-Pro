"""P0 unattended schedule evidence. No lottery/model/API calls.

The ledger lives on a dedicated Git branch, never on main or V4.7 formal data.
An event is only durable after the enclosing GitHub Actions job pushes and
independently reloads the remote ledger. Hashes show content integrity, not
independent trusted timestamping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL = "SSQDLT_P0_SCHEDULE_V1"
REL = Path("research/p0_ledger")
ZERO = "0" * 64


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _checked(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("sha256"), str):
        raise ValueError("missing ledger hash")
    source = {k: v for k, v in payload.items() if k != "sha256"}
    if _hash(source) != payload["sha256"]:
        raise ValueError("ledger hash mismatch")
    return payload


def _sealed(payload: dict) -> dict:
    return {**payload, "sha256": _hash(payload)}


def _write_once(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")


def _read(path: Path) -> dict:
    return _checked(json.loads(path.read_text(encoding="utf-8")))


def _empty_state() -> dict:
    return _sealed({
        "protocol": PROTOCOL,
        "count": 0,
        "events": [],
        "latest_receipt_sha256": ZERO,
    })


def verify(ledger_root: Path, expected_run_id: str | None = None) -> dict:
    """Verify every immutable event and the state hash, not merely the last."""
    directory = ledger_root / REL
    path = directory / "state.json"
    if not path.exists():
        if directory.exists() and any(directory.rglob("*.json")):
            raise ValueError("orphaned receipts without ledger state")
        if expected_run_id is not None:
            raise ValueError("expected persisted run not found")
        return _empty_state()

    state = _read(path)
    if (state.get("protocol") != PROTOCOL
            or type(state.get("count")) is not int
            or state["count"] < 0
            or not isinstance(state.get("events"), list)
            or state["count"] != len(state["events"])):
        raise ValueError("invalid state schema or count")

    previous = ZERO
    seen_runs: set[str] = set()
    scheduled = 0
    for seq, entry in enumerate(state["events"], start=1):
        if not isinstance(entry, dict):
            raise ValueError("invalid event index")
        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9]+", run_id):
            raise ValueError("invalid indexed run id")
        relative = f"events/{seq:06d}-{run_id}.json"
        if entry.get("path") != relative:
            raise ValueError("invalid indexed event path")
        event = _read(directory / relative)
        if (event.get("protocol") != PROTOCOL
                or event.get("sequence") != seq
                or event.get("run_id") != run_id
                or event.get("previous_receipt_sha256") != previous
                or event.get("sha256") != entry.get("sha256")
                or event.get("trigger") not in ("schedule", "workflow_dispatch")
                or type(event.get("run_attempt")) is not int
                or event["run_attempt"] < 1
                or event.get("paid_api_calls") != 0
                or event.get("formal_v47_modified") is not False):
            raise ValueError("invalid linked event")
        if run_id in seen_runs:
            raise ValueError("duplicate run id in ledger")
        seen_runs.add(run_id)
        previous = event["sha256"]
        scheduled += int(event["trigger"] == "schedule")
    if state.get("latest_receipt_sha256") != previous:
        raise ValueError("ledger chain head mismatch")
    actual_files = {p.relative_to(directory).as_posix()
                    for p in directory.glob("events/*.json")}
    expected_files = {x["path"] for x in state["events"]}
    if actual_files != expected_files:
        raise ValueError("orphaned or missing event files")
    if expected_run_id is not None and expected_run_id not in seen_runs:
        raise ValueError("expected remote run id missing")
    return {**state, "scheduled_observed": scheduled}


def record(ledger_root: Path, env: dict, *, inject_failure: bool = False) -> dict:
    """Append one event. Caller must Git-commit/push and reload before PASS."""
    if env.get("GITHUB_ACTIONS") != "true":
        raise ValueError("must execute on GitHub Actions")
    if env.get("GITHUB_REPOSITORY") != "douluo511/Geometry-Lotto-Pro":
        raise ValueError("unexpected repository")
    trigger = env.get("GITHUB_EVENT_NAME")
    if trigger not in ("schedule", "workflow_dispatch"):
        raise ValueError("not an approved trigger")
    run_id = env.get("GITHUB_RUN_ID", "")
    attempt = env.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("invalid Actions run metadata")
    state = verify(ledger_root)
    if any(item["run_id"] == run_id for item in state["events"]):
        return {"action": "ALREADY_RECORDED", "run_id": run_id,
                "events": state["count"],
                "scheduled_observed": state.get("scheduled_observed", 0)}

    seq = state["count"] + 1
    event = _sealed({
        "protocol": PROTOCOL,
        "sequence": seq,
        "run_id": run_id,
        "run_attempt": int(attempt),
        "trigger": trigger,
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "workflow_commit_sha": env.get("GITHUB_SHA", ""),
        "run_url": f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{run_id}",
        "previous_receipt_sha256": state["latest_receipt_sha256"],
        "restored_previous_events": state["count"],
        "paid_api_calls": 0,
        "research_only": True,
        "formal_v47_modified": False,
        "random_null_modified": False,
        "result_sync_performed": False,
        "prediction_performed": False,
    })
    relative = f"events/{seq:06d}-{run_id}.json"
    directory = ledger_root / REL
    _write_once(directory / relative, event)
    entries = state["events"] + [{
        "path": relative, "run_id": run_id, "sha256": event["sha256"]}]
    updated = _sealed({
        "protocol": PROTOCOL,
        "count": seq,
        "events": entries,
        "latest_receipt_sha256": event["sha256"],
    })
    tmp = directory / f"state.json.{run_id}.tmp"
    _write_once(tmp, updated)
    os.replace(tmp, directory / "state.json")
    if inject_failure:
        raise RuntimeError("injected failure before external Git commit/push")
    verified = verify(ledger_root, expected_run_id=run_id)
    return {"action": "LOCAL_RECORD_CREATED_NOT_YET_DURABLE",
            "run_id": run_id, "events": verified["count"],
            "scheduled_observed": verified["scheduled_observed"],
            "restored_previous_events": seq - 1,
            "receipt_sha256": event["sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "verify"))
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--expected-run-id")
    args = parser.parse_args()
    if args.action == "record":
        report = record(args.ledger, dict(os.environ))
    else:
        state = verify(args.ledger, expected_run_id=args.expected_run_id)
        report = {"action": "REMOTE_PERSISTENCE_VERIFIED",
                  "events": state["count"],
                  "scheduled_observed": state.get("scheduled_observed", 0),
                  "last_receipt_sha256": state["latest_receipt_sha256"],
                  "expected_run_id": args.expected_run_id,
                  "two_scheduled_runs_observed":
                      state.get("scheduled_observed", 0) >= 2}
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
