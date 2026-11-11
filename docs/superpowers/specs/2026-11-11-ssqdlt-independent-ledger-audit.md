# SSQ＋DLT Research Ledger P0/P2 read-only audit — design (2026-11-11)

## Scope and why this exists

Real deployed `main/.github/workflows/ssqdlt-research-loop.yml` ran on `push` twice (43069944964 and 43071336351), and appended research-only evidence to `ssqdlt-research-ledger-v1`. Both contained one SSQ and one DLT forecast target with zero completed prospective scores. Prior local replay did **not** independently check GitHub Actions event authenticity, full Git object append-only history, or each individual forecast's own hash.

This work adds one **read-only verifier**, NOT a fourth Harness, new number selector, ticket purchase, official history override, or merge of draft V4.7. Independent formal V4.7/Random NULL remains frozen. The research data itself never implies improved odds.

## Independent failure gates

1. Fully cloned original ledger must have canonical JSON with unique keys, finite numbers, safe paths, two-game legal tickets and a single immutable issue per game; a modern per-issue forecast hash must equal its canonical body (excluding its hash field). Legacy original combined receipt predates this per-issue canonical format: preserve it unchanged and verify only its format, original Git add history, and external archived run reference; **do not** claim its internal hash can be recomputed without original full receipt bytes.
2. All saved raw HTTP bytes must exactly match stored base64 length, SHA256, allowed provenance URL/source path. This is data-custody, not authenticated public-source truth.
3. All saved score files must reference a unique stored forecast, stay complete, never claim formal A, and be recomputed independently by the existing **pinned** research scorer on the original immutable input files. Summary n = count of every score per game; pending forecasts must not enter denominator.
4. `git log` of all `research/{forecasts,scores,raw,ticks}` must show **exactly one add** for each currently tracked JSON receipt and no replacement, deletion, rename, or rewriting in full history. Reject shallow history, dirty checkout, untracked changes and file-path attacks. An authorized repo admin can rewrite Git refs; only an external independent timestamp/signature may address that threat.
5. GitHub Actions REST must independently corroborate every persisted tick: exact run ID/attempt, repository, `workflow_id=414968846`, actual event `schedule/push/workflow_dispatch`, `main` source branch, source SHA and terminal `success`, and exact GitHub run URL. Unavailable API, incomplete runs, failed runs, mismatched event/sha must not be PASS. Two distinct **actual successful schedule** runs are needed for the P0 scheduler gate. Pushes never count.
6. Independently re-check current remote branch HEAD with `git ls-remote` after checkout: cold retrieval from GitHub is not simulated local state.
7. Keep both acceptance labels separate: `LEDGER_INTEGRITY` can PASS while `SCHEDULE_2_REAL_TRIGGERS` remains UNVERIFIED. Always `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`, `formal_A=0`, `NO_EDGE` until the separate official V4.7 chain has truly passed.

## Implementation and testing

- `research/ssqdlt_research_ledger_audit.py` standard-library-only, offline pure-core and optional GitHub REST audit.
- `tests/test_ssqdlt_research_ledger_audit.py` adversarial future/past/JSON/commit/API tests.
- `.github/workflows/ssqdlt-research-ledger-independent-audit.yml`: on PR or completed research-loop workflow, independent fresh remote fetch, full history, pinned existing scorer and archive, read-only permissions; Ubuntu and Windows offline tests.
- `docs/superpowers/plans/2026-11-11-ssqdlt-ledger-independent-audit.md` details actual RED→GREEN CI links.

## Not accomplished by this PR

No actual GitHub `schedule` trigger or physical Windows cold boot, no officially authenticated future issue/cutoff, no independent RFC3161 accepted TSA, no complete formal six-arm score roster, no independent prospective edge. Stay Draft until independent reviewer signs off. The natural user-facing acceptance: successful read-only audit with exact Actions API events, original ledger SHA and 0-or-more real scored draws.