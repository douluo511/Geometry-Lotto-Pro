# Local V4.7 Control Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Tasks use checkbox steps with actual RED/GREEN records.

**Goal:** deliver an executable local view of the existing SSQ/DLT freeze/score loop and fix the reproduced SSQ source-launch failure.
**Architecture:** same Python closed_loop and original Windows installer; a thin native Win32 UI with read-only status and retained subprocess receipts, no new scheduler or predictor.
**Tech Stack:** Python3.11, stdlib/Win32 ctypes, existing requests2.34.2, original PowerShell scripts.
**Spec:** docs/superpowers/specs/2026-10-25-local-control-design.md

## Global Constraints
- SoleIssue468/DraftPR467; base5c9f351b7380340be35fd0416a2eb660cd7a13ca; no main merge/newHarness/seed or formal-model/family change/purchase.
- Same ledger/workspace and explicit future inputs only; no backfill; formal_A0/NO_EDGE and separate evidence tiers.
- No system policy change, Force overwrite, temporary-tool-account task install or claim of physical/owner acceptance from CI.
- Work in local_deployment edit snapshot. Original dirty Git checkout and host_forward immutable execution snapshot stay unchanged. Native worktree unavailable and Git HTTPS transports failed; connected GitHub API commits use expected-head lease.

## Review Focus
- Fresh unrelated/spaced cwd and missing PYTHONPATH must actually import SSQ source package.
- Empty/tampered/unfinished read-only journal must not create DB, invent denominators or mix ticks.
- Null/empty/old-mode snapshot fields must fail before subprocess or writes.
- CLI failure/timeout and non-owner install attempts must retain diagnostic bytes without repeating or claiming registration.
- Reused widgets must never run old predictors, updater, legacy timer or legacy acceptance writer; Linux import and global glp modules remain safe.

### Task1: source-launch repair
Files: SSQ/launcher.py; research/harness_v46/tests/test_source_launcher.py.
- [ ] Write subprocess test with PYTHONPATH removed, spaced unrelated cwd, --check corrupt-repair and result file. Assert actual exit/result, not source-string matching.
- [ ] Run against base and save intended ModuleNotFoundError/exit assertion RED. Pause before implementation for test-only commit.
- [ ] Add minimal own-directory package bootstrap only in non-frozen source execution.
- [ ] Run focused test and relevant SSQ suite; preserve RED/GREEN raw logs.
- [ ] Independent task review checks packaged paths and unchanged scientific code.

### Task2: local controller and native window
Files: research/harness_v46/desktop.py; tests/test_desktop.py.
Interfaces: DesktopController(config_file,reports=(),owner_sid=None), read_status/run_tick/install_task/research_status(progress=None), build_window(controller), main(argv=None); match spec exactly.
- [ ] Write functional tests for read-only actual ledger/absent DB, tamper and unfinished state, strict config/explicit per-game CLI forwarding, retained external-process failure, refused sandbox owner install, lazy import and inert Windows widget callback smoke.
- [ ] Run tests with module absent; assert feature absence as a test failure (not collection ImportError). Save RED and pause for parent test-only commit.
- [ ] Implement minimal controller and native UI; no extra timer, source/forecast family or trust approval.
- [ ] Run focused tests and actual safe --status-json/GUI-self-test; review implicit inputs in Review Focus.
- [ ] Independent task review; repair findings and rerun focused then full suites.

### Task3: two new-row diagnostics and release
Files: new outputs/work evidence only; no old study/ledger edits.
- [ ] Verify old frozen manifest/model/data SHA and unchanged prefixes; reconstruct only two new known historical targets with selected arm and fixed NULL.
- [ ] Save explicit POST_RESULT_RECONSTRUCTION_EXPLORATORY D1-D5/D2 paired rows and limitations; formal denominator remains NOT_VERIFIED.
- [ ] Commit tests-only RED, preserve exact-SHA CI failures; then minimal GREEN to same branch via API with lease, preserving original main.
- [ ] Run full V4.7 regression, relevant legacy suites, exact-SHA Ubuntu/Windows CI and fresh broad independent review.
- [ ] Hash-verify full final source snapshot, prepare original bot config and local one-click entry; point current_runtime only after identity/review/CI verified.
- [ ] Actual local UI/status smoke and report remaining owner/source/future gates. Update soleIssue468 and attach existingPR. No complete/edge claim without required evidence.


## Builder-check rulings
- R1: use original configured interpreter/timeout(default45,finite(0,120])/log-parent validation, not GUI process defaults.
- R2: use one deployment-specific config COPY with new verified repository_root for desktop and original installer.
- R3: require actual token SID match to known durable profile-owner SID before installation; missing/malformed/mismatch refuses.
- R4: block GUI close while operation busy until its receipt is durable;100ms GUI-event drain timer is allowed, no extra forecasting timer.
