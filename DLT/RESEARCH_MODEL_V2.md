# DLT Research Model V2 — Multiscale Ridge / Random Baseline Gate

Status: **RESEARCH CANDIDATE / NOT PRODUCTION EDGE / NOT FINAL**

This document freezes the research formula introduced on top of the current DLT product head.

## First-principles baseline

For each draw:

- front marginal baseline: 5/35 = 1/7
- back marginal baseline: 2/12 = 1/6
- every legal exact 5+2 combination has the same lottery-mechanism probability absent verified predictive information.

Historical patterns are therefore candidate features only. They are not evidence of a predictive edge.

## Candidate features

For each number and area:

1. 20-draw standardized frequency
2. 60-draw standardized frequency
3. 120-draw standardized frequency
4. 120-draw exponentially weighted standardized deviation, decay = 0.97
5. 20-minus-120 standardized trend
6. 20-minus-60 standardized trend

Gap/omission is deliberately excluded from the default feature vector. No "overdue" assumption is allowed.

## Ridge probability model

A logistic ridge model is fit only on rows whose features are computed from history strictly before the target draw.

The current-number research probabilities are calibrated by a common logit shift so that:

- sum(front probabilities) = 5
- sum(back probabilities) = 2

This prevents aggregate probability inflation.

## Production shrink gate

The only permitted production probability is:

    p* = (1-rho) * p0 + rho * q

where:

- p0 is the uniform marginal baseline,
- q is the calibrated research probability,
- rho is constrained to [0,1].

Default and current value is **rho = 0**.

This module has no authority to increase rho. A non-zero rho requires a separate current-version out-of-sample Evidence Court decision. Without that evidence, production probabilities remain exactly uniform.

## Promotion requirements

This research candidate must not be called predictive or promoted merely because it fits history.

Before any production integration, it must pass the existing DLT scientific firewall, including at minimum:

- chronology/leakage guard
- walk-forward out-of-sample comparison
- uniform random baseline
- bootstrap confidence interval
- permutation test
- multiple-testing correction
- era stability
- untouched holdout
- null-world false-edge tests
- prospective immutable pre-draw replay evidence
- DLT Dan firewall

A code or policy change invalidates old model/evidence hashes and requires fresh downstream acceptance.

## Current delivery boundary

Repository Independence, real independent Release N→N+1, formal release re-download Same Hash, and Final Gate are unaffected by this research PR and remain separate hard gates.
