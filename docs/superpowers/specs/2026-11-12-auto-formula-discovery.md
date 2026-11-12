# Automatic Formula Discovery V1 — research design (2026-11-12)

## Objective and status

Research-only, completely isolated from formal SSQ/DLT V4.7 forecasts, historical evidence and its fixed Random NULL. This is **not** a live prediction producer. No paid APIs or ticket purchase. No new forecast receipt enters an official ledger.

The current checked-in `official_seed.json` files are historical snapshots. They are not authenticated live feeds and cannot establish an actual current next draw, sales cutoff or independent pre-draw seal. All displayed next-after-snapshot candidates must be marked `not_live=true`, `not_formal=true`.

## Automatic search algorithm

- Enumerate a bounded, deterministic grammar of 72 arithmetic candidate formulas (5 operator families: ATOM, DOUBLE, ADD, SUB, MUL; lag-1, lag-2, lag-3 and next-issue-index inputs; canonicalize commutative operands and obvious x+x duplicates).
- Every candidate also chooses one of two trailing calibration windows, 8 or 16 draws. Modular per-position residual offsets are fitted only to known draws and never to the historical target being scored.
- At each target draw `t`, first freeze `history[:t]`. Inside that prefix, score every candidate on the previous 10 targets; at each inner target `s<t`, refit offsets using only `history[:s]`. Rank by a fixed D2 + front/back coverage surrogate adjusted for uniform-draw expectations.
- Select at most eight formulas, no more than two per operator family, with bounded heuristic weights. Ensemble votes across candidate numbers, chooses a unique valid front ticket, valid back ticket, and an explicit D2 pair contained in the front. Deterministic SHA tie-breaking and hash receipts.
- Predict `t` before consulting its historical actual result. Score every target in the predefined trailing 40-issue cohort, including all losses. A deterministic same-issue seeded random control is distinct from and does not replace the formal V4.7 NULL.

## Validation limits

This exercise is a **retrospective search**, not prospectively registered forecasting. Even with causal outer evaluation, design choices were made after historical data existed. P-values, if displayed, are **exploratory only** and must not be sold as evidence of predictive edge. Data-source failure, unverified issue identity, future knowledge leakage or missing outcomes must block formal promotion. Searching more expressions risks selection overfitting.

An authentic formal-prediction research gateway requires, separately:
1. Contemporaneous independent official draw ingestion with source signatures / raw response hashes, valid current issue identity and sales cutoff.
2. Independently timestamped create-only forecast seal made **before** the cutoff, recording code SHA, model versions, complete predictions, random control and parameters.
3. Later independent official outcome verification against that saved forecast, with a complete append-only record of every attempt, failure and miss.
4. Preregistered model choice and decision threshold, minimum prospective sample size, paired fixed NULL comparison, multiple testing correction, independent review, and explicit authorization to move beyond `NO_EDGE`.

None of these formal gates is bypassed by this PR. In all reports: `formal_A=0`, `formal_prediction=false`, `prospective_scored=0`, `edge=NO_EDGE`.

## Reproduction

Run from repository root, Python 3.11+:

```shell
python -m unittest discover -s research/supercompute/tests -p 'test_auto_discovery.py' -v
python -m research.supercompute.auto_discovery --periods 40 --out auto-formula-output
```

The program creates `report.json`, `report.sha256`, `summary.md` exclusively in a nonexisting destination directory. The branch CI runs both Ubuntu and Windows tests, then performs the complete study and archives SHA-verifiable artifacts. It does not push to the main branch or sealed research ledger.
