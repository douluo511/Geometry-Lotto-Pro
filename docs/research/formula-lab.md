# Bounded causal formula research (code only)

This module extends reviewed prior work without promoting a lottery model. It
does not claim that formula search or more computation improves a random draw.
`formal_A=0`, `edge=NO_EDGE`, and zero admitted prospective predictions are hard
boundaries. A SHA256 of local content is not an authenticated predraw timestamp.

## Existing work inspected

| Source | Pinned commit | Reuse / difference |
|---|---|---|
| main | `241684ed09f348b845d7150b92b01b3d6171b828` | imports game specs, deterministic seed and HOT60/EWMA30 only |
| #470 | `199cc2a2797f11b8179aaa6649f0649613c72010` | inverse fitting / committee work inspected; no oracle fit or live paid API included |
| #478 | `dede22dff2d5e22d8d36dc643a556ff94e389bf7` | ablation/control protocol inspected; no exhaustive repeat or original bank rewrite |
| #479 | `3d6516d59ae92c4025570e5b3de315ba79792977` | pure port of its 72-expression grammar, legal remapping and same-issue research NULL |
| #480 | `3945d0ec9f81fb2c63af84e2cd8e0160a4fe5bb9` | freezes a roster but refits residuals online; this module also freezes residual parameters |
| #481 | `73981a8cd6461f5582a52bc007364524bb5a68bb` | source/prospective implementation inspected; external storage extended to any Git root and Windows junctions |

This independent PR adds only its own package, synthetic tests, one synthetic
workflow and this document. Existing V4.7 source, seeds, frozen ledger and PRs
are not edited. The pure library port avoids depending on unmerged PR code or
importing its unsafe default real-data writers. No historical fixtures or old
workflow artifacts are copied into this PR. If #479 later merges, consolidate
the pure functions with explicit parity tests rather than maintaining two APIs.

## Algorithm and split

The grammar enumerates ATOM/DOUBLE/ADD/SUB/MUL over LAG1/LAG2/LAG3/ISSUE with
calibration windows 8 and 16. Commutative trees are canonicalized. Offsets are
categorical modular-residual modes, tied toward the smallest residual, learned
only from training. ISSUE retains #479's previous-issue-plus-one expression;
that mathematical input is not authoritative identification of a future issue.

The validation objective is average front overlap/front count plus back
overlap/back count, minus uniform expectation, minus `penalty * complexity`.
Complexity is operator node count + log2(window) + 1 (calibration parameter
family). Default penalty 0.005 is fixed, not tuned against held-out D2 hits.
At most eight behaviorally distinct formulas are combined with equal weights,
at most two per operator family. Selection can honestly return fewer than eight.
D2 is the two highest ensemble votes; it is not inferred from sorted ticket order.

Default private-study split: 180 training, 60 validation, 120 held-out draws.
The CLI requires exactly the declared cohort, so it cannot silently discard
losses or select a favorable slice. The user must explicitly prepare any cohort
outside the repository; all research-selected historical slices remain exploratory.

Two separately labelled protocols score every held-out issue:

- **Frozen:** fit on training, select on validation, then freeze expressions,
  offsets and weights. New past observations may enter the lag inputs but never
  refit the model. This is one-step prediction, not a 120-step forecast made at
  the freeze time.
- **Rolling:** repeat that train/validation split at each origin, using only
  the observed prefix. Formula search never sees its target outcome. This is an
  adaptive diagnostic, not another independent replication of the same cohort.

Controls: identical #479 issue-keyed research NULL, HOT60, EWMA30, a model trained
on permuted development outcomes, and four fixed iid negative-control streams.
Every control is scored on exactly the model's issues, including all misses.
**The research NULL is not the immutable formal V4.7 NULL.** This implementation
preserves the latter's files, but does not claim to have authenticated or paired
against private V4.7 records that were not supplied.

## Statistics

Exact uniform theory is derived independently using hypergeometric front/back
overlaps and their product. It provides D2, exact front, exact back and whole
ticket probabilities; the joint histogram and average zone overlaps are retained.
Binary hit rates include Clopper-Pearson 95% intervals, including zero successes.
Matched controls use two-sided exact discordance tests and paired differences.
Holm correction spans both games, both evaluation modes, all eight controls and
all four binary endpoints plus each model-vs-theory comparison (144 tests).
Control-vs-theory p-values are not reported or hidden outside this family.

Seven-period circular block bootstrap intervals (499 deterministic resamples)
describe paired differences, including front/back overlap. They are unadjusted
exploratory intervals, not proof of significance. Exact binomial inference assumes
iid Bernoulli trials; exact paired inference assumes exchangeable discordances.
Adaptive predictions may violate independence. Block resampling does not eliminate
that limitation, selection bias, reused historical data or data provenance gaps.
No statistic changes `NO_EDGE` or admits a prospective sample.

## Compute and bounds

The NumPy fitter broadcasts bounded residual histograms across formulas, training
rows and positions. It uses integer arithmetic and agrees exactly with the original
scalar estimator, including ties. At most two processes are allowed; one is default.
Benchmark timings include input validation, allocation and result construction,
alternate backend order and report medians of seven repetitions. A full selection
profile identifies time spent outside the fitting kernel. A fitting speedup must
not be represented as the same end-to-end speedup.

Limits: train 40..2000, validation 10..150, holdout 1..300, complete input <=2500
rows, private JSON <=32 MiB. CI has per-job timeouts, read-only permissions and
one BLAS/OpenMP thread. Numba/GPU are intentionally unused until a measured workload
justifies installation/JIT/startup overhead. Exhaustive enumeration is unnecessary
for the already exact combinatorial baseline.

Official implementation references: [NumPy broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting.html),
[SciPy binomial tests and exact intervals](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html),
[Python process pools](https://docs.python.org/3/library/concurrent.futures.html).

## Windows / Ubuntu execution

Install Python 3.11 and `python -m pip install -r research/formula_lab/requirements.txt`.
Run offline checks with `python -m pytest -q research/formula_lab/tests`.
Run synthetic computation with:

```text
python -m research.formula_lab.cli synthetic --train 180 --validation 60 --holdout 120
python -m research.formula_lab.benchmark --parallel
```

These commands print only synthetic technical metrics and aggregate execution
status. No dataset, tickets, per-issue report, receipts or artifacts are uploaded
by `.github/workflows/ssqdlt-formula-lab.yml`. It performs real Windows/Ubuntu
unit tests and actual synthetic calculations; it is not a real-draw backtest.

For locally authorized historical work:

```text
python -m research.formula_lab.cli private --authorized-root PRIVATE_ROOT --input PRIVATE_ROOT/input.json --output PRIVATE_ROOT/new-report.json --train 180 --validation 60 --holdout 120
```

`PRIVATE_ROOT` is a user-authorized persistent location outside any Git repository.
Input schema: `games` maps `ssq` and `dlt` to chronological row lists; each row
contains `issue` (numeric string), `front` and `back` (strictly sorted distinct
integer arrays). No real example is checked in. Inputs and outputs must resolve
within the authorized root. Git roots/worktree `.git` files, symlinks, Windows
junctions/reparse points, Git environment redirections and hosted GitHub Actions
real mode are rejected. Files
are create-only and fsynced. Windows access control is a responsibility of local
directory provisioning; POSIX mode 0600 alone does not establish a Windows ACL.
The filesystem guard assumes no hostile concurrent replacement of parent folders.

Private output contains the complete cohort, model/parameter identities, all
scores, confidence intervals and input digest. Public output suppresses paths,
draws, private digests, predictions and per-period results, including on errors.

## Prospective boundary and unresolved work

`prospective.admission` always fails closed because no independent official target,
sales cutoff or predraw timestamp verifier is configured. Caller booleans and
self-computed hashes cannot unlock it. Reuse #481's pinned official intake and
shadow scoring locally with raw bytes in authorized storage; those observations
still do not satisfy independent predraw proof or constitute formal forecasts.
No retroactive prediction is created when verification fails.

Historical out-of-sample replay is not independently preregistered future evidence.
A real future outcome cannot be tested before the draw occurs. No future scheduler,
paid API request, lottery purchase, main merge or V4.7 promotion is authorized here.
The main branch already has historical fixtures and separate data-publishing
workflows. This Draft neither triggers nor removes those legacy workflows and
does not purge old Git history/artifacts; repository-wide migration is unresolved.
