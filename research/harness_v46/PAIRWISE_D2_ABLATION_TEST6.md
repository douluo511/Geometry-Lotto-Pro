# SSQ＋DLT V4.7｜test6 Pairwise-D2 independent oracle and ablation plan

**Scope:** research-only / synthetic contract assertions. This document does not
preregister an official trial, submit current lottery numbers, verify official
sources, request external TSA, or prove an advantage in fair lotteries.

## Canonical inspected parent

- Convergence Draft PR #432 at pinned parent commit
  `f12e47106f1d0c325573a48e39a6e2efd5d459ff`.
- Model version: `v47-research-core-0.1`.
- Identity: `pairwise_d2`; registered window 120 historical draws;
  residual shrinkage `tau=200`; ascending numeric pair tie-break.
- All six model identities, the fixed `random_null` seed and old V4.5
  formal M04/M05-1..5/M06/M07 remain unchanged.

## Existing score (preserved byte-for-byte)

For the last exactly 120 *prior* draws, let `k` be the number of front-zone balls,
`c[a]` and `c[b]` the single-number counts, and `c[ab]` the co-occurrence count:

```text
n = 120
expected[ab] = c[a] * c[b] * (k - 1) / (n * k)
marginal[ab] = (c[a] + c[b]) / n
residual[ab] = (c[ab] - expected[ab]) / (n + 200)
combined[ab] = marginal[ab] + residual[ab]
```

The current pair winner maximizes `combined`, breaking ties
lexicographically. It is **not** a residual-only model. The remaining three
ordered dan are the first three candidates from the most recent 60-draw
single-number frequency ranking excluding the fixed pair.

**Important:** this expected-pair formula is a research normalization,
not an established physical mechanism, calibrated probability, or
proof that co-occurrence residuals predict independent random draws.

## Independent synthetic checks on the new test6 branch

`tests/test_pairwise_v47_independent.py` recomputes **every pair's**
marginal/expected/residual/combined value with exact `fractions.Fraction`
arithmetic independently from the implementation's floating-point path,
then checks its score, winner, tie-break, first-five ranking and immutable
primary D2 on both SSQ and DLT invented fixtures.

Additional checks:
1. 119-row direct Pairwise forecast must BLOCK; 120-row forecast must work
   with a SHADOW-only model hash and parameter contract.
2. Editing only rows older than the 120-draw window cannot move the Pairwise
   ranking or ticket, though it necessarily changes the snapshot identity.
3. Degenerate tied pairs choose numeric ascending.
4. After-the-fact D2 reversals and a record published after `as_of` are refused.
5. An independent marginal/residual/combined decomposition is retained as
   arithmetic diagnostic only; it makes no claim about future draws.

The fixture histories are invented. Existing SSQ/DLT official *seed* files in
`main` are historical baselines, not fresh target-locked and independently
authenticated G00/G01 V4.7 snapshot receipts. **No valid future forecasts
were issued here.**

## Pre-registration *proposal*, not yet an approved study

Three prospective model identities must be locked *before* new target draws
are seen. They are separate versioned hypotheses, not posthoc options for
choosing whichever pair happened to win.

| Candidate | Pair score | Scientific question |
| --- | --- | --- |
| P-MARGIN | `marginal` | Does marginal frequency alone account for any apparent edge? |
| P-RESIDUAL | `residual` | Does joint residual yield increment beyond marginal signal? |
| P-COMBINED | `marginal + residual` | Does the existing combined rule add incremental value? |

For each candidate, record a unique model/version/parameter SHA; freeze
the **single** ordered D2 pair for SSQ and DLT before sales cutoff on the
same official as-of snapshot. Use one frozen, contemporaneous, seed-fixed
Random NULL. D1 and D3-D5 are diagnostics; do not use them to replace main D2.

Compare same-date D2 success/failure pairs with exact conditional McNemar/sign
arithmetic; also report performance against SSQ `15/528` and DLT
`10/595` fair baselines. Record confidence intervals, pre-specified family
and multiplicity adjustment, independent auditing, and a fixed look/stop
policy. This expanded ablation family **must not silently replace** the
legacy formal 12-hypothesis family. Historical tuning/selection periods
are not new independent forward samples. If future results are
indistinguishable from chance, retain `NO_EDGE`.

## P0 gates still not cleared

- Official per-game target/holiday/sales cutoff and >=120 independently
  source-checked rows, raw provenance bytes, semantic two-source agreement,
  as-of proof and exact snapshot SHA: **BLOCKED** until test2 returns
  verifiable evidence.
- Independent external pre-cutoff timestamp with cryptographic receipt: **NOT_RUN**.
- Authenticated actual draw intake and independent read-only paired scoring:
  **NOT_VERIFIED**.
- Real Windows cold boot, installer safety, 30-min recovery, physical/network
  P0 failures: **NOT_RUN**.
- Historical DLT negative-control `69/2880` root cause: **UNRESOLVED**.
- Formal A samples: **0**. Scientific decision: **NO_EDGE**.

Only a finished review of exact-head GitHub Actions logs can establish whether
the newly added synthetic tests actually passed. This test6 branch must remain
a separate stacked **Draft PR** and must not be merged into `main`.
