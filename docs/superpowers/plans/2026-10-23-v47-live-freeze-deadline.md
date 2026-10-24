# V4.7 Live Freeze Deadline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Prevent a real per-game Bot tick from freezing late using stale entry time.
**Architecture:** Repair the original `closed_loop.advance_game_workspace` transaction.
Only local deadline enforcement changes; explicit synthetic clocks retain compatibility.
**Tech Stack:** Python 3.11, stdlib unittest/SQLite, existing GitHub Windows/Ubuntu CI.
**Spec:** `docs/superpowers/specs/2026-10-23-v47-live-freeze-deadline.md`.

## Global Constraints

Sole Issue468/PR467, no main changes/new Harness/parallel PR. Preserve all old
freezes, five candidates, fixed Random NULL, formal eight slots; formal_A=0/NO_EDGE.
No scheduler installation, automatic purchase or merge.

## Review Focus

- Lock or expensive model computation consumes the remaining presale window.
- Cutoff equality at either transaction boundary must roll back all rows.
- Stored time must describe the final checked boundary, not the original tick.
- Existing post-cutoff replay must remain read-only and preserve all six cards.
- Abrupt process exit must leave no partial rows; retry must freeze only six arms.

## Task 1: Pin and fix stale-clock admission

Files: `research/harness_v46/closed_loop.py` and
`research/harness_v46/tests/test_game_freeze_deadline.py`.
Interface: existing `advance_game_workspace(workspace, snapshot=None, game=None,
observed_at=None) -> dict`; unchanged.

- [ ] Add three clock-boundary tests with real six-model generation and SQLite.
- [ ] Run `python -m unittest research.harness_v46.tests.test_game_freeze_deadline -v`;
  retain RED log showing two missing rejections and one stale stored timestamp.
- [ ] Recheck live time after lock and before commit, persist final local time,
  roll back failed transaction. Retain explicit synthetic clock compatibility.
- [ ] Run targeted tests and entire `python -m unittest discover -s research/harness_v46/tests -v`.
- [ ] Independent reviewer audits complete branch and new change; fix important findings.
- [ ] Commit/publish only to the existing PR467 head branch through expected-SHA guard;
  verify exact-HEAD Ubuntu/Windows CI original logs and record all limits in Issue468.

## Task 2: Exercise abrupt exit and retry

File: same test module. Real subprocess terminates after its third transactional
card insertion; no mocks of predictions, SQLite or outputs. Parent observes
no published partial rows and a fresh process retry produces exactly six cards.

- [ ] Add real process-death recovery test; record whether existing transaction already passes.
- [ ] Verify new test and full regression on Windows and Ubuntu CI.
- [ ] Publish evidence with physical reboot explicitly NOT_VERIFIED.
