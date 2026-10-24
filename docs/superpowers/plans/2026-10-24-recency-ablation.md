# V4.7 recency and ablation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Actually execute the three authorized historical research directions in the existing lab.

**Architecture:** Extend existing lab with date-only input and separate preparation/frozen evaluation. Reuse core model and statistical arithmetic; no formal producer edits.

**Tech Stack:** Python3.11 standard library, existing unittest/CI.

**Spec:** docs/superpowers/specs/2026-10-24-recency-ablation-design.md

## Global Constraints
Preserve core/statistics/model_versions, NULL seed, formal family and past ledger. No new Harness/PR/main merge. Historical study always exploratory; UNKNOWN publication times stay unknown.

## Review Focus
Future suffix leakage; forged frozen manifest rehashed by caller; duplicate numeric issue aliases; selected model misrepresented as independent evidence; inconsistent denominator or missing reporting scopes.

### Task1: date-only locked recency/ablation experiment
Files: existing research/harness_v46/d2_challenger_lab.py; new tests/test_recency_ablation.py.
Interfaces: prepare_ablation_study(bundle) -> manifest; evaluate_ablation_study(bundle, manifest) -> full rows/statistics; ablation_rank(history,game,arm) -> ordered ranking.
- [ ] Write independent behavioral tests for required invariants in design, assert absent feature RED and save original log.
- [ ] Implement minimal extensions; do not edit existing function behavior or core.
- [ ] Run new tests then full unittest discovery; retain exact stdout/stderr and command.
- [ ] Freeze data/contract manifest to file, then separate evaluation; record all source hashes.

### Task2: adversarial review and real evidence
Files: docs/superpowers/reviews/2026-10-24-recency-ablation-independent-review.md; evidence summary documentation in same original research path.
- [ ] Fresh agent reviews implementation, denominator, exact arithmetic, split and raw data identity, reruns meaningful negative controls; findings get actual RED/GREEN fixes.
- [ ] Run full regression after final code; publish only existing PR branch using expected-parent compare-and-swap.
- [ ] Verify Ubuntu+Windows CI raw logs and exact checkout SHA, no invented CI outcome.
- [ ] Preserve per-draw historical outputs and metadata in user deliverable evidence archive, update Issue468 with exact claims and blockers.

Ruling: the explicit user request already specifies scope, execution method, constraints and acceptance; proceed through design/plan rather than asking the user to re-authorize the same work. No genuinely hidden historical test or future preregistration is claimed.
