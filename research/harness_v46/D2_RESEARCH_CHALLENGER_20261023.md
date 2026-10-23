# SSQ＋DLT V4.7 — D2 Recency-Pair Research Challenger (NOT a forecast edge)

**Identity:** `RECENCY_PAIR_H45_120_V1` — a new isolated experimental
hypothesis. It is **not** a replacement for the registered six producers,
their frozen predictions, original V4.5 formal eight slots, or fixed
`random_null`. Do not backdate a candidate or pick a model using test results.

## Single fixed hypothesis and objective

On a 120-draw prior training window, count all front-zone pairs with
weight `2^(-age_in_draws/45)`; select the pair with the largest weighted
co-occurrence sum, resolving exact ties by numeric pair order. That one
ordered two-number pair is the only proposed D2 pair for this arm.
There are NO adjustable CLI knobs for the window, half-life or holdout
boundary. This does not imply causality: independent fair draws have no
predictable pair preference.

The SSQ fair D2 probability is `15/528` (2.8409%), and DLT
`10/595` (1.6807%). These are *mathematical references*, not estimated
historic odds. Attempting many pair variants until one looks superior
would be post-hoc selection, not evidence of improved prospective odds.

## Runnable research diagnostic

```sh
python -m research.harness_v46.d2_challenger_lab \
  --snapshot-bundle SSQ_DLT_UNVERIFIED_HISTORY.json \
  > retrospective_d2_experiment.json
```

The input must have EXACT `SSQ` and `DLT` snapshots in the same
existing `research.harness_v46.core.validate_study_snapshot` schema:
at least 121 observed draws per game, strict issue/date ordering,
front/rear ball validation and timezone-aware
`drawn_at`/`published_at` for every row. For each historical target
index 120 onward, the algorithm uses only records 0..i-1 and rejects
a target if ANY prior row has `published_at >= target.drawn_at`.
It evaluates **every contiguous available** historical target row:
no favorable-trial sampling, no future outcome in the predictor.
If a required row lacks a defensible publication time, DO NOT invent
one to pass the gate.

The returned JSON binds all input values and every evaluation row
by SHA256 and records for each draw the experimental D2, legacy
`pairwise_d2` and same-issue fixed `random_null` pair, plus D2 hits.
Exact binomial/paired results are explicitly **unadjusted exploratory**
statistics; no Holm-family, pre-registration, source-authentication,
independent timestamps, or future trials are claimed here.
The CLI is deliberately retrospective; this code path does not issue
an externally trusted predraw freeze.

This report cannot be promoted even if the candidate has more historical
hits than NULL. The old DLT 69/2880 negative-control anomaly remains
`FALSIFIED_REPRODUCED_NOT_FIXED`; a strong historical deviation alone
can reflect non-independent PRNG sampling or selection bias.

## Mandatory progression before any real improvement claim

Use authentic source-by-source checked G00/G01 histories and true
publication times. Independently preregister a future candidate identity,
a uniquely frozen D2 and the entire future issue schedule, with trusted
pre-cutoff custody, authenticated results, and one unchanged contemporaneous
Random NULL. Reserve a disjoint future horizon and stop rule before
any draw; report all failed/missing trials. Quantify D2 rate difference,
exact paired disagreements, confidence intervals, family-adjusted inference
and independent replication. Do not use this already-exposed historical
diagnostic as future evidence. Engineering CI PASS != prediction edge.

**Permanent classification for this diagnostic:**
`formal_A=0`, `RESEARCH_VALID=NOT_YET`, `D2_EDGE_CONFIRMED=NO`,
`NO_EDGE`. No ticket purchase or changes to `main`.
