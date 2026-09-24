# Unified Lotto Model Governance (DLT + SSQ)

This contract is frozen for both lottery applications.

## Release chain

Candidate model pool -> independent falsification -> reject false edge -> validated model promotion ->
Champion/Ensemble Freeze -> Windows EXE -> exact-package revalidation -> same-hash ->
final_release_gate == PASS -> one final artifact.

## Candidate pool

All useful model families may enter validation, including:

- random baseline
- simple frequency / single-number probability
- recency and gap
- transition
- pair/co-occurrence graph
- geometry state
- geometry transition
- ranking model
- logistic regression
- decision tree
- gradient boosting
- research ensemble
- multiple windows, seeds and model perturbations

Candidate membership NEVER grants production weight.

## Required per-model falsification

Every candidate that can affect production must independently pass all of:

1. Walk-forward OOS
2. Explicit random baseline
3. Bootstrap lower-bound test
4. Remove/Shuffle/Random ablation
5. Reality Check
6. Holm multiple-testing correction
7. Leave-One-Era-Out
8. Leakage Sentinel
9. Null-world false-positive-rate firewall
10. Untouched holdout

Missing evidence => UNVALIDATED.
Executed but insufficient evidence => NO_EDGE.
Complete reproducible evidence => VALIDATED_EDGE.

## Ensemble firewall

Multiple surviving models may be fused only if the ensemble independently passes:

- model correlation / redundancy screen
- incremental information test
- remove-one-model ablation
- ensemble gain over each admitted component/baseline
- weight stability across windows/seeds/eras

Ten correlated variants of one signal are not ten independent votes.

## Production rule

Production prediction may load only frozen VALIDATED_EDGE members.
REJECTED/NO_EDGE/UNVALIDATED models receive zero production weight.
If no model survives, the auditable random/uniform baseline remains Champion.

No system is allowed to fabricate a Dan/edge merely because a prediction UI must return numbers.

## Allowed scientific states

- VALIDATED_EDGE
- NO_EDGE
- UNVALIDATED

## Exact-package rule

A model or ensemble is not production-approved until the exact Windows EXE bytes that contain
that frozen production graph rerun the scientific acceptance and the delivered EXE SHA-256 is the
same hash recorded by the acceptance report. PASS requires zero hard FAIL and
final_release_gate == PASS.
