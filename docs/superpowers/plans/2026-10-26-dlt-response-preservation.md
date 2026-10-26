# DLT response preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Preserve each actually returned DLT source response before parser failure.
**Architecture:** Extend the existing intake guard; bind parser success manifests to captured observations without a second receipt. Original semantic validation remains strict.
**Tech Stack:** Python3.11, requests, unittest, existing SQLite/JSON intake.
**Spec:** docs/superpowers/specs/2026-10-26-dlt-response-preservation.md

## Global Constraints
Existing PR467/Issue468 only. Base84df; current529blob runtime immutable. No formal model, NULL seed, family, source quorum, deadline or admission changes. No past response backfill. Metadata is not full headers.

## Review Focus
1. Retry bodies identical: preserve separate observations.
2. First variant bad200 then success: retain bad bytes and keep existing semantic gate strict.
3. Later-page failure: preserve earlier and failed returned pages.
4. No response: no invented payload.
5. Parser manifest differs from observed bytes or final query URL: reject before claiming binding.

### Task1: Existing intake capture and manifest binding
Files: modify research/harness_v46/official_intake.py; add research/harness_v46/tests/test_dlt_response_capture.py.
Interfaces: _install_dlt_redirect_guard(game, failure_recorder) remains callable; _worker(game) retains its schema.
- [ ] Write network-boundary and original-worker tests covering the five review inputs and normal success without duplicate receipts.
- [ ] Run unittest new module; observe missing200 body assertions fail against unchanged84df.
- [ ] Record every actual response and validate successful manifest against captured observations, excluding timestamp/requested-hop differences from matching.
- [ ] Run new module plus existing official_intake/source semantic tests; retain stdout/stderr/exit/hash.
- [ ] Run full regression without policy bypass and report every failure.
- [ ] Independent scoped review, commit to same branch, exact new-head Ubuntu/WindowsCI. Promote only after evidence.

## Execution ruling
Reuse work/local_deployment, already isolated from original dirty checkout and verified against all529 baseline blobs. Git object changes go through the connected repository API with expected-parent compare-and-swap; do not create another Harness/PR. Evidence under work/raw_response_repair is retained because the user requires original RED/failure evidence. Current pointer is not moved during implementation.

