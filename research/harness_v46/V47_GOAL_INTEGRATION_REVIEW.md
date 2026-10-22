# V4.7 /goal research-only integration receipt (2026-10-22)

## Exact source and scope

- Parent commit: `f12e47106f1d0c325573a48e39a6e2efd5d459ff` (Draft PR #432).
- Proposed target branch: `research/ssq-dlt-v46-test10-convergence-20261022`; NEVER merge into main via this review.
- PR #439 at `56366520e79b89e5f8141237ad30444b3fb95c38`: official intake must reject claimed parsed history if it lacks preserved successful HTTP 200 raw response bytes; carry full independent regression tests.
- PR #440 at `09df8fc9475f3df77d44d0534dc80c2bdd7cb89b`: EWMA direct entry requires >=120 prior draws; independent oracle test.
- PR #441 at `c7f7b23ecff1bcacb1b12dff5c5831d391480065`: ShrinkMix direct entry requires >=120 prior draws; independent oracle test.
- PR #442 at `da5c45ef39790eaef8d46318261e895de9909622`: independent Fraction oracle and ablation research note, with no model-selection change.
- No current challenger implementation (#443) is integrated or preregistered. Random NULL remains unchanged.
- Canonical `core.py` combines only the two 120-draw guard changes; forecast formulas are unchanged for >=120 draws.

## Reproducible CI

```sh
python -m unittest discover -s research/harness_v46/tests -v
```

The branch must pass both Ubuntu and Windows tests at the exact integration HEAD. Parent or source-PR CI is not sufficient evidence for this merged patchset.

## Adversarial / counterexample tests

- A worker claims raw replay PASS but supplies no preserved raw HTTP response; reject.
- A worker supplies only a non-200 HTML/error response and claims successful replay; reject.
- EWMA and ShrinkMix: 119 prior draws rejected in direct calls, 120 accepted; independent ranking oracles plus time-order/leakage checks.
- Pairwise-D2: Fraction-based independent all-pairs score oracle, 119/120 boundary, ties, mutation, future-publication rejection.

## Independent acceptance gates — currently NOT PASSED

- True official dual-source >=120 independently matched SSQ and DLT histories, target issue, cutoff and publication-time verification: BLOCKED.
- Raw bytes preserved and successfully reparsed are necessary, not sufficient for external official authenticity: BLOCKED.
- External RFC3161 cryptographically verified pre-cutoff seal: NOT_RUN.
- Independently authenticated post-draw outcome intake and full REPLAY/SCORE/AUDIT/REPORT/NEXT: NOT_RUN.
- P0 fail-closed gate/SHADOW trace separation: PR #438 remains separate and unintegrated; MUST review/rebase/test.
- Physical Windows cold boot/network outage/30-minute compensating scheduler fault tests: NOT_RUN.
- Historical DLT 69/2880 negative-control root cause: UNRESOLVED.
- Exact historic 12-hypothesis preregistration and prospective paired Random NULL advantage: NOT_VERIFIED.

## Non-negotiable verdict

`ENGINEERING_PASS=NOT_YET`; `RESEARCH_VALID=NO`; `D2_EDGE_CONFIRMED=NO`; `formal_A=0`; `NO_EDGE`; `SHADOW_ONLY`.
V4.5 M04, M05-1..5, M06 and M07 identities and all historic evidence remain unchanged. No auto-purchase and no claimed prospective predictions.
