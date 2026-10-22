# V4.7 /goal independent P0-A gate vs SHADOW-trace integration

## Scope and exact source identity

- This commit stacks on research integration branch commit `7d2b798bea442729efdc2c3c3d84f8139e1dccab`, PR #445, **not** main.
- Source P0-A change: Draft PR #438, commit `aa4217e20d5869bd315365bb1c22a9c1df4cecc8`.
- Preimage checks: the four affected files in PR #445 had the same blob SHA as the parent version from which PR #438 changed them. They can therefore be transplanted without overwriting another intervening change.
- Transplanted files: `convergence.py`, `schedule.py`, `tests/test_convergence.py`, `tests/test_schedule.py`.
- The prior #439 preserved HTTP raw-byte guard, #440 EWMA 120-draw contract, #441 ShrinkMix 120-draw contract, and #442 independent Pairwise mathematical oracle remain intact. This tranche does **not** transplant PR #438's DLT three-source collection change or unrelated workflow/policy code.

## P0-A execution / authority separation

The application previously wrote SYNC, VERIFY, AUTHORIZE, PREDICT, FREEZE, and WAIT into one workflow table even though official source verification, authorization, and a trusted external time seal were absent.

After this integration, the scheduler writes only a **BLOCKED** SYNC gate to `workflow_events`. It records the six research execution stages in a distinct `shadow_trace_events` table with `SHADOW_UNVERIFIED` evidence. No caller-provided `PASS` grants admission. The official gate remains fail-closed until an independent verifier with a separate trusted receipt contract is implemented.

`FREEZE` in a shadow trace means a complete local batch SHA was stored, **not** a verified pre-cutoff third-party seal.

## Exact-head tests

Run on two GitHub CI platforms for the integration SHA (not just source-branch tests):

```sh
python -m unittest discover -s research/harness_v46/tests -v
```

Adversarial regression cases must reject forged PASS and formal A, out-of-order / blocked-upstream VERIFY, FREEZE hash alteration, journal update/delete/REPLACE, and partial cross-game writes under injected SQLite failure; retries of identical records remain idempotent. Also rerun #445's raw-provenance and 120-window tests.

## Explicit non-claims and blockers

- Official SSQ/DLT 120+ independently matched historical source admission and per-target cutoff proof: BLOCKED; existing SSQ HTTP 403, DLT HTTP 567, DLT chronology anomalies remain.
- A documented *blocked* official gate is not an official verified result; no signed test1 authorization or source-publication-time proof.
- External RFC3161/independent witness pre-cutoff verification: NOT_RUN. Local SHA, SQLite and Git timestamps are not trusted timing.
- Independent official post-draw intake and the verified REPLAY–SCORE–AUDIT–REPORT–NEXT orchestration: NOT_RUN.
- Full real Windows physical P0 cold-boot / offline / 30-minute recovery: NOT_RUN.
- DLT 69/2880 negative-control root cause: UNRESOLVED.
- Historical exact confirmatory 12-hypothesis family and prospective paired D2 advantage: NOT_VERIFIED.
- No V4.5 formal eight-slot changes, no `main` write, no retroactive prediction, no purchase.

`ENGINEERING_PASS=NOT_YET`; `RESEARCH_VALID=NO`; `D2_EDGE_CONFIRMED=NO`; `formal_A=0`; `NO_EDGE`.
