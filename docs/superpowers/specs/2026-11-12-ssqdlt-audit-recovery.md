# Issue #468: repair audit acceptance and retry evidence

Continue existing Draft PR #472. The user's current request authorizes actual
GitHub operation, verification and fixes. No new Harness, predictor, seed,
formal sample, or rewritten historical evidence is introduced.

## Observed defects

Independent AI review of `00edd8ca1e1363518a07036f7af4072fb65411ea`
reproduced merge-hidden modification/deletion, nested scores omitted by the
pinned scorer, standalone acceptance of invented score bits, latest-attempt
identity drift, and clean Windows checkout bytes differing from Git blobs.

## Approach and boundaries

Repair the existing auditor and workflow contracts. Reimplementing the lottery
parser would introduce a second score implementation; instead export and run
the existing scorer from its exact Git commit in an isolated temporary tree.
Compare complete forecast, score, raw and per-game denominators/counters.
Without that replay, a nonempty score cohort must fail closed.

Require canonical evidence paths and exact disk/Git-blob equality. Audit every
historical receipt change including merges; conservatively reject a merge that
changes any receipt relative to any parent. This costs support for merging
ledger branches, which the existing append-only writer does not need.

Query the recorded GitHub run attempt, retain old tick paths, and use new
attempt-qualified paths on retries. Count distinct successful schedule run IDs;
reruns never create extra scheduler evidence. Failed attempts remain visible.

Research workflow cadence becomes minute 17 and 47 of each UTC hour, allowing
transient source errors to recover in later ticks instead of waiting half a day.
This is an implementation decision within the requested continuous operation.
It does not guarantee GitHub timing. Require full-history audit before any new
records and again after remote re-fetch; actual run IDs/events remain the gate.

All original forecasts/raw bytes and fixed V4.7 Random NULL remain unchanged.
`formal_A=0`, `NO_EDGE`, `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`.
Git ancestry does not establish administrator-resistant WORM or trusted predraw
time. Actual schedule, manual dispatch, synthetic recovery, physical restart,
source agreement and independent source authentication remain distinct claims.

## Acceptance

Real RED then GREEN reproductions for each defect; full affected suite and
exact-head Ubuntu/Windows CI; fresh remote restore and pinned score replay;
actual Actions event/attempt metadata. Source intake preserves original bytes,
including failures. Future draws and trusted seals cannot be fabricated to
finish the current session. Deployment is conditional on those concrete checks.
