# SSQ + DLT P0: unattended schedule and durable recovery ledger

Research infrastructure only. Not a lottery forecast. No model/API charges.
This is an isolated P0 heartbeat that tests unattended GitHub Actions,
append-only event receipts, and restart from committed state.
It does not edit V4.7, the formal frozen ledger, or the fixed Random NULL.

## Registration and schedule

- Workflow: .github/workflows/ssqdlt-p0-scheduler.yml on main
- UTC cron: 17 16,17 * * * (16:17 and 17:17 UTC daily).
- Manual workflow_dispatch is only for diagnostics. It cannot count as a
  scheduled unattended run.
- GitHub can delay or skip scheduled events. Never fabricate missed runs.
- Permission: contents write, solely for the dedicated ledger branch.
- No OPENAI_API_KEY, paid models, or lottery data requests.

## Persistent state

The first successful workflow creates branch ssqdlt-p0-ledger-v1.
Later runs fetch this branch into a clean Git worktree, verify the entire
SHA256-linked JSON event chain, and append exactly one event for each unique
GitHub run ID. All event receipts are individually immutable by program policy;
state.json is the mutable index/checkpoint. Both change together in one commit
on the separate ledger branch, never on main.

The workflow then fetches the pushed remote branch again and validates the
run from a new Git worktree in a separate Python process. A subsequent
scheduled job independently restores previous remote ledger state.

A failure before Git push leaves no durable event. A later run resumes from
the last persisted state instead of inventing a missing trigger.
The offline test suite includes injected precommit failure and restart from
a copy of the pre-failure persisted state.

Git SHA256 content checks and GitHub-run metadata aid audit. They do not
constitute an independently trusted predraw timestamp; repo administrators
can rewrite branches and GitHub log retention is finite.

## Tests

From repository root:

    python -m unittest discover -s tests -p 'test_p0_scheduler.py' -v

These tests check idempotence, run-type isolation, hash tampering, orphaned
events, and crash-before-push restart. Tests alone do not prove P0 deployment.

## Acceptance criteria

1. Registered: the workflow exists on main with schedule enabled.
2. Persistence: a successful scheduled run produces an actual GitHub run ID,
   a pushed receipt, and a fresh remote reload verification.
3. Unattended: two distinct successful schedule-triggered run IDs appear in
   the persistent ledger. Manual dispatches never count.
4. Restart: the later run loads and verifies the earlier remote ledger chain.
5. Failure recovery: fault-injection test is green. Any real failed run and
   subsequent recovery must be documented separately, not assumed.
6. Isolation: no changes to V4.7 official selectors, formal predictions,
   frozen ledger, or original Random NULL.

Keep P0 UNVERIFIED until externally observed Actions evidence satisfies its
gates. This infrastructure does not imply P1 draw synchronization or scoring.
