# V4.7 live per-game freeze deadline

Authority: sole master Issue #468 and existing Draft PR #467 at baseline
`a0c52fa167fae17bd766c9d0209528afcad1a493`; continue the authorized implementation.
User-facing date: 2026-10-23 America/New_York. Existing filenames dated Oct 24
are preserved; no evidence is backdated.

## Intent and root cause

`advance_game_workspace` samples the live clock before computing all six cards
and before SQLite lock acquisition. The same stale value then authorizes and
dates a new transaction even if computation, lock wait or writes cross cutoff.
This violates the existing no-late-freeze contract for the persistent Bot.

## Chosen approach

Re-sample the local clock inside the acquired transaction and immediately before
commit. Reject a time outside `[as_of, sales_cutoff)` and roll back every row.
Generate all six cards before insertion. Sample/check the final local time before
inserting the run row, after the six card writes, so its immutable timestamp
records that boundary. The atomic transaction publishes all seven rows together.
Explicit `observed_at` continues to be a fixed synthetic API clock. This is a
local engineering guard; clock manipulation, commit latency and external time
trust remain blocked pending actual approved RFC3161 proof with accuracy.

Alternatives: a single start-of-tick check is the reproduced defect; adding a
second Harness, scheduler, or changing model code is outside the authorized line.
This small existing-contract repair needs no new product/architecture decision.

## Constraints and acceptance

- Same CLI, SQLite file, per-game tables and same PR branch. Do not rewrite old runs.
- Keep five candidate models, fixed Random NULL, formal eight slots and main.
- Real model/SQLite tests with only the clock controlled reproduce late admission.
- Cutoff equality is blocked after lock and before commit; no partial six-arm freeze.
- Successful freeze stores the final precommit local observation. Post-cutoff replay
  uses original immutable records. Explicit synthetic clock tests remain compatible.
- Run full existing suite, independent adversarial/whole-branch review and exact
  HEAD Ubuntu/Windows CI. Preserve RED failures as evidence.
- Process termination recovery may be checked as synthetic engineering only;
  physical Windows power-loss/boot remains NOT_VERIFIED.
- Source history/cutoff authentication, RFC3161 qualification, DLT69/2880 and real
  future paired-NULL research remain separate unresolved gates. formal_A=0; NO_EDGE.
