# Source date semantics correction plan

> For agentic workers: use superpowers:subagent-driven-development; implementer
> and final reviewer are separate. Checkbox steps track verified work.

**Goal:** Prevent publication/unknown source date columns from entering a
draw-date observation or official replay as if actual draw dates were known.

**Architecture:** Selectively port pinned464 research grammar and wire it
before both legacy parsing entrypoints. Preserve raw bytes before rejection;
retain the shared application parsers and every existing downstream guard.

**Tech Stack:** Python3.11, stdlib HTMLParser, requests, unittest, GitHub dualOS CI.

**Spec:** ../specs/2026-10-23-source-date-semantics-design.md

## Global constraints

No actual forecast until authenticated target/cutoff; no main write/merge,
purchase, old evidence rewrite, inferred dates, model/statistics/seed/schedule
change, fake official pass or promotion. All source claims CALLER_UNVERIFIED,
formalA0, NO_EDGE. This is a new child of fixed466 b754ec2, not a blind464 merge.

## Review focus

- Header labels must bind the actual candidate columns in the same table.
- Hidden/escaped data or malformed context release cannot borrow a safe header.
- A later bad page cannot be dropped to recover120 rows.
- Pin mismatch alone cannot prove the original semantic defect was corrected.
- Positive fixture changes cannot silently authorize original publication pages.

## Task1: Date guard and capture integration

Files: official_intake.py and recent_observation.py; new pinned semantic tests
and recent-worker integration tests; necessary explicit-header positive fixture
builders in existing tests. Parent owns README/design/delivery metadata.

- [x] Port45 semantic tests and write recent-worker failure/custody tests first.
- [x] Execute RED on466 and preserve exact failure counts/reasons.
- [x] Port only _JiangsuDateTables/_verify_jiangsu_draw_date_columns/imports and
      the original replay call, then call it in recent worker before parsing.
- [x] Align invented positive headers; retain original negative inputs and
      rejection assertions, documenting any earlier precise error ordering.
- [x] Run focused GREEN, direct original-byte rejection/hash checks, full suite.
- [x] Fresh independent reviewer verifies code, counterexamples and scope;
      repair findings with RED/GREEN before claiming completion.
- [ ] Build exact child commit/PR, attach it, run trueWindows/Ubuntu CI and
      preserve original checkout SHA/Ran/skip outputs.
- [ ] Package pinned source and evidence with quarantine/correction documents,
      remaining actual-data/target/TSA/research blockers and precise hashes.

## Ledger

The466 score/study feature is separately reviewed and its CI39979608868 passed
Windows286 and Ubuntu286/skip3 at b754ec2f9f8b2a76e4358f9a151516f4307fecd8.
Its62-file source snapshot is preserved outside the live implementation folder.
Original source-date quarantine and independent unsafe-accept probes are saved.
Implementer /root/implement_source_date_guard is responsible for TDD and source
edits; parent will independently verify and publish after a fresh review.
