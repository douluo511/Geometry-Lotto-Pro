# V4.7 SSQ/DLT Eleven-Component Research Lab

Isolated Python 3.11+ research module. Five candidate families only; historical immutable receipts are preserved.

## Eleven requirements and functions

| Requirement | Implementation |
| --- | --- |
| 1 HOT60 | inclusion_probabilities(..., model='HOT60') |
| 2 EWMA | inclusion_probabilities(..., model='EWMA') |
| 3 ShrinkMix | shrink and inclusion_probabilities |
| 4 Pairwise-D2 | pair_residuals and candidates |
| 5 Challenger | evolve: parent, mutate, validate, compete |
| 6 Statistical frequency, decay, shrinkage, pairs | weighted_counts, shrink, pair_residuals |
| 7 Sorting, search, prediction, freeze, score | candidates, freeze, score_frozen |
| 8 Span, gaps, states, transitions | geometry, geometry_state, geometry_transition |
| 9 Random sampling, Monte Carlo, backtests | random_ticket, monte_carlo, backtest |
| 10 Ball collisions, airflow, mechanics | physics_toy (illustrative and uncalibrated) |
| 11 M1 mathematical, M2 refutation, M3 calibration | m1_math, m2_refutation, m3_calibration |

The five named model families are candidate selectors; the remaining numbered requirements are system capabilities and safeguards. Per-ball inclusion marginals are not full-ticket probabilities.

## Windows PowerShell commands from repository root

    python -m unittest discover -s research/supercompute/tests -p 'test_v47_models.py' -v
    python -m research.supercompute.v47_cli run --game both --periods 30 --trials 10000 --seed 2026 --output research-output/v47-lab-001.json

Default historical paths: SSQ/SSQ/resources/official_seed.json and DLT/src/resources/official_seed.json. These are repository snapshots, NOT live official issuer verification. The JSON output uses create-only mode and will refuse to overwrite an earlier report.

To freeze a research candidate for an explicitly known target issue:

    python -m research.supercompute.v47_cli freeze --game ssq --data SSQ/SSQ/resources/official_seed.json --model Challenger --target-issue REPLACE_WITH_TARGET --output research-output/frozen-ssq.json

Record the printed SHA256 and supply an independently verified outcome JSON for the optional scoring operation:

    python -m research.supercompute.v47_cli score --receipt research-output/frozen-ssq.json --sha256 PRINTED_SHA256 --actual actual.json

Scoring status remains UNVERIFIED_RESULT because input JSON has no issuer-source verification. The local UTC timestamp and SHA256 do not independently establish a trusted pre-draw seal.

## Validation and limits

- M1 validates legal tickets, exact fair game space and D2 chance, and mass of per-ball marginal inclusion probabilities.
- M2 compares the observed D2 hits to the exact mathematical fair-draw probability using a one-sided binomial tail. No extra candidate model is created. No multiple-comparison correction is claimed.
- M3 reports per-ball Brier and grouped empirical calibration; sparse bins and past data cannot establish prospective edge.
- Challenger chooses mutations on a strictly earlier training-prefix validation tail before the final holdout; repeated tuning may overfit the validation tail.
- Geometry and uncalibrated 2D physical motion are hypothesis-generating demonstrators, not validated physical forecasting mechanisms.
- The system reports NO_EDGE and formal_prediction false. The five model families are HOT60, EWMA, ShrinkMix, Pairwise-D2 and Challenger. Neither a trusted pre-draw timestamp nor Windows restart resilience is established.

Live P0/P1 validation requires actual scheduled triggers and persisted recoveries, authoritative draw-source checks, independent prediction sealing, and scored prospective outcomes under a preregistered mathematical null hypothesis.
