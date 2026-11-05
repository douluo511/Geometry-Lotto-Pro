# V4.7 freeze-safety Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Honor existing cutoff and original-evidence integrity across every canonical freeze path.
**Architecture:** Fresh real clock under the original dual transaction; acquire exclusive lock before time validation; use original prior-roster replay/scoring before new cards; reject canonical identities at legacy interfaces.
**Tech Stack:** Python3.11, existing SQLite and unittest.
**Spec:** docs/superpowers/specs/2026-10-26-freeze-safety.md

## Global Constraints
Existing PR467/Issue468 only; keep runtime0fe pinned until verification. No code/parameters/seed/family changes in core/statistics; no past freeze/receipt changes, no official trust promotion, no extra Harness, no security setting change. Explicit synthetic clocks keep their documented SHADOW behavior.

## Review Focus
1. Real SQLite writer lock extends beyond cutoff.
2. Forecast or final trace work crosses cutoff; all staged rows roll back.
3. Existing malformed old JSON/receipt/card must not commit new targets.
4. Valid prior pending roster and unrelated other-game evidence still work.
5. Legacy V46 still scores; V47-/V47G- cannot bypass canonical replay.

### Task1: Clock freshness
Files: schedule.py; closed_loop.py normal-clock forwarding; tests/test_freeze_safety.py.
- [ ] Write real SQLite lock, late forecast, late precommit and stored-time counterexamples; run RED.
- [ ] Take fresh real time after write lock, before each freeze and before commit; reject backward clock. Keep explicit synthetic clock behavior.
- [ ] Verify real-clock closed_loop caller passes None to canonical scheduler, not entry observed time; run targetedGREEN.

### Task2: Prior evidence before new cards
Files: closed_loop.py and same new tests.
- [ ] Write dual/per-game old bad JSON, unknown paths, conflicting receipt, corrupt prior card and operational-only-ledger cases; run RED.
- [ ] Validate prior roster through original reentrant scorer before any new freeze. Keep original post-freeze validation as a conservative concurrent-change check. Treat absent dual tables as an empty dual roster, not invalid database bytes.
- [ ] Verify no new frozen cards on rejection; valid older rows/files remain; run focusedGREEN.

### Task3: Legacy namespace separation
Files: cli.py and same new tests.
- [ ] Observe legacy entry accepts canonical identities; test rejection and V46 scoring compatibility.
- [ ] Reject V47-/V47G- before opening scoring files, retain original V46 path.
- [ ] Full regression with exact failure reporting; commit only these repairs/spec/tests to same branch; exactSHA dualCI, independent scoped review, controlled current runtime activation and original tick.

Ruling: prior-roster reentrant validation may create valid original create-only score receipts; it must not add SQL forecasts. Its purpose is to prevent an unrelated failing new target from consuming immutable identity before old evidence is validated. This is not a new all-files transaction or an external trust verifier.

Final review fix: actual reader-blocked COMMIT reproduced after final time check. Add the reader-lock counterexample (RED:14 methods/1 failure), then replace BEGIN IMMEDIATE with BEGIN EXCLUSIVE (GREEN:14 methods). Absolute fsync completion and trusted predraw time remain NOT_VERIFIED. Repeat full regression for these final bytes; require exact new-head dual-platform CI before runtime activation. The original 13-method RED/GREEN and earlier full526 result remain preserved as earlier evidence.

Same-fix-pass extension: reproduce the per-game reader delay (15 methods/1 failure). Preserve recursive old-roster read access with IMMEDIATE preflight, ROLLBACK, then EXCLUSIVE and roster recheck before new-card checks. Independent reviewer confirmed this bounded lock ordering without running final bytes. Add a deterministic same-issue interleaving through real SQLite (16 methods/1 failure), then allow exact same-target reuse while rejecting other roster changes. The original snapshot equality and original card replay remain mandatory. Preserve all earlier results; final regression covers all538 deliverable files and expected529 tests.

