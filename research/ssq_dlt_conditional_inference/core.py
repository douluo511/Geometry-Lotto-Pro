"""Fixed-endpoint empirical-Bernstein bounds for average conditional means.

Howard et al. (2021), Theorem 4, Appendix A.8, arXiv:1810.08240.
No IID/common-mean assumption. Bounds concern the observed period's average
conditional expectation, not a stationary population or future performance.
All statistical choices are explicit. This module does not register a trial.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Iterable, Mapping

PRECISION = 80
MIN_LAMBDA = Decimal("1e-30")


def _decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric observation/parameter")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid numeric input") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite input")
    return result


def _c(lam: Decimal) -> Decimal:
    # Series avoids catastrophic cancellation for small lambda.
    if lam <= Decimal("0.1"):
        power = lam * lam
        total = power / 2
        k = 3
        while True:
            power *= lam
            term = power / k
            updated = total + term
            if updated == total:
                return total
            total = updated
            k += 1
    return -(1 - lam).ln() - lam


def coefficient(lam) -> Decimal:
    """Numerically stable -ln(1-lambda)-lambda, in the supported domain."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        x = _decimal(lam)
        if not MIN_LAMBDA <= x <= 1 - MIN_LAMBDA:
            raise ValueError("lambda outside numerical domain [1e-30,1-1e-30]")
        return +_c(x)


def analyze(values: Iterable, *, lower, upper, center, lambdas: Iterable,
            alpha, null_mean, expected_n: int) -> dict:
    """One fixed endpoint; equal-weight finite-grid union correction.

    center is one explicit constant, not an outcome-dependent center array.
    The caller still must precommit it before outcomes. It differs from null_mean.
    Rows, timestamps,
    trial registration and completeness must be checked outside this toolkit.
    A two-sided 1-alpha interval spends alpha/2 on each tail. The one-sided
    bound and p-value spend alpha on the upper-deviation test H0: average
    conditional mean <= null_mean, almost surely. Neither is an IID CI.
    """
    if isinstance(expected_n, bool) or not isinstance(expected_n, int) or expected_n <= 0:
        raise ValueError("expected_n must be an explicit positive integer")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        lo, hi, m, a, null = map(_decimal, (lower, upper, center, alpha, null_mean))
        if not lo < hi or not lo <= m <= hi or not lo <= null <= hi:
            raise ValueError("Invalid range, center or null_mean")
        if not 0 < a < 1:
            raise ValueError("alpha must be in (0,1)")
        data = tuple(map(_decimal, values))
        if len(data) != expected_n or any(x < lo or x > hi for x in data):
            raise ValueError("Length mismatch or out-of-range observation")
        grid = tuple(map(_decimal, lambdas))
        if not grid or len(set(grid)) != len(grid):
            raise ValueError("An explicit nonempty grid without duplicates is required")
        if any(not MIN_LAMBDA <= x <= 1 - MIN_LAMBDA for x in grid):
            raise ValueError("lambda outside numerical domain [1e-30,1-1e-30]")
        n, scale = Decimal(expected_n), hi - lo
        total = sum(data, Decimal(0))
        mean = total / n
        v = sum((((x - m) / scale) ** 2 for x in data), Decimal(0))
        log_k = Decimal(len(grid)).ln()
        log_penalty = log_k - a.ln()
        log_two_penalty = log_penalty + Decimal(2).ln()
        entries = []
        for lam in grid:
            cv = _c(lam) * v
            radius_one = scale * (log_penalty + cv) / (lam * n)
            radius_two = scale * (log_two_penalty + cv) / (lam * n)
            log_e = lam * (total - n * null) / scale - cv
            entries.append(dict(lambda_value=str(lam), c=str(_c(lam)),
                                lower_one=mean - radius_one,
                                ci_lower=mean - radius_two, ci_upper=mean + radius_two,
                                log_e=log_e))
        lower_one = max(lo, max(x["lower_one"] for x in entries))
        ci_lower = max(lo, max(x["ci_lower"] for x in entries))
        ci_upper = min(hi, min(x["ci_upper"] for x in entries))
        # A true empty confidence set is retained, never repaired after results.
        log_p = min(Decimal(0), log_k - max(x["log_e"] for x in entries))
        return dict(schema="conditional-eb-toolkit-v1", n=expected_n,
                    bounds=[str(lo), str(hi)], center=str(m), alpha=str(a), null_mean=str(null),
                    mean=str(mean), normalized_squared_residual_sum=str(v),
                    lower_one_sided=str(lower_one), ci_two_sided=[str(ci_lower), str(ci_upper)],
                    ci_empty=ci_lower > ci_upper, log_p_one_sided=str(log_p),
                    grid=[str(x) for x in grid], grid_correction="EQUAL_WEIGHT_UNION",
                    components=[{k: str(v) for k, v in row.items()} for row in entries],
                    estimand="FIXED_PERIOD_AVERAGE_CONDITIONAL_EXPECTATION",
                    scope="NUMERICAL_TOOLKIT_NOT_REGISTERED_TRIAL", confirmatory_eligible=False,
                    numeric_precision_decimal_digits=PRECISION)


def paired_hits(model_hits: Iterable, null_hits: Iterable, *, lambdas, alpha,
                null_difference, expected_n: int) -> dict:
    """D = hit(model)-hit(NULL); fixed normalized center 1/2 (D center zero)."""
    model, null = tuple(model_hits), tuple(null_hits)
    if len(model) != len(null):
        raise ValueError("Unpaired lengths")
    if any(type(x) is not int or x not in (0, 1) for x in model + null):
        raise ValueError("Hits must be literal 0/1 integers")
    return analyze((x-y for x, y in zip(model, null)), lower=-1, upper=1, center=0,
                   lambdas=lambdas, alpha=alpha, null_mean=null_difference, expected_n=expected_n)


def fair_baseline_hits(hits: Iterable, *, p0, lambdas, alpha, null_increment,
                       expected_n: int) -> dict:
    """Marginal H in [0,1], explicitly testing p0 + null_increment."""
    data = tuple(hits)
    if any(type(x) is not int or x not in (0, 1) for x in data):
        raise ValueError("Hits must be literal 0/1 integers")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        base = _decimal(p0)
        target = base + _decimal(null_increment)
        if not 0 < base < 1:
            raise ValueError("p0 must be in (0,1)")
        return analyze(data, lower=0, upper=1, center=base, lambdas=lambdas, alpha=alpha,
                       null_mean=target, expected_n=expected_n)


def intersection_union(log_p_paired, log_p_fair) -> Decimal:
    """Valid only when BOTH supplied component p-values are valid for their nulls."""
    x, y = _decimal(log_p_paired), _decimal(log_p_fair)
    if x > 0 or y > 0:
        raise ValueError("log p must be <=0")
    return max(x, y)


def holm_log_pvalues(log_pvalues: Mapping[str, object]) -> dict[str, str]:
    """Holm adjustment for an explicit complete family; no independence needed."""
    if not log_pvalues or any(not isinstance(k, str) or not k for k in log_pvalues):
        raise ValueError("Explicit nonempty labelled family required")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        rows = [(key, _decimal(value)) for key, value in log_pvalues.items()]
        if any(value > 0 for _, value in rows):
            raise ValueError("log p must be <=0")
        rows.sort(key=lambda row: (row[1], row[0]))
        out, previous = {}, None
        for rank, (key, value) in enumerate(rows):
            adjusted = min(Decimal(0), value + Decimal(len(rows) - rank).ln())
            previous = adjusted if previous is None else max(previous, adjusted)
            out[key] = str(previous)
        return out

