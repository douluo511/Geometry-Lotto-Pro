# V4.7 numeric issue identity: freeze and cumulative denominator audit

Base: PR #450, `664f8b6dc2adf41b47063bb58cd6dd1747c7df6c`.
Scope: isolated research patch; no main merge, V4.5 formal-slot change, model
formula change, NULL seed change, historical rewrite, purchase, or edge claim.

## Reproduced failure and root cause

An unchanged synthetic snapshot with target `29999`, followed by the same
snapshot with target `029999`, created two complete dual-game freezes in one
ledger. Cumulative review counted two observations per game for one numeric
issue. The alternative issue spelling also changed the SHA256-derived NULL
selections: SSQ `[4,10]` versus `[27,7]`; DLT `[35,8]` versus `[10,31]`.
These are synthetic counterexamples, never real predictions or outcomes.

Snapshot chronology already compares issues numerically. The scheduler guard
and cumulative duplicate check instead compared raw text, allowing inconsistent
identities. The fix compares their integer identities while preserving every
original issue string, manifest, frozen number and source attribution. Existing
guards with leading zeros remain readable and block a second freeze. Guards
are inspected inside the existing write transaction; no migration rewrites them.

The patch does not canonicalize model input or issue fresh NULL predictions.
Existing single-run reports keep their frozen identities. Across databases,
cumulative review rejects numeric issue collisions in either input order.

## Verification evidence

- Exact baseline export: all 54 required file blobs matched GitHub blob SHAs.
- Baseline Windows local suite: 203 tests, OK. An earlier incomplete-export run
  failed because SSQ/DLT parser source files were missing; dependencies were
  then exported and verified before taking the passing baseline.
- TDD RED: 2 new tests, 10 failing subcases; the expected GateError was absent.
- TDD GREEN: the same 2 tests passed after the production fix.
- Full Windows local suite: 205 tests, OK.
- Tests cover both games, leading-zero aliases in both directions, Unicode
  decimal aliases, distinct non-colliding issues, exact retries, database
  immutability after rejected cumulative replay, and full SQL-content rollback
  after a rejected freeze. Existing disk-failure and cutoff tests remain active.

Reproduce from the final patch commit (recorded in its Draft PR):

```sh
python -m pip install requests==2.34.2
python -m unittest discover -s research/harness_v46/tests -v
```

The unchanged workflow explicitly checks out `pull_request.head.sha` and checks
that `git rev-parse HEAD` matches before running Windows/Ubuntu tests. Actual
run URLs, checkout SHAs and original log summaries belong in the PR evidence;
the local run alone does not establish Ubuntu CI success.

## Trust boundaries and remaining blockers

This prevents duplicate counting within the submitted cohort. It cannot prove
that the caller submitted all eligible cycles or prevent selection of a single
unverified alias stream from separate ledgers. Caller-provided results remain
CALLER_UNVERIFIED. A locally hashed report is not an independent timestamp.

Official cross-source raw history/target/cutoff validation (G00/G01), authenticated
postdraw result acquisition, independent external pre-cutoff timestamp proof,
historical 12-hypothesis preregistration, physical Windows boot/outage/P0 tests,
and the historical DLT 69/2880 negative-control investigation remain BLOCKED or
unresolved. No qualified forward sample was generated in this patch.

Separate whole-system verdicts remain ENGINEERING_PASS=NOT_YET,
RESEARCH_VALID=NO, D2_EDGE_CONFIRMED=NO, formal_A=0, NO_EDGE, even if this
bounded regression patch passes both CI jobs.

## Future-only algorithm hypothesis (proposal, unregistered, not implemented)

A slower EWMA decay of 0.97 (input weight 0.03) over the last 120 admitted
draws may reduce sensitivity to short-lived fluctuations compared with the
current 0.92/0.08 EWMA. Fix numeric tie-breaking and ticket generation before
the first observation; do not choose decay using these failures or retrospective
hit rates. Evaluate SSQ and DLT separately against the theoretical D2 baseline
and the same-draw fixed Random NULL stream.

Before any validation, register a separate model version, source/parameter SHA,
official issue representations, cohort inclusion/missing-data rules, two-game
hypothesis family, test statistic and fixed sample horizon in an independently
timestamped protocol. A proposed horizon is 1,000 qualified future draws per
game, no optional stopping, with Holm correction across the two game hypotheses
and both baseline/NULL comparisons required for success. This proposal is not
the authenticated legacy family and cannot enter its existing 12 slots.
Failure to meet the prespecified criterion falsifies the proposed advantage;
missing trust evidence blocks eligibility rather than counting as success.
