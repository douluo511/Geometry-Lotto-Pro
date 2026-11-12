"""Append attempt-qualified research receipts without rewriting earlier runs."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from research.ssqdlt_research_ledger_audit import (
    PINNED_SCORER_SHA, _paths, load_json, scan_ledger,
)


def save_tick_attempt(ledger: Path, wrapper: dict) -> Path:
    ledger = Path(ledger)
    run_id = wrapper.get("github_run_id")
    attempt = wrapper.get("github_run_attempt")
    if (not isinstance(run_id, str) or not run_id.isascii() or not run_id.isdecimal()
            or not isinstance(attempt, str) or not attempt.isascii() or not attempt.isdecimal()):
        raise ValueError("INVALID_ACTIONS_ATTEMPT")
    name = f"{run_id}-attempt-{attempt}.json"
    raw = (json.dumps(wrapper, sort_keys=True, ensure_ascii=False,
                      indent=2, allow_nan=False) + "\n").encode("utf-8")
    # Validate only this new wrapper; do not regenerate any historical record.
    with tempfile.TemporaryDirectory(prefix="ssqdlt-tick-check-") as temporary:
        probe = Path(temporary) / "research" / "ticks" / name
        probe.parent.mkdir(parents=True)
        probe.write_bytes(raw)
        scan_ledger(Path(temporary))
    list(_paths(ledger))  # Reject linked/ambiguous evidence destinations first.
    folder = ledger / "research" / "ticks"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / name
    legacy = folder / f"{run_id}.json"
    if legacy.exists() and load_json(legacy).get("github_run_attempt") == attempt:
        if load_json(legacy) != wrapper:
            raise FileExistsError("CONFLICT_WITH_IMMUTABLE_LEGACY_ATTEMPT")
        return legacy
    # Stage outside research/, fsync, then atomically publish without overwrite.
    with tempfile.TemporaryDirectory(prefix=".ssqdlt-stage-", dir=ledger) as temporary:
        staged = Path(temporary) / name
        with staged.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staged, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise FileExistsError("CONFLICT_WITH_IMMUTABLE_ATTEMPT") from None
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    wrapper = {
        "schema": "SSQDLT_ACTIONS_RESEARCH_TICK_V1",
        "github_run_id": os.environ["GITHUB_RUN_ID"],
        "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "trigger": os.environ["GITHUB_EVENT_NAME"],
        "workflow_source_commit": os.environ["GITHUB_SHA"],
        "pinned_formula_commit": PINNED_SCORER_SHA,
        "report": load_json(args.report),
    }
    print(save_tick_attempt(args.ledger, wrapper))


if __name__ == "__main__":
    main()
