# V4.5 D2 study: no demonstrated improvement

Design was published before outcome scoring in commit
`6ad6343b3130271ff122bb4f8ce842bf46401c35` (tree
`2e7caaefeefd55ec612803408bf677f4ba20b5dd`). Local plan SHA256 is
`ce4545aa00941cda7fe2868d63d5900432779a50ec1d7a4f3f8edff8ff9c0720`.
The public design timestamp and local seal do not qualify historical forecasts
as prospective. No model source or design changed after outcome scoring.

## Locked historical audit-test

| Model | SSQ hits / 392 | SSQ rate | DLT hits / 564 | DLT rate |
| --- | ---: | ---: | ---: | ---: |
| Hot60 | 15 | 3.827% | 11 | 1.950% |
| EWMA | 17 | 4.337% | 11 | 1.950% |
| ShrinkMix | 15 | 3.827% | 13 | 2.305% |
| Fixed primary Pairwise-D2 | 11 | 2.806% | 11 | 1.950% |
| Fixed-seed Random NULL | 9 | 2.296% | 8 | 1.418% |
| New isolated Pair-Residual | 8 | 2.041% | 10 | 1.773% |

All ten one-sided paired comparisons fail the registered .05 Holm family:
minimum adjusted p = 0.8431877195835175; the other nine equal 1. The secondary
fair-uniform-null mixture p bounds, adjusted as their separately prespecified
ten-test family, all equal 1. All paired 95% intervals include zero. These
conditional method outputs require their stated assumptions and are not proof
that the underlying lottery is fair, biased or predictable.

The fixed primary's same-period NULL difference is SSQ +0.510 percentage points
(conservative 95% interval -3.367 to +4.370 pp) and DLT +0.532 pp (-2.114 to
+3.162 pp). The residual candidate has fewer full hits than the original primary
in both audit slices; its proposed improvement is unsupported by this run.

EWMA has the largest SSQ audit-slice rate, but it cannot be selected after
seeing that slice. The pre-fixed validation nomination was ShrinkMix for SSQ,
and no positive validation-delta nominee for DLT. Neither nomination establishes
a winner or replaces the fixed operational primary.

## Scope and verification

Every available eligible period is retained: SSQ 1,956 and DLT 2,816, total 4,772
rows, with six exact two-number forecasts each (28,632 scored forecast pairs).
The first 120 rows per game were warmup; development/validation/test counts are
SSQ 1173/391/392 and DLT 1689/563/564. The existing model code is unchanged.

The independent result check rescored all 28,632 pairs, matched 175 original
producer forecasts at 35 fixed prefix indices, independently reconstructed 35
residual and 35 seeded NULL pairs, checked all 36 summary rows and confidence
intervals against independent arithmetic/SciPy, and verified the whole ten-test
Holm family. Maximum CI discrepancy was 3.32e-15. The export groups rows by
canonical stage-key order; every stage is chronological and complete. The first
audit script incorrectly assumed one global export ordering; its original and
the correction are preserved. No product code, model or result was changed.

Separately, 170 full regression tests pass on local Windows (0 errors/failures/
skips). The 170 SciPy numerical cross-checks are a different scope, not extra
product tests; maximum tail/quantile error was 3.80e-12. Exhaustive synthetic
tests cover every uniform draw for pair-overlap probabilities and sparse-CI
coverage. Real archived-row source availability remains absent.

## What remains unproved

- **Demonstrated improvement:** none.
- **Retrospective observations only:** the displayed rate differences, validation
  nomination and fixed residual trial. They may be sampling variation; they
  cannot justify choosing the best audit-test model.
- **Not run / blocked:** new independent prospective replication, actual admitted
  next issue/deadline, original formal eight-model/twelve-family qualification,
  actual 01--04 authority and external pre-draw seal.

For an assumed absolute +1 percentage point alternative, conservative planning
at 80% target power and .05/10 one-sided planning alpha gives approximately
7,801 SSQ or 5,091 DLT periods per game (maximum-discordance scenario). The
independent-success scenarios give 7,546 and 4,986. These are approximations,
not guarantees or evidence that such an effect exists. The current 392/564
audit slices cannot provide this planned sample size. No future issue list is
invented; enrollment has not started.

`formal_A=0`, `NO_EDGE`, `repository_independence=FAIL`, `Final=FAIL` remain.
Do not tune this study's parameters after these outcomes and reuse its locked
historical slice as an unseen test. A new hypothesis requires a new registered
independent cohort.
