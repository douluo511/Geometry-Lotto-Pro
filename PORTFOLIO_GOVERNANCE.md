# Portfolio Governance — Frozen Non-Degradable Release Rule

This repository is a **shared migration / acceptance workspace**, not an acceptable final home for any independent product.

## Mandatory project independence

Every final system must have its own repository, code, data, configuration, models/rules/content, updater, Windows build, Exact EXE, Same Hash evidence, Final Gate and final artifact.

While a project remains in this shared repository:

- `repository_independence = FAIL`;
- Final Gate must remain FAIL even when every technical/business gate passes;
- no artifact may be labeled or uploaded as the unique portfolio FINAL;
- technical PASS remains useful audit evidence only.

## Frozen hard-gate chain

Requirements / purpose → 5 Why → risk boundary → Domain Model → architecture → function/API contracts → sources → NetClient → Storage → Engine → Evidence → Service → UI → Self-Test → Unit/Contract/Integration → Fault Injection → Real Network → Business validation → Counterexample / Reversal → Windows Build → Exact EXE → Physical GUI Click → Same Hash → repository independence → evidence-derived Final Gate → unique artifact.

Only explicit, current-run, machine-verifiable PASS counts. PENDING, WARNING, SKIPPED, UNAVAILABLE, UNKNOWN, stale evidence, inherited PASS, or missing evidence fail closed.

## Change invalidation

Any substantive change to a project's code, models, rules, data chain, source parser, production parameters, UI→Service binding, build, acceptance logic, or governance gate invalidates the affected acceptance evidence and requires the full applicable chain to be rerun.

## Scientific honesty

For predictive/research systems, a null result such as NO_EDGE / NULL_DAN is acceptable when independently validated. A release must never manufacture an edge to satisfy product expectations.

## Promotion rule

A product may be called complete/final only when:

- Engineering completion = 100%;
- Business-content completion = 100%;
- repository_independence = PASS;
- Final Gate = PASS;
- hard_fail_count = 0;
- the final artifact is the exact bytes validated by Same Hash.

This rule is non-degradable.
