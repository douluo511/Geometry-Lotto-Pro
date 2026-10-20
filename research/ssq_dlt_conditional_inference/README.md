# Conditional inference toolkit (isolated, unregistered)

This addition addresses a statistical assumption gap, **not prediction skill**.
Existing plans, seeds, models, holdouts and their frozen inference remain unchanged.
The original formal 12-comparison family, producers for eight slots and approvals
01–04 have **not been established**, as confirmed by the user. This toolkit neither
creates them nor confers admission. A=0, NO_EDGE, qualified prospective samples=0.

The estimand is the **fixed period's average conditional expectation**. It can
change with the realized history. A positive bound does not establish a stationary
effect, future continuation, or a persistent lottery edge. Observations may be
dependent, training windows may overlap, and marginal means may vary. Valid
pre-draw provenance, lawful issue identity and complete paired observations are
still separate required gates; a bounded-data confidence interval cannot repair
post-outcome prediction or missing periods.

## Construction

For Y in [a,b], X=(Y-a)/(b-a), fixed predictable center m in [a,b], and a fixed
0<lambda<1, put c=-ln(1-lambda)-lambda and
V=sum((Y-m)/(b-a))^2. Howard et al., Theorem 4 and Appendix A.8, establish the
nonnegative supermartingale exp(lambda sum(X-E[X|past])-cV).
This module's finite **explicit** equal-weight lambda grid uses union correction;
its members are numerical method parameters, not additional lottery models.
No grid, sample count, family, or protocol is registered here.

For grid size K the one-sided lower bound is the maximum over its members of
mean(Y) - (b-a)(log(K/alpha)+cV)/(lambda*n). The endpoint p-value for the null
average conditional mean<=u almost surely is min(1,K*min exp(-lambda sum(Y-u)/(b-a)+cV)).
Two-sided intervals spend alpha/2 per tail. The center is distinct from u.
All arguments are explicit; no hidden lambda search or outcome-dependent center
is accepted. Fixed finite grids need not shrink to zero width as n grows.

Paired D=Hmodel-Hnull uses range [-1,1] and center 0, so V=discordant_count/4.
The fair component uses H in [0,1], center p0, and tests p0+increment. To require
both paired and fair improvement, an intersection-union p-value is their maximum.
Only valid component p-values can be used. Holm then applies to a complete,
predeclared family. Merely labelling a set of numbers does not register that family.
Zero advantage and +1 percentage point are **different nulls**; the API names the
threshold explicitly. Existing sample-size estimates are not transferred here.

The module uses 80-digit Decimal arithmetic and a stable small-lambda series;
lambda is restricted to [1e-30,1-1e-30] for numerical support. This is a numerical
implementation, not a machine-checked real-arithmetic proof. Inputs, labels,
timestamps, provenance, complete experiment registration and power planning must
be audited externally before any confirmatory use.

## Verification

Run from repository root with Python 3.11+:

    python -m unittest discover -s research/ssq_dlt_conditional_inference/tests -v

All tests use synthetic observations or finite probability trees. No lottery
archive, holdout, prediction ledger or model selector is loaded. Finite tests
check the implementation; the cited argument provides general validity.

Primary source: [Howard et al., Time-uniform, nonparametric, nonasymptotic
confidence sequences, Theorem 4 and Appendix A.8](https://arxiv.org/html/1810.08240).

