# Frozen score receipt integration implementation plan

> For agentic workers: use superpowers:executing-plans inline; an independent
> whole-branch reviewer verifies the final result. Steps use checkbox syntax.

**Goal:** Reconcile449 score/study additions with465 chronology, alias and
observation safeguards so future real outcomes can follow one reproducible path.

**Architecture:** Extend the existing guarded evaluator, replay every submitted
receipt through it, enforce the complete same-ledger roster, then call unchanged
12-family SHADOW arithmetic. Publish only a new child Draft of fixed465.

**Tech Stack:** Python3.11, SQLite read-only, unittest, GitHub exact-head dualOS CI.

**Spec:** ../specs/2026-10-23-study-receipt-integration-design.md

## Global constraints

No actual forecast until target/cutoff authentication; no main write/merge,
purchase, backdating, V4.5 slot/model/seed change, fabricated research or authority.
Preserve A0/NO_EDGE, CALLER_UNVERIFIED, all465 tests and current cumulative CLI.
No stats or source-parser changes; no borrowed live-intake trigger.

## Review focus

- Receipt hash alone must not validate caller-rewritten D2 or authority.
- Receipt replay must retain claimed drawn_at and local observed_at guards.
- Numeric issue aliases must not create additional independent observations.
- A locally frozen but unscored run must not disappear from the study denominator.
- A complete local roster must never imply complete official or registered coverage.

## Task1: Bound scoring inputs and complete study replay

Files: modify research/harness_v46/prospective_cycle.py; create
research/harness_v46/tests/test_prospective_study.py; append the README usage.

Interfaces: retain evaluate_after_draw(..., *, observed_at=None) and add
summarize_prospective_receipts(database, receipts, *, observed_at=None).
The existing summarize_from_frozen_runs API and cumulative CLI remain available.

- [x] Write failing receipt/study tests with explicit synthetic before/after clocks.
- [x] Run the new unittest module; preserve RED log and verify feature failures.
- [x] Add exact validated five-field result preimages and final report digest.
- [x] Port local roster/study replay from449, passing observed_at to the guarded
      evaluator and normalizing ASCII numeric issue identity before deduplication.
- [x] Add study CLI alongside cumulative; preserve old commands and source identity.
- [x] Run focused module GREEN, then complete existing suite once.
- [ ] Independently review code and adversarial gaps; reproduce/fix any finding
      with RED/GREEN evidence before full revalidation if code changed.
- [ ] Create new child commit/branch/PR; attach it, collect actual dualOS logs,
      prove expected checkout equals exact commit and record raw Ran/skip counts.
- [ ] Package reproducible source/logs/review, precise dependency SHA and blockers.

## Execution ledger

Baseline:465 is byte-verified against all59 source hashes. Its CI39941264326
passed Windows271 and Ubuntu271/skip3. Preliminary read-only contract review of
new449 reproduced loss of drawn_at and numeric duplicate counting. The integration
preserves both guards. Fourteen new tests first failed on465 (15 assertion/subtest
failures), then passed in18.410s. A fifteenth limitation test documents that a
fully recomputed legal caller outcome remains unauthenticated. Full suite:
286 tests in101.423s, OK. A synthetic subprocess probe ran score, study and
cumulative successfully with unchanged SQLite bytes. No real forecasts were made.

Final independent review and exact-head Windows/Ubuntu CI remain required
before component acceptance. Their actual results belong in the delivery
evidence; the broader source, target and research gates remain independent.
