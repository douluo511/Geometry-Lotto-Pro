# Integrate score receipts and complete local-ledger study

The research user requires actual pre-draw frozen model outputs, independently
authenticated later outcomes, D1-D5/D2 and fixed paired NULL feedback, then future
model versions. Actual output is currently forbidden until target and cutoff
authentication. This integration prepares one coherent frozen-ledger feedback
path while that external blocker remains; all new executions are synthetic.

Fixed source bases: PR465 `8b56de0c9d720d5aec10e49d304416f497862874` and the
separately reviewed PR449 addition at `91b6ca88693ae6dc1c158a1d7a82644dc2101595`.
The latter diverged from the older449 used by451/452. It adds complete local
roster study replay but omits the later time and numeric issue-alias guards.

## Approach and ownership

I choose a child of465 with a targeted port into `prospective_cycle.py`.
Replacing that file with449 would remove postdraw chronology and cumulative
commands. Rebasing the older published PR chain would change existing evidence
identities and require resolving unrelated changes. This child keeps those
histories and ports only score/study functionality with adversarial tests.
This is an implementation choice under the user's instruction to execute;
it is not a new user approval of source authority, study design, or TSA policy.

The current workspace is a dedicated, non-Git materialized source snapshot;
all59 baseline files match465. There is no local main checkout to edit.
GitHub objects will be built on465, and a new Draft branch will hold this work.

## Required behavior

`evaluate_after_draw(database, run_id, result_bundle, *, observed_at=None)`
retains451 validation and D1-D5 feedback. It additionally binds the exact
validated two-game caller outcome, including `drawn_at`, into
`scoring_inputs.result_bundle`, its digest, and a final `score_receipt_sha256`.
No claim becomes authenticated. The receipt remains deterministic after the
time gates pass: current observation time is a check, not a receipt timestamp.

`summarize_prospective_receipts(database, receipts, *, observed_at=None)` checks
outer receipt hash, replays every receipt through that same guarded evaluator,
and requires exact report equality. A caller rehash cannot authorize changed
score bits, outcome times, source labels or model arms. The original database
is always read-only.

Require every run registered in the supplied local ledger, including a run
awaiting an outcome. Missing, duplicate, unrelated or incomplete receipts block
the study. This is local coverage only: external schedule, other databases,
privileged replacement and original preregistration remain unverified. Two
numeric issue spellings such as29999/029999 denote one game target and cannot
both increase the sample count. Raw original spelling remains in frozen data.

Only ledger-replayed D2 bits enter the existing fixed12-entry descriptive
statistical family: baseline, same-draw NULL paired counts and Holm arithmetic.
It remains an unverified family including the unregistered challenger, with
`formal_A=0`, `NO_EDGE`. It does not confirm a prospective edge or grant formal
research validity. Existing `cumulative` and all date-only/TSA paths remain.

## Invariants and exclusions

- No main merge/write, V4.5 slot/formula/parameter/NULL-seed changes or purchase.
- No genuine or calendar-candidate forecast; target/cutoff must authenticate first.
- No backdating, old-ledger mutation, official result promotion or fake timestamps.
- No transfer of449 live-intake trigger/workflow changes into this child.
- Existing465 raw observations retain their pinned original source identity;
  this change alters orchestration identity for future runs only.
- No change to statistics arithmetic or strict TSA precision requirements.
- Synthetic fixtures cannot count as actual prospective samples.

## Acceptance

Tests must first fail on465 due to absent receipt/study behavior, then pass
after integration. Cover full local roster, an unscored freeze, repeated/order
independent read-only replay, numeric duplicate aliases, rehashed score/outcome
tampering, future/early/naive observation chronology, missing `drawn_at`, forged
authority, and12 complete arms with expected frozen D2/paired-NULL counts.
Full baseline regressions, an independent final review, exact-head Windows and
Ubuntu CI with raw Ran/skip counts, full SHA, reproducible source/evidence and
remaining blockers are required before claiming component success.
