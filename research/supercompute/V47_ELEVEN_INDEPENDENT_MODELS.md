# V4.7 / SSQ-DLT: Eleven separate executable model contracts

## Goal and decomposition

The requirement is **11 separate model implementations**, NOT five forecast families plus six unchecked helper flags. The public interface for *every* independent model is `fit(history, game, context)`, `predict(history, game, context)`, and `score(ticket, actual, game)`. Each has its own class, a nonempty fitted state, a legal candidate ticket, and inspection metadata. The fixed-order orchestration function is `research.supercompute.v47_registry.execute_eleven()`.

| # | Model class | Independent fit mechanism | Independent prediction output |
|---|---|---|---|
| 1 | HOT60Model | 60-observation counts | frequency candidate |
| 2 | EWMAModel | exponential half-life weights | EWMA candidate |
| 3 | ShrinkMixModel | pseudo-Bayesian shrink of frequency and decay | shrunken candidate |
| 4 | PairwiseD2Model | within-draw co-occurrence residuals | pair-adjusted D2 candidate |
| 5 | ChallengerModel | evolving parameter-genome population with selection, crossover and mutation | champion-genome candidate plus genealogy |
| 6 | StatisticsModel | counts, decay, shrinkage and pair residual fitting | independently ranked statistical candidate |
| 7 | ForecastSearchModel | six-model weighted marginal objective | separate bounded combinatorial search; 3 candidates |
| 8 | GeometryModel | spans, gaps, zone-state transitions | geometry-aware ranked candidate |
| 9 | SimulationModel | seeded sampling, Monte Carlo and strictly past-only backtest | sampling-derived candidate and retrospective records |
| 10 | PhysicsModel | 2D motion, pair/wall collisions, airflow (uncalibrated) | physics-toy candidate |
| 11 | ValidationModel | exact M1 legal/math tests, M2 fair-D2 binomial refutation, M3 Brier, past-only weighting | a **new 10-source ensemble candidate** plus alternates |

## Eleven smaller engineering prompts / acceptance tasks

1. `HOT60`: verify legal ball ranges, sample 60 recent historical draws, score occurrence counts, generate and record a candidate.
2. `EWMA`: weight each past draw by exponentially decaying half-life, normalize inclusion probabilities, generate a candidate.
3. `ShrinkMix`: combine hot and decay estimates with an explicit mathematical pseudo-prior, normalize, generate a candidate.
4. `Pairwise-D2`: calculate pair count minus fair-pair expectation normalized by estimated dispersion, rank D2-related combinations.
5. `Challenger`: keep parents, cross over genes, mutate bounded parameters, independently fit offspring on historical validation, prune, and retain full IDs/parents/objectives/genomes.
6. `Statistics`: make a separately callable fitted statistical feature model; expose normalized marginals, pair residuals, and its own generated candidate.
7. `ForecastSearch`: make a separately callable fitted search model; generate legal front/back combinations from six earlier fitted-model outputs, with top ranked alternatives.
8. `Geometry`: fit zone transitions and span/gap estimates on chronological history and rank its own candidate against the observed geometry objective.
9. `ProbabilitySimulation`: run a controlled seeded uniform Monte Carlo and a chronological backtest, then generate an independent simulation-based candidate. **This is not an extra random-baseline selector**.
10. `Physics`: simulate two-dimensional collisions, momentum exchange and airflow; output a mechanical-toy candidate and `calibrated_to_draw_machine=false`.
11. `M1/M2/M3 Validation`: validate all ten earlier model tickets; derive fair D2 probability analytically for exact binomial hypothesis checks; calculate historical Brier scores; allocate nonzero influence to *all ten* model candidates; search a separate 11th prediction.

## Cross-run genetic learning

`cell_division()` in `v47_integrated.py` records parent genomes, mutation/crossover offspring, each evaluated fitness and survivors, including the final evaluated generation. The `ChallengerModel` fits this population and accepts a prior persisted champion. Each scheduled run loads the previous immutable report's champion from the GitHub evidence branch. **No new data means no new predictive evidence**, even if genomes mutate.

## Required execution and evidence

From a Windows repository root (Python 3.11+), with real target identifiers and suitable input snapshots:

    python -m unittest discover -s research/supercompute/tests -p 'test_v47_registry.py' -v
    python -m research.supercompute.v47_forecast generate --game both --ssq-target EXPLICIT_SSQ_NEXT --dlt-target EXPLICIT_DLT_NEXT --generations 2 --validation 6 --holdout 3 --mc-trials 300 --physics-steps 30 --output research-output/unified-11.json --freeze-dir research-output/frozen

Output: `games.ssq.independent_11` and `games.dlt.independent_11` each contain 11 separate `models` with `fit` and `prediction`; `proposed_tickets` contains **11 model-labelled rows per game (22 total)**, ordered by model number; the eleventh row is the Model 11 ten-source ensemble. Each model also exposes a callable `score()` method for post-draw evaluation. Research-only create-once SHA256 freezing and tamper refusal are inherited from `v47_integrated.freeze_result()`.

Acceptance asserts: eleven unique concrete classes; eleven unique fit and predict implementations; eleven legal predictions per game; 6–11 independent outputs; real mutation/crossover genealogy; past-only backtesting; M1, M2, M3; deterministic repeated runs; strict separation of prospective data; score/freeze integrity. A later schedule result is only counted by actual GitHub `event=schedule`, not PR CI.

## Evidence limits

This is a fitted, evolutionary research predictor, not self-training on future results without a source. Checked-in historical snapshots can be stale. Model 10 is **not** a calibrated physical lottery machine. The model output remains `formal_prediction=false`, `edge=NO_EDGE`. These flags do not change whether the code runs; they prevent unverified statistical or physical claims. No evidence is overwritten or retroactively changed.

## Required 22-row output contract

Every normal combined SSQ/DLT CLI run emits exactly **11 rows for SSQ and 11 rows for DLT**. The rows are labelled by `model_number` and `model_name` and are copies of their corresponding independent model's own `prediction.ticket`, with no replacement by a three-ticket merged shortlist. The research freeze contains all 11 rows for each game; scoring returns one result per row. Duplicate ball combinations from independently computed models are retained **as separate attributed model rows** and are not silently modified or counted as a new unique combination. An evidence gate rejects reports with other counts or mismatched sources. Past 3-row immutable reports remain verifiable but cannot satisfy the new 22-row contract.

## November 2026 hardening: actual M2/M3 for all eleven

The live `execute_eleven()` engine now evaluates **every one of the eleven named models** in chronological walk-forward historical folds. Each fold fits on strictly preceding draws. M2 uses the mathematical fair-D2 null with exact binomial tail, reports the full trial count and is exploratory with no multiple-testing adjustment. M3 now **fits a shrinkage-to-fair reliability calibration multiplier** using earlier test folds only, then independently scores the last holdout fold. Both raw and calibrated Brier/ECE and sample counts are persisted. Physics model 10 uses explicitly labeled *uncalibrated proxy probabilities*, NOT calibrated probabilities from a real machine. Calibration fitted from 1–2 older folds and evaluated on just one fold is statistically weak; reports should never describe that as validated predictive power.

The pair-residual model fits a pair-conditioned marginal vector, the statistical model uses separate priors/mixing/conditioned residuals, and the geometry model adjusts per-number weights by observed posterior/fair zone occupancy before ranking. Shared source data and shared utility code do **not** imply statistical independence. Exact match and distinct-state tests are executable in `test_v47_registry.py`.

The evolution engine accepts an explicit previously frozen champion and now records the **inherited parent genome ID and `inherited_prior_run` origin** in the initial generation. This verifies code-level transfer across runs; it does not prove that the scheduled GitHub evidence ledger has triggered twice or that future fresh outcomes have been ingested.

The 22-row report output and new scheduled receipts fail closed if fewer than 11 M2 and 11 M3 audit records exist for either game. Historical immutable three-row/five-audit receipts remain readable in legacy mode. A source-date or physics-calibration gate is not silently disabled by successful unit tests.
