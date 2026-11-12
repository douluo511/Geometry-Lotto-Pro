# SSQ / DLT mathematical formula discovery V2 — falsification-first redesign

**Date:** 2026-11-12. **Status:** Draft research, NOT a formal V4.7 forecast.

## Why V1 required redesign

V1 generated 72 arithmetic/lag/window expression trees and, on the included 40 historical targets in each lottery, observed **SSQ D2 0/40 vs research random 2/40** and **DLT D2 0/40 vs random 1/40**. Its selection reoptimizes formula IDs on every short rolling window and explicitly uses D2 during selection. Searching more formulas or renting GPUs would raise the opportunity for spurious historical patterns, not establish a future edge.

This redesign **does not claim a better predictive accuracy**. Its objective is falsifiable evaluation with fewer adaptive degrees of freedom.

## Exact procedure (fixed before executing the next V2 historical study)

1. Load the two pinned checked-in historical JSON snapshots and validate game and ball constraints. Record source filename and SHA256. These snapshots are **stale** and do not authenticate official current issues, sale cutoff or provenance.
2. For each game, define a fixed trailing **120-issue historical holdout**; immediately preceding it is a **60-issue development validation** slice; all older records constitute training warmup and must include at least 180 draws. Do not change the boundaries after seeing results.
3. Use the same, code-generated **72 expression tree grammar** as V1. For each formula, compute per-issue predictions over the 60 validation draws using only information *earlier than each validation draw*.
4. **No D2-target tuning.** Rank candidates using centered front/back ball-overlap from validation only, balanced by the expected overlap under uniform draws; omit D2 score from selection because it is rare and easy to overfit. Remove duplicate behavioral fingerprints on the development validation window; choose **8 formula IDs**, maximum two per operator family.
5. **Freeze the entire roster, all operator parameters, tie-breaking, and equal weights** with a SHA256 decision record before evaluating the holdout. Do not change selected IDs or weights for any of those 120 historical targets.
6. Over the 120 holdout targets, refit each selected formula's modular residuals only from draws observed before that target (specified online adaptation). For each test issue, record its candidate ticket, D2 pair, roster SHA, decision SHA and *all outcomes including misses*.
7. Evaluate on exactly the same historical target issues against **three deterministic controls**: fixed, issue-seeded research NULL (distinct from immutable formal V4.7 NULL), HOT60, and EWMA30. Report D2 and full-ticket hit totals, exact paired discordance tests, and Holm-adjusted exploratory p-values for the three comparisons. Use uniform D2 theoretical probability as a fourth reference.
8. Save report.json, report.sha256 and summary.md in a **create-only directory**; upload raw artifacts. GitHub CI must verify the historical cohort size, complete coverage, absence of future-target inputs in the scoring interface, frozen roster across all targets, official-data warning and NO_EDGE nonpromotion.

## What this research does not establish

* Historical holdout is not prospectively preregistered. Since these records existed before code design, even a statistically significant retrospective comparison would not be proof of a future advantage.
* The unreviewed live draw source and sales cutoff, independent trusted predraw seal, real unattended scheduler trigger and cold reboot, immutable full official ledger, and subsequent prospective paired scoring remain **NOT VERIFIED**.
* There is **no model-selection path** into formal V4.7. `require_formal_promotion()` rejects every call, even with user-supplied true booleans. Only a separately reviewed, source-authenticated formal pipeline could change that.
* Exact random baseline for D2: SSQ 6*5/(33*32)=2.841%; DLT 5*4/(35*34)=1.681%. More computational work does not change these fair-draw probabilities.

## Reproduction

From the stacked V2 branch, using Python 3.11+:

```shell
python -m unittest discover -s research/supercompute/tests -p 'test_*.py' -v
python -m research.supercompute.auto_discovery_v2 --validation 60 --holdout 120 --out auto-formula-v2-output
```

CI runs the full test suite on Windows and Ubuntu, then issues the fixed 60/120 historical study and archives create-only receipts. The study produces **no current or future formal candidate**.

## Formal-prediction prerequisites

First verify issue identity and full official source provenance from independent raw responses, source SHA256 and sale cutoff; prove a predraw signed/timestamped create-only seal; preregister a fixed model and sample-size/statistical testing plan; automatically score **every** future issue against independently verified outcomes, compare paired against fixed NULL; require independent review and an explicit promotion decision. Formal forecast must not be activated by a favorable backtest alone.
