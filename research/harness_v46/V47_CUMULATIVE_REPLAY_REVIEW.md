# V4.7 /goal: Cumulative SSQ/DLT D2 scoring over frozen SHADOW runs

Pinned base: Draft PR #449 @ `0cb5c28e3483a6e573a28b51691c1570a634f673`.
Scope: three additive research files only, **not main**. Preserve the eight V4.5 formal slots, all historical freezes, all existing model formulas, fixed NULL seed and unregistered challenger status.

## Gap audited
The #449 `prospective_cycle.py` provides *one* verified-identity local freeze and a paired SSQ/DLT `score` for caller-provided results but not a strict historical, per-model cumulative performance ledger. This patch adds `cumulative_shadow.py`, a standalone read-only calculator that consumes only exact frozen RUN_IDs from real local V4.7 research databases. It calls #449's `frozen_forecast_report()` and `evaluate_after_draw()` for each row. The latter recomputes scores from persisted predictions; no caller can submit winners, alternate D2 or choose a single preferred model.

## Outputs
Each game and each of six registered model arms: numerator/denominator D2 successes, observed hit rate, descriptive 95% binomial interval, theoretical fair D2 baseline, and same-draw fixed Random NULL paired wins, losses and hit-rate difference. Each observation retains target issue, batch digest, caller-outcome digest, D2 bits for all six models. Sorting by issue is deterministic.

Input is JSON list of records containing `database`, `run_id`, `results` (both games with exactly `lottery`, `issue`, `front`, `back`, `drawn_at`). Refuses repeated runs, repeated game/issue across distinct databases, partial outcomes, altered stored prediction hashes, fake formal flags, impossible claimed pre-draw draw-times, or mixed model/version/parameter SHA identities. Ledger is always read-only. Claims `drawn_at` and local report hash are NOT trusted.

Reproduce from exact HEAD:
```sh
python -m unittest discover -s research/harness_v46/tests -v
python -m research.harness_v46.cumulative_shadow --cycles-json local-unverified-cycles.json
```
An example file would contain paths to **real existing** locally frozen run ledgers and externally supplied outcomes. This PR deliberately does NOT fabricate sample historical predictions or issue a current prediction.

## Remaining blockers
G00/G01: official target/cutoff and independently witnessed raw official historical histories: BLOCKED. Official postdraw result fetch/parser and independent origin/time authenticity: NOT IMPLEMENTED. External RFC3161 or independent witness pre-cutoff proof: NOT_VERIFIED. Actual Windows cold-boot/offline/30-minute P0: NOT_RUN. DLT 69/2880 root cause UNRESOLVED. Exact history of 12 preregistered hypotheses: NOT AUTHENTICATED. Prospective D2 advantage: NOT DEMONSTRATED.

This tool reports **SHADOW_DESCRIPTIVE_ONLY**, `formal_A=0`, `NO_EDGE`, even for arbitrarily high illustrative hit counts. All six models are included, no cherry-picked winner, and descriptive rates do not imply a future edge.

`ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NO; D2_EDGE_CONFIRMED=NO`.
