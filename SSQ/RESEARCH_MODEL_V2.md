# SSQ Research Model V2 — Multiscale Ridge / Random Baseline Gate

Status: **RESEARCH CANDIDATE / NOT PRODUCTION EDGE / NOT FINAL**

This document freezes the clean SSQ research candidate created after the useful-vs-useless feature review.

## First-principles baseline

SSQ contract:

- red/front: choose 6 from 33, marginal null probability = 6/33
- blue/back: choose 1 from 16, marginal null probability = 1/16
- absent verified predictive information, every legal exact 6+1 ticket has the same mechanism probability

Therefore historical patterns are candidate features only. They are not predictive evidence by themselves.

For two fixed red-ball dans, the exact random baseline is:

- P(0 hits) = C(31,6) / C(33,6)
- P(1 hit) = 2*C(31,5) / C(33,6)
- P(2 hits) = C(31,4) / C(33,6)
- P(at least 1 hit) = P(1)+P(2)

Any dan model must beat this null on future, chronology-safe data before an edge claim is even considered.

## Default candidate feature vector

For each number and area:

1. 20-draw standardized frequency
2. 60-draw standardized frequency
3. 120-draw standardized frequency
4. 120-draw exponentially weighted standardized deviation, decay = 0.97
5. 20-minus-120 standardized trend
6. 20-minus-60 standardized trend

A logistic Ridge model is trained only on rows whose features use history strictly before the target draw.

The current-number research probabilities are calibrated by a common logit shift so that:

- sum(red marginal probabilities) = 6
- sum(blue marginal probabilities) = 1

This prevents aggregate probability inflation.

## Features deliberately excluded from the default V2 candidate

The following are **not** accepted as predictive features merely because they are popular lottery heuristics:

- omission/gap / "overdue"
- raw recency
- previous-draw transition
- pair/co-occurrence graph
- geometry-state and geometry-transition
- forced odd/even ratio
- forced zone ratio
- forced sum range
- AC value
- span
- tail-number pattern

They may remain in separate challenger/ablation experiments, but they cannot be promoted without current-version OOS evidence.

### Why omission is excluded

Under the independent-draw null, a number being absent for many draws does not make it "due". A positive gap bonus is therefore not permitted by default. Gap can be used for diagnostics or as a separately pre-registered challenger, never as an assumed edge.

### Bayesian frequency note

With a common prior, common window size, and the same prior strength for every number, posterior-mean shrinkage is a monotone transform of the count. It stabilizes probability estimates but does not create a new ranking signal. It can be used for calibration research, but is not counted as independent evidence of an edge.

## Production shrink gate

The only permitted production probability from this module is:

    p* = (1-rho) * p0 + rho * q

where:

- p0 is the uniform marginal baseline
- q is the calibrated research probability
- rho is constrained to [0,1]

Default and current value: **rho = 0**.

This module has no authority to increase rho. With rho=0, production probabilities remain exactly uniform even if the research ranking looks impressive in-sample.

## Required evidence before any non-zero rho

At minimum:

1. chronology-safe walk-forward; no random train/test shuffle
2. same-target comparison to the uniform random baseline
3. two-dan hit distribution vs the exact null
4. six-red hit distribution and blue hit rate vs exact null
5. bootstrap confidence interval with lower bound above zero for the chosen score delta
6. permutation test with multiple-testing correction
7. era stability across at least three periods
8. untouched final holdout
9. null-world / synthetic-null false-edge tests
10. feature ablation, including removing each retained feature
11. challenger tests for the excluded heuristics
12. prospective immutable pre-draw replay evidence

If the evidence is insufficient or unstable, the required result is:

- edge_state = NO_EDGE
- dan_state = NULL_DAN
- rho = 0

## Interpretation of "useful"

- **Useful for validation:** random baseline, chronology guard, bootstrap/permutation, ablation, null worlds.
- **Useful as candidate predictors:** multiscale frequency and EWMA/trend only until OOS results decide.
- **Useful only as descriptive diagnostics unless proven otherwise:** odd/even, zones, sums, spans, tails.
- **Rejected as a default predictive assumption:** positive omission/gap compensation.

## Delivery boundary

This research candidate does not clear Repository Independence, independent Release N→N+1, formal release re-download Same Hash, updater real-network acceptance, or Final Gate. Those remain separate hard gates.
