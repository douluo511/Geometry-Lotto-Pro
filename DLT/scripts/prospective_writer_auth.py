"""Current-main DLT prospective STAGING: no PR/head can write the ledger.

Account-authorized promotion requires a separately reviewed, version-frozen
writer workflow. PlanOnly/live CI cannot mutate historical cohorts.
"""
from __future__ import annotations

import argparse


def writer_authorized(event_name: str, head_ref: str, ref: str) -> bool:
    # Explicit deny-by-default. Never interpret PR branch names as authority.
    return False


def _self_test() -> None:
    probes = (
        ("pull_request", "research/dlt-prospective-protocol-v2-20261006", "refs/pull/293/merge"),
        ("pull_request", "research/dlt-current-main-prospective-readonly-20261008", "refs/pull/380/merge"),
        ("workflow_dispatch", "", "refs/heads/main"),
        ("workflow_dispatch", "", "refs/heads/research/dlt-current-main-prospective-readonly-20261008"),
        ("push", "main", "refs/heads/main"),
    )
    assert all(not writer_authorized(*probe) for probe in probes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("PROSPECTIVE_READ_ONLY_AUTH_SELF_TEST=PASS")
        return 0
    print("true" if writer_authorized(args.event_name, args.head_ref, args.ref) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
