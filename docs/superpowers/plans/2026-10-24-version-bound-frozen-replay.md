# Version-bound Frozen Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Safely replay existing frozen cards after a core source upgrade.
**Architecture:** Full-hash trusted package artifacts, old-core validation and scoring, no ledger migration.
**Tech Stack:** Python 3.11 standard library, SQLite, existing unittest/Actions workflow.
**Spec:** ../specs/2026-10-24-version-bound-frozen-replay-design.md

## Global Constraints
Only Issue #468 / existing Draft PR #467. No main merge, new Harness/PR, model,
parameter, fixed NULL or historical freeze edits. Formal A and scientific edge
stay separate and blocked. Source/host/TSA investigations are independent evidence.

## Review Focus
1. Source hashes are not normalized to hide CRLF/LF identity differences.
2. No executable source may be selected by a caller path or DB contents.
3. Archived dependency import must not silently use the upgraded current core.
4. Scores and receipt retries use original pinned rules and immutable cards.
5. Missing, tampered, mixed or unknown historical source must fail closed.

### Task 1: Native cross-version regression, then minimal repair
**Files:** new `research/harness_v46/tests/test_versioned_frozen_replay.py`;
new `research/harness_v46/frozen_replay.py` and trusted `model_versions/*.source`;
modify `closed_loop.py`, `convergence.py`, `.gitattributes`.
**Interfaces:** `resolve_core(source_sha256) -> module`,
`validate_prediction(prediction, snapshot)`, `score_prediction(prediction, result)`.

- [ ] Write native subprocess A→B replay and failure-boundary tests first.
- [ ] Run targeted unittest; preserve expected RED and test-only GitHub commit.
- [ ] Archive exact baseline core LF/CRLF and observed validator; verify fixed full hashes before isolated loading.
- [ ] Resolve frozen six-arm source before checking old run identity; retain full deterministic card comparison.
- [ ] Route legacy validation and both scorers through pinned core; do not modify core.py.
- [ ] Run targeted GREEN and complete `python -m unittest discover -s research/harness_v46/tests -v`.
- [ ] Independently review implementation and adversarial limits; address concrete findings with RED→GREEN.
- [ ] Fast-forward only the existing PR branch using an expected-SHA lease; inspect Windows/Ubuntu exact-HEAD logs.

### Task 2: Evidence and acceptance record
- [ ] Record refreshed dependency SHAs, raw official observations and conflicts, TSA/host permissions and limits.
- [ ] Publish falsifiable A checklist without inventing or replacing a missing numerical rubric.
- [ ] Record commits, CI raw logs, review classification, prospective denominator NOT_VERIFIED and remaining gates in Issue #468.
