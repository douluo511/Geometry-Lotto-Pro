# Independent-game statistics Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Connect replay-verified complete single-game local scores to existing CP95/exact/paired/Holm arithmetic.
**Architecture:** Add one returned report at the end of advance_game_workspace; unchanged arithmetic accepts one game plus twelve named hypotheses.
**Tech Stack:** Original Python3.11 unittest/SQLite.
**Spec:** docs/superpowers/specs/2026-10-26-independent-game-statistics.md

## Global Constraints
No model/NULL/seed/family/formal admission changes; original twelve mapping exact. Existing score receipt files unchanged. No pending issue excluded to get a complete report. Report scope is roster at read, not official schedule/current global state.

## Review Focus
1. Another game has no rows in report: label placeholder, not true zero denominator.
2. One frozen issue pending: no statistical summary of the convenient subset.
3. Retry: DB and saved receipt bytes unchanged.
4. Known hot60 win/NULL loss: exact delta1, CP95 lower.025, paired p.5, Holm1 for one synthetic draw.
5. Multiple original issues: full included denominator, no per-model sample selection.

### Task1
Files: closed_loop.py plus tests/test_independent_game_statistics.py.
Consumes original replayed scores; produces returned local_d2_statistics only.
- [ ] Write real frozen SQLite fixtures with outcomes chosen to hit a frozen hot60 pair and exclude one frozen NULL element; assert literal arithmetic and scope.
- [ ] Run new tests RED against unchanged closed_loop.
- [ ] Construct rows and fixed twelve mapping only after pending is empty; call original evaluator and annotate scope/placeholders/delta.
- [ ] Run focused and full regression, retain exact logs and immutable source/ledger hashes.
- [ ] Independent review; same-branch commit and exact-SHA dual-platform CI before runtime promotion.

Ruling: use existing isolated work/local_deployment, already baseline-verified; this return-only diagnostic bridge is within delegated closure repairs. Official trial schedule, sample endpoint/stopping policy and gate verifier remain NOT_VERIFIED, not invented.

