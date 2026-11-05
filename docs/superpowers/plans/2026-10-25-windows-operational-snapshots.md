# Windows operational snapshot handoff implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution of this single integrated repair.

**Goal:** Make the existing Windows operational caller pass explicit SSQ/DLT snapshots to the already implemented Python CLI without weakening admission.

**Architecture:** Extend only original invoke_closed_loop.ps1 configuration routing. Existing Python runner performs all validation/freezing/scoring. No new service, model, seed or formal sample.

**Tech Stack:** Windows PowerShell5.1, Python3.11/unittest, existing two-platform GitHub Actions.

**Spec:** docs/superpowers/specs/2026-10-25-windows-operational-snapshots.md

## Global constraints

Sole Issue468 / DraftPR467; unchanged main, original data, models, seeds, NULL and formal Holm family. No task install, security-policy change, purchase, fabricated target or backfilled freeze. Runtime source f595659 remains immutable until replacement is independently byte-verified.

## Review focus

- Paths containing spaces retain native argument boundaries.
- One malformed/missing game does not block the other or fake its freeze.
- New config fields cannot be silently ignored by legacy modes.
- Existing bundle conflicts are still rejected before side effects.
- Per-worker timeout admission fits the existing600-second host budget with headroom; not a hard tick-duration claim.

## Task1: Complete caller configuration boundary

- [ ] Add real PowerShell tests in research/harness_v46/tests/test_windows_operational_snapshots.py for both-game freeze/idempotence, malformed-SSQ isolation, invalid mode combinations, and120.001-second admission rejection. Use the default PowerShell entrypoint, no execution-policy override.
- [ ] Execute the tests before implementation; if local host policy prevents observation, retain exact failure and use test-only exact-SHA Windows CI as authoritative RED. Publish only test/spec/plan to existing PR with expected-head lease.
- [ ] In research/harness_v46/invoke_closed_loop.ps1 detect new config fields, reject non-operational use, pass each nonempty path to its existing Python flag, retain old conflicts; cap worker timeout120 and correct four-stage comment.
- [ ] Run focused tests and full research/harness_v46/tests regression. Capture all local host failures without policy bypass or skips. Run original complete suite on precise candidate SHA Windows/Ubuntu CI.
- [ ] Fresh independent reviewer checks original/changed script, tests and counters; retain scope limits and any failure. Publish final reviewed increment, reverify exact final SHA CI and all tracked source bytes before changing runtime pointer/handoff documentation. Update only Issue468 with concrete new evidence; preserve formal_A=0/NO_EDGE.

Ruling: this is a direct completion of already authorized continuous-operation behavior, not a new product/design choice requiring renewed approval. Historical research is unchanged and not rerun.

