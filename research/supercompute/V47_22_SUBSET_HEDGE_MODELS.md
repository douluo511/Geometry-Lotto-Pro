# V4.7 22 true computation models / 44 dual-lottery research outputs

## Exact user contract

Eleven existing distinct original model classes are the positive arm M01+...M11+. Eleven additional negative/exclusion model classes with individually implemented `fit()` methods are the negative arm M01-...M11-. Each of the 22 has fit, predict and score functions; the branch identifiers are unique even when two algorithms legitimately produce identical balls. Execute separately for SSQ and DLT: **22 per lottery = 44 named predictions**.

## Subset and non-subset mathematical definition

Let B be the actual drawn front/red set. For each positive arm, A is its 2-number candidate inclusion pair from ticket `dan2`; its event is `A subset B`. For each negative arm, E is its independently computed 2-number `excluded_pair`; its event is `E not-subset B`, meaning at least one exclusion number is absent. The stronger `E disjoint B` is a separate event: not-subset is NOT equivalent to zero overlap.

The mathematically fair probabilities for a fixed pair are:

- `subset`: C(k,2) / C(N,2)
- `not_subset`: 1 - C(k,2) / C(N,2)
- `disjoint`: C(N-k,2) / C(N,2)

Here N is 33 and k is 6 for SSQ front, N is 35 and k is 5 for DLT front. The event not-subset is intrinsically much easier than subset under fair draws. Every model's M2 test uses its own event null, rather than comparing raw success rates for opposite events or proclaiming the negative model superior.

## Negative arm as an independent algorithm

Each negative model fits a distinct complement-probability mixture from its corresponding positive model's fitted marginals, chronological recent/decayed frequencies, observed pair co-occurrence residuals and (for the geometry branch) zone occupancy. It evolves and selects its own anti-parameter genome. It estimates a two-ball pair exclusion event, finds an excluded pair, optimizes its own candidate combination subject to a hard exclusion and a contrasting candidate position, and scores exclusion probability and full candidate overlaps separately. Original positive model code is retained unmodified.

The negative candidate hard-excludes the two exclusion numbers from its generated ticket; this does not make a prediction claim that neither exclusion number will actually be drawn. After the draw, record both not-subset and disjoint events to avoid confusing the weaker and stronger logical conditions.

## Cell division and inherited parameters

Each negative model starts with multiple genomes and can ingest a prior persisted champion. A separate, strictly past-only rolling validation evaluates per-number absence Brier, picks best parents, performs crossover and bounded mutation, and repeats for multiple generations. Every generation stores genotype, parent IDs, ancestry origin, fitness and selected champion. The M05+ original Challenger evolution also survives. `--previous <earlier-44-report.json>` passes all eleven negative champions and the original positive champion into a second real calculation. A CI acceptance run checks not merely inherited booleans but the **exact prior champion genome appearing as an evaluated first-generation parent**.

## M1 / M2 / M3 for all 22 model arms

M1 verifies legal tickets and contract. M2 performs binomial comparisons against either the correct subset event baseline or its mathematical complement, per arm. M3 fits a shrink-to-fair coefficient using earlier chronological folds and evaluates the last unseen fold. The available 3-fold audit and its one observation in the final test are **insufficient for claims of predictive edge**; all reports say NO_EDGE and multiple tests are unadjusted.

## Run on official-cited as-of snapshot (not continuously live authenticated)

Build input:

    python -m research.supercompute.v47_merge_history --output-dir run/current

Generate all 44 models and freeze both 22-row reports:

    python -m research.supercompute.v47_hedge generate --ssq-data run/current/ssq-merged-history.json --dlt-data run/current/dlt-merged-history.json --ssq-target 2026131 --dlt-target 26130 --generations 2 --validation 4 --holdout 3 --mc-trials 80 --physics-steps 6 --seed 20261114 --output run/hedge44.json --freeze-dir run/frozen

Build next generation with the prior champion genomes and create-only files:

    python -m research.supercompute.v47_hedge generate --ssq-data run/current/ssq-merged-history.json --dlt-data run/current/dlt-merged-history.json --ssq-target 2026131 --dlt-target 26130 --previous run/hedge44.json --generations 2 --validation 4 --holdout 3 --seed 20261115 --output run/hedge44-inherited.json --freeze-dir run/inherited-frozen

Score a frozen game only against a user-supplied actual draw and its exact hash. This score is explicitly marked as unverified source until an issuer data receipt separately verifies the draw:

    python -m research.supercompute.v47_hedge score --frozen run/frozen/ssq-2026131-hedge22.json --sha256 <actual_sha256> --actual <actual_json_path>

Run the executable acceptance tests:

    python -m unittest discover -s research/supercompute/tests -p 'test_v47_hedge.py' -v

CI: `.github/workflows/v47-hedge-44.yml` produces a create-only combined report and two game-specific frozen reports and uploads all artifacts. Legacy 11-model jobs remain intact for prior evidence compatibility and do not turn into 22 models by relabeling their old results.

## Limitations

Frequent non-subset outcomes under a random fair lottery are baseline probability, not predictive power. Forecasting physical draw outcomes reliably with historical patterns and an uncalibrated toy physics simulation is unsupported; physics and signatures remain clearly flagged. A reproducible historical validation/PR run is not proof of two unattended GitHub cron triggers or of real Windows reboot recovery.
