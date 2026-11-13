# SSQ + DLT V4.7: unified eleven-stage prediction research

## What changed

This module is a **single entrypoint** that runs and records all eleven requested capabilities before ranking candidates. There are precisely five selectable model families:

1. HOT60; 2. EWMA; 3. ShrinkMix; 4. Pairwise-D2; 5. Challenger;
6. frequencies/decay/shrinkage/pair residuals; 7. ranking/combinations/generation/create-only freeze/scoring;
8. geometry/spacing/span/zone transitions; 9. random sampling/Monte Carlo/chronological holdout;
10. 2D toy ball collisions/airflow/mechanical motion; 11. M1 math, M2 paired NULL refutation, M3 marginal calibration.

`v47_integrated.run_all()` emits the 11 evidence branches, independent family tickets, gene lineage and 3 combined candidate tickets. `v47_forecast.py` exposes the full chain and research-only freeze/score.

## Controlled cell-division algorithm

`cell_division()` begins with 3 seeded parameter genomes; optionally includes the champion from a prior run. Each generation ranks genomes on validation folds using *only earlier historical draws*, keeps the best 2, makes up to 4 children through gene crossover and bounded mutation, deduplicates genome IDs, and logs parents, scores and survivor IDs. The final champion feeds the ensemble. Repeated runs on unchanged historical data do not add new evidence.

Five family marginal inclusion estimates are combined with **fixed predeclared weights** HOT60 .18 / EWMA .18 / ShrinkMix .18 / Pairwise-D2 .18 / Challenger .28. Candidate combinations are ranked using marginal log-odds, pair residuals, geometry transition/span, and a small (0.01) explicitly uncalibrated physics-toy contribution. This is an experiment, not a measured physics lottery model.

Validation uses a held-out chronological tail; the **holdout champion is trained without that tail**, while the next research candidate can use the entire historical source because the next target remains unseen. M2 tests D2 against the exact combinatorial fair-draw probability rather than generating a sixth candidate. The system reports `NO_EDGE`, and M2 p-values are exploratory (not multiplicity corrected).

## Run on Windows PowerShell, from repository root (Python 3.11+)

    python -m unittest discover -s research/supercompute/tests -p 'test_v47_integrated.py' -v

    python -m research.supercompute.v47_forecast generate --game both --ssq-target USER_VERIFIED_NEXT_SSQ_ISSUE --dlt-target USER_VERIFIED_NEXT_DLT_ISSUE --seed 2026 --generations 2 --validation 6 --holdout 3 --mc-trials 300 --physics-steps 30 --output research-output/11-unified-run.json --freeze-dir research-output/frozen

Data defaults to checked-in SSQ/SSQ/resources/official_seed.json and DLT/src/resources/official_seed.json. **These are historical, not live issuer-verified. Never label the resulting tickets as upcoming real issues until official issue/source data has actually been checked.** Supply verified, time-ordered JSON snapshots via `--ssq-data` and `--dlt-data` for newer input.

To carry a champion between runs, use `--previous research-output/11-unified-run.json` (same game(s), verified provenance). Do not pass output to itself; use a new output path each time. Cross-run inherited parameters are logged in `evolution.parent_from_prior_run`.

To score after the draw (with independently verified actual values), use one frozen file and SHA256 printed by the generation command:

    python -m research.supercompute.v47_forecast score --frozen research-output/frozen/ssq-USER_VERIFIED_NEXT_SSQ_ISSUE-v47-unified.json --sha256 SHA256_FROM_GENERATE --actual issuer-confirmed-actual.json

Scoring verifies frozen hash and target issue, then reports front/back/D2/full hits; it does **not** itself verify that the user-supplied outcome was issuer-confirmed.

## End-to-end acceptance

- All eleven `requirement_modules` must be present, with nonempty meaningful outputs.
- Both games must generate legal tickets; M1, M2 and M3 must be populated; complete parent-child genealogy must appear.
- Freeze is `xb` create-only, SHA256 rechecked before score. Historical future leakage test changes test-tail outcomes and asserts earlier training unchanged.
- No model can be declared predictive from simulated physical variables without calibrated equipment observations; `source_status`, `formal_prediction=false`, and `edge=NO_EDGE` remain explicit.
- Existing official V4.7 selectors/P0 ledger remain untouched by this integration. Deployment and schedule are separate from proof of prospective predictive edge.
