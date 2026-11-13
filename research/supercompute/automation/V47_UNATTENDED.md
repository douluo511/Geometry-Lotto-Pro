# V4.7 research-only unattended GitHub deployment and acceptance

## Registration

- Workflow: .github/workflows/v47-model-lab-scheduled.yml (on default main).
- UTC schedule: 19:29 and 20:29 every day. GitHub may delay or skip cron runs; never infer a run merely from registration.
- Each actual scheduled event runs the SSQ and DLT 11-model research CLI with stored historical repository snapshots, fixed seed 2026, a 12-period retrospective evaluation, and 1,000 uniform Monte Carlo trials per game.
- Manual workflow_dispatch and pull_request/push checks execute preflight tests ONLY; they do not append to the schedule ledger or count towards unattended acceptance.
- The schedule workflow uses minimal contents:write permission only in the separate record job; independent audit is read-only.
- Research reports and hash-chained events are committed to ssqdlt-v47-lab-ledger-v1, never to main or to the separate P0 ledger.

## Acceptance evidence

1. REGISTRATION: schedule YAML exists on the default branch.
2. REMOTE PERSISTENCE: genuine scheduled run pushes a hashed event and full research report to branch ssqdlt-v47-lab-ledger-v1; fresh Git worktree verifies the restored state and expected GitHub run_id.
3. UNATTENDED: at least two distinct COMPLETED SUCCESS GitHub Actions runs with event=schedule, correct workflow path, main branch, code SHA and repository. Manual runs, failed, incomplete, or canceled runs cannot pass.
4. RESTART: second run starts from existing remote ledger branch, verifies prior receipts, appends one, pushes and independently reloads. This is *container/job restart recovery*, not a Windows physical reboot.
5. TAMPER / FAILURE TESTS: immutable receipts via create-only writes, linked SHA256 hashes, integrity checking of all reports, duplicate run-id rejection, missing predecessor detection, mocked external audit and restored-prefix tests.
6. INDEPENDENT AUDIT: workflow_run completion event launches .github/workflows/v47-model-lab-audit.yml, reads the remote ledger, looks up GitHub REST runs, and writes an acceptance artifact. Result is UNVERIFIED until two real completed schedule runs are externally confirmed.

## Validation commands (Windows PowerShell or Linux)

    python -m unittest discover -s research/supercompute/tests -p 'test_v47_schedule.py' -v
    python -m unittest discover -s research/supercompute/tests -p 'test_v47_models.py' -v

Read-only inspection of a cloned ledger branch:

    git fetch origin ssqdlt-v47-lab-ledger-v1
    git worktree add --detach v47-ledger origin/ssqdlt-v47-lab-ledger-v1
    python -m research.supercompute.automation.v47_schedule verify --ledger v47-ledger

All score/outcome claims are historical research only: repository snapshots are stale and NOT live official results; no issuer verification, no independent predraw timestamp and NO_EDGE. This does not deploy a Windows local service, establish Windows reboot recovery, or automatically source new lottery results.

## Production safety

- The original official V4.7 selectors, fixed RANDOM_NULL records, P0 schedule, and freeze ledger are untouched.
- GitHub Actions hosted runner resources are bounded (15-minute scheduled job). No paid API or training loop is invoked.
- The event ledger uses a Git branch with SHA256 linkage; repository administrators could still rewrite this branch. It is audit-aiding but not independently immutable or timestamp-trusted.
- A returned audit status PASS means only two completed genuine schedule-run records and cross-run persistence were verified; it does not mean better lottery forecasting.
