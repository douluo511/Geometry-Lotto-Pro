# DLT real background continuity implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Replace the existing false1800-second acceptance with observed two-cycle native continuity.
**Architecture:** Preserve the existing worker and PowerShell executor; add bound cycle telemetry, an independently observed process interval and a pure evidence verifier consumed by the existing final gate.
**Tech Stack:** Python3.11 stdlib, existing PowerShell/Windows process APIs and GitHub Actions.
**Spec:** docs/superpowers/specs/2026-10-27-background-continuity.md

## Global constraints
Original PR467/Issue468 only; preserve all old/source/runtime/evidence. Operational intake timeout120 unchanged; native acceptance timeout3600 is a separate existing test budget. No models/NULL/seeds/family/stopping changes, no fake or backfilled prediction, no task/policy/elevation/reboot. Real continuity minimum1800, interval1800, two successful cycles; no accelerated production acceptance mode. Existing job cap120min and all other release gates stay. All local synthetic claims remain limited.

## Review focus
- Early waking clock, malformed/nonfinite/regressing offsets and1799.999 boundary must not pass.
- PyInstaller bootloader/payload PID differences must be validated by fresh lineage; PID reuse or replacement fails.
- Replayed/old-v1/wrong nonce/SHA/run/attempt/hash evidence must fail even when booleans say PASS.
- A failed first cycle followed by success must remain failed; unchanged data and immutable Freeze are allowed across two fresh updates.
- Timeout/crash/cleanup must retain actual failure evidence and affect only this invocation's owned processes; native CI must actually wait.

### Task1: Worker and evidence acceptance boundary
**Files:** Modify DLT/src/glp/background.py; DLT/src/main.py; DLT/scripts/background_acceptance.ps1; .github/workflows/dlt-windows-build-acceptance.yml. Create DLT/scripts/verify_background_acceptance.py and focused tests under DLT/tests. Retain existing compatibility tests without watering down assertions.
**Interfaces:** Worker/launcher optional launch-session/acceptance-nonce fields flow through CLI to status/cycle records with old callers unchanged. Driver creates expected request (session/nonce/SHA/run/attempt/EXE identity) BEFORE launch as a create-only sibling of the fixed EvidencePath. Pure verifier consumes v2 report plus that separately supplied expected request and externally supplied exact SHA/run/attempt/EXE identity, returns structured acceptance errors and nonzero on invalid evidence. Driver emits v2/failure records with external process samples; workflow supplies expected identities separately and calls the same pure validator rather than trusting flags. Never derive expected session/nonce from the report under test.
- [ ] Write literal behavioral tests first: existing worker early-wake/two-cycle/retained first failure; verifier CLI valid and adversarial reports. Run and preserve actual failing assertions/exit streams before production edits; explain each realistic mutation caught.
- [ ] Implement only the bound cycle telemetry/deadline wait and CLI forwarding. Keep fresh service.update and immutable Freeze behavior. Run worker/compatibility tests.
- [ ] Implement pure schema/timing/sequence/provenance verifier and original driver process observation, cleanup and durable failure report. Test replay, boundaries, malformed data and legitimate native PID separation; no fake success from an absent tool or policy denial.
- [ ] Wire the original workflow to v2 validation and real interval1800/two-cycle invocation; preserve all other final predicates and120min job cap. Syntax-check native scripts and run focused tests.
- [ ] Freeze final candidate file hashes; independent review finds counterexamples. Each Important/Critical fix gets its own RED before minimal GREEN; preserve failed attempts.
- [ ] Run complete existing regression once final code stabilizes; classify known local policy failures accurately. Commit exact files to the existing branch with expected-HEAD compare-and-swap; no new PR or merge.
- [ ] Verify exact-SHA Ubuntu/Windows CI and actual native step measured >=1800 with two live cycles, preserving final release failure if independent-repo/updater remains blocked. Wait on the same live job; no restart on observation timeout.
- [ ] Independent delivered-byte/CI review, then source/config promotion only if relevant gates justify it; retain old runtime and actual root operational attempts. Update sole Issue468 with public code/CI facts only; detailed internal evidence stays local.

## Self-review
All five review classes are owned by Task1 tests/actual native run; neither unit simulations nor a renamed smoke fulfill real duration. Runtime/source and research boundaries are unchanged. Larger source-date cache design is separate and not bundled.

