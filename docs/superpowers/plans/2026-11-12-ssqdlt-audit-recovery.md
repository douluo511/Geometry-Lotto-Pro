# SSQDLT audit recovery implementation plan

> For agentic workers: use superpowers:executing-plans; implementation is inline,
> independent AI review has already reproduced the five defects.

**Goal:** Make the existing research auditor fail closed on demonstrated fraud
and remain reproducible across checkout platforms and GitHub retries.

**Architecture:** Existing audit module plus pinned original scorer; no new
Harness. Preserve old receipts, append new retry receipts, compare exact bytes.

**Tech Stack:** Python 3.11 standard library, Git, existing GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-12-ssqdlt-audit-recovery.md`

## Global constraints

Keep `formal_A=0`, `NO_EDGE` and fixed V4.7 NULL. Never rewrite evidence.
Do not count `push`, `workflow_dispatch` or repeated attempts as new schedules.
Do not claim source authenticity, TSA, physical restart or formal acceptance.

## Review focus

Merge-hidden deletion/modification; canonical scanner/replayer file-set parity;
score claims with non-result bytes; rerun identity drift/double counting; Git
clean filters that hide byte changes. Each is covered below by a regression.

## Task 1: auditor and writer correction

Files: existing audit module/test/workflow, a focused recovery test file,
and a small attempt-receipt writer used by the existing workflow.

- [ ] Reproduce merge, nested path, false score, CRLF and attempt defects with
  real temporary Git repositories and controlled API responses; save RED log.
- [ ] Enforce exact bytes/canonical paths and inspect merge ancestry.
- [ ] Add `replay_pinned_scores(ledger, scorer_root)` using an archive of
  `199cc2a2797f11b8179aaa6649f0649613c72010`, isolated Python and strict JSON.
  Refuse publishing score claims without replay; compare complete counters.
- [ ] Fetch `/runs/{id}/attempts/{attempt}`; accept attempt-qualified tick paths;
  deduplicate schedule counts by run ID and retain failed attempt evidence.
- [ ] Test and use append-only attempt writer; rerun cannot overwrite originals.
- [ ] Run full affected suite and actual cold remote replay; save GREEN log.
- [ ] Push to existing PR #472; inspect exact-head dual-OS CI and raw logs.

## Task 2: real operations and evidence

- [x] Query main, existing PR, workflow and all schedule run metadata.
- [x] Run existing main research loop by real workflow_dispatch; do not relabel.
- [x] Run pinned official intake on actual network, retaining original bodies.
- [ ] Independently audit source bundle and publish concrete evidence/limits.
- [ ] If corrections pass, apply only the reviewed research workflow changes;
  verify deployment run, retry recovery and real schedule state separately.
- [ ] Append results to Issue #468 and PR #472; retain Draft if any deployment
  gate is missing. Save downloadable evidence bundle and digest.
