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
- [x] Write subprocess test with PYTHONPATH removed, spaced unrelated cwd, --check corrupt-repair and result file. Assert actual exit/result, not source-string matching.
- [x] Run against base and save intended ModuleNotFoundError/exit assertion RED. Pause before implementation for test-only commit.
- [x] Add minimal own-directory package bootstrap only in non-frozen source execution.
- [x] Run focused test and relevant SSQ suite; preserve RED/GREEN raw logs.
- [x] Independent task review checks packaged paths and unchanged scientific code.

### Task2: local controller and native window
Files: research/harness_v46/desktop.py; tests/test_desktop.py.
Interfaces: DesktopController(config_file,reports=(),owner_sid=None), read_status/run_tick/install_task/research_status(progress=None), build_window(controller), main(argv=None); match spec exactly.
- [x] Write functional tests for read-only actual ledger/absent DB, tamper and unfinished state, strict config/explicit per-game CLI forwarding, retained external-process failure, refused sandbox owner install, lazy import and inert Windows widget callback smoke.
- [x] Run tests with module absent; assert feature absence as a test failure (not collection ImportError). Save RED and pause for parent test-only commit.
- [x] Implement minimal controller and native UI; no extra timer, source/forecast family or trust approval.
- [x] Run focused tests and actual safe --status-json/GUI-self-test; review implicit inputs in Review Focus.
- [x] Independent task review; repair findings and rerun focused then full suites.

### Task3: two new-row diagnostics and release
Files: new outputs/work evidence only; no old study/ledger edits.
- [x] Verify old frozen manifest/model/data SHA and unchanged prefixes; reconstruct only two new known historical targets with selected arm and fixed NULL.
- [x] Save explicit POST_RESULT_RECONSTRUCTION_EXPLORATORY D1-D5/D2 paired rows and limitations; formal denominator remains NOT_VERIFIED.
- [ ] Commit tests-only RED, preserve exact-SHA CI failures; then minimal GREEN to same branch via API with lease, preserving original main.
- [ ] Run full V4.7 regression, relevant legacy suites, exact-SHA Ubuntu/Windows CI and fresh broad independent review.
- [ ] Hash-verify full final source snapshot, prepare original bot config and local one-click entry; point current_runtime only after identity/review/CI verified.
- [ ] Actual local UI/status smoke and report remaining owner/source/future gates. Update soleIssue468 and attach existingPR. No complete/edge claim without required evidence.


## Builder-check rulings
- R1: use original configured interpreter/timeout(default45,finite(0,120])/log-parent validation, not GUI process defaults.
- R2: use one deployment-specific config COPY with new verified repository_root for desktop and original installer.
- R3: require actual token SID match to known durable profile-owner SID before installation; missing/malformed/mismatch refuses.
- R4: block GUI close while operation busy until its receipt is durable;100ms GUI-event drain timer is allowed, no extra forecasting timer.

## Discovered regression and validation rulings
- Existing offline SSQ suite103 had1 date-sensitive ERROR: fixed2026-09-29 failover fixture had become stale. Freeze only that test sources-clock at2026-09-30; production stale/future gate and negative tests unchanged. Parent rerun103/OK.
- DLT14 offline tests inspected and rerun with isolated data/background disabled,14/OK.
- Extend existing exact-SHA two-OS workflow with independent-process SSQ103/DLT14 offline suites and SSQ/DLT path filters; no new workflow or network app tests.
- Strengthened desktop RED26cases includes wrong-schema validJSON and lexical/real symlink path rejection.

## Independent failure-boundary review and repair
- Independent reviewer reproduced three Important/P2 issues on desktop SHAa2f047366c29ad602089e5f1825e06687cda9acc38ab12e839e5398cd09dc84b: invisible pythonw startup error, prior busy-close hides receipt persistence failure, and mode=ro creates WAL sidecars. The28 focused passing tests did not cover these paths. No Critical defect in reviewed scope.
- Add meaningful real temp/native regressions first and preserve RED, then fix and independently recheck all three before deployment. Unsupported WAL must be refused without sidecar creation; do not ignore live WAL via immutable=1.
- Original complete-suite attempt was interrupted without final summary and is NOT_COMPLETED, not PASS. Preserve its log and run a new complete suite for the changed candidate.
- Earlier strongest review could not start because of usage limits; the fresh independent reviewer did run. External human acceptance remains NOT_VERIFIED.

## Verified repair checkpoint before release commit
- The three review findings were repaired with observed7-test/8-assertion RED then34 desktop tests/OK(skip1actualsymlink). Fresh independent increment review, including a nested native reviewer, found no unresolvedCritical/Important on source754a8ae878cfc18e5ae8ccc10dffd0ca01a0e7db6c14a9af18baf046c09ba451.
- Unchecked release steps below remain pending at this source checkpoint; exact final CI/deployment/host results will be recorded in the soleIssue468 and persistent local evidence. No source checkpoint claims external acceptance or formal forecast advantage.

## Completed local regression before release commit
- V4.7:490 tests/341.763s, FAILED7assertions across4existing Windows operational-snapshot test methods, skipped1actualsymlink. All7traces are the local script-policy refusal before invoke_closed_loop.ps1 loads, not a controller assertion. Do not suppress or relabel this suite PASS. Exact failure names/raw logs retained locally and published in Issue468.
- Offline SSQ103/OK(2.601s), DLT14/OK(.121s), separate processes. Candidate source hashes and actual ledger SHA unchanged before/after. Original interrupted run remains NOT_COMPLETED. No policy bypass/change introduced.
