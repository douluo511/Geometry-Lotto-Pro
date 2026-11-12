# Reverse Formula Bank v2: frozen-historical ablation and honest paired validation

2026-11-12. Base: main `241684ed09f348b845d7150b92b01b3d6171b828`.

## One goal
Make the **existing Reverse Formula Bank** (6 offset families; 24 lookback anchor positions; min 5 known future validations per anchor; top 12 capped weighted votes) the main **research direction** without silently treating answer-fitted identities as a predictive edge.

Reference original source is pinned at `199cc2a2797f11b8179aaa6649f0649613c72010`, under `research/inverse_formula/{formula_bank,reverse_search,probe}.py`. **Do not copy or modify that source**. New code on main-derived experimental branch loads pinned code in a second independent GitHub checkout. No changes to `main`, Issue #468 V4.7, original fixed NULL, past forecast receipts, or official draw sources. Propose via Draft PR only.

## Exact experimental arms
The unchanged `predict_with_bank` decision is the baseline FULL_WEIGHTED. Compare to equal voting weights FULL_EQUAL and six leave-one-out `DROP_<family>` arms. All arms must reuse the **same catalog of formulas constructed from the past prefix**. For each arm recompute selection and weighted votes from past only; do not recompute offsets after the target result is known. The experiment must verify FULL_WEIGHTED bit-exactly equals the pinned original `predict_with_bank` ticket (front/back/D2).

Run on a fixed cohort of 2026 historical seeded snapshots from main, NOT authenticated live draws. Each arm and fixed independent `_research_null(issue, game)` must predict one D2 and full ticket prior to comparing with that issue's outcome. Record **every issue**, forecast SHA256, formula family and count, red/front and blue/back hits, D2 and full match. Pairwise exact two-sided McNemar vs same-issue NULL, Holm across **16 comparisons** (8 research arms × 2 lotteries), plus fair theoretical baseline and 32 deterministic independent research placebo control streams. Explicitly exploratory/model-selection-biased.

## Causal and data gates
- Never train/validate at or after evaluated outcome; refuse missing/duplicate/unordered issues, invalid balls, inconsistent outcome target issue, modified pinned checkout SHA, changed base original behavior, JSON duplicate/nonfinite.
- Validate the snapshot historical last issue and raw SHA; report separately reproducible old source and current source. Derived candidate is **HYPOTHETICAL POST-HISTORICAL-SNAPSHOT**, cannot be advertised as latest verified prediction.
- Local self-report SHA256 and GitHub commit are not independently trusted predraw timestamp. No score is eligible for formal A without authenticated latest results + independently approved cutoff and timestamp.
- Report status remains `NO_EDGE`, `formal_A=0`, `prospective_scored=0`, `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`. No purchase or bets.
- If branch CI has no available pinned source or wrong SHA, HARD FAIL. Red tests first, real exact-head Ubuntu/Windows green CI and artifact audit. No independent reviewer means `REVIEW_NOT_VERIFIED`.

## Interpretation
A formula that exactly recovers the draw to which its offsets were fitted is **not** evidence it generalizes. A favorable retrospective p-value is also not enough. Only independently preregistered prospective assessments on authentic future draws, with stable error controls and independent review, could support an edge claim.
