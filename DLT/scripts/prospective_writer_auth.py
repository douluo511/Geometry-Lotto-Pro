from __future__ import annotations

import argparse


AUTHORIZED_BRANCH = "research/dlt-prospective-protocol-v2-20261006"


def writer_authorized(event_name: str, head_ref: str, ref: str) -> bool:
    event_name = str(event_name or "").strip()
    head_ref = str(head_ref or "").strip()
    ref = str(ref or "").strip()
    if event_name == "pull_request":
        return head_ref == AUTHORIZED_BRANCH
    if event_name == "workflow_dispatch":
        return ref == f"refs/heads/{AUTHORIZED_BRANCH}"
    return False


def _self_test() -> None:
    assert writer_authorized("pull_request", AUTHORIZED_BRANCH, "refs/pull/293/merge")
    assert not writer_authorized(
        "pull_request", "fix/dlt-prospective-service-fingerprint-20261006", "refs/pull/306/merge"
    )
    assert not writer_authorized("pull_request", "feature/untrusted", "refs/pull/999/merge")
    assert writer_authorized(
        "workflow_dispatch", "", f"refs/heads/{AUTHORIZED_BRANCH}"
    )
    assert not writer_authorized("workflow_dispatch", "", "refs/heads/main")
    assert not writer_authorized("push", AUTHORIZED_BRANCH, f"refs/heads/{AUTHORIZED_BRANCH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("PROSPECTIVE_WRITER_AUTH_SELF_TEST=PASS")
        return 0
    print(
        "true"
        if writer_authorized(args.event_name, args.head_ref, args.ref)
        else "false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
