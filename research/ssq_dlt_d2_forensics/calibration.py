"""Finite synthetic calibration diagnostics; no prediction candidate is added.

All probability maps use one-based, unordered pair keys.  The empirical and
surrogate prior share observations, so their cross-error term is retained.
Oracle probabilities are generator knowledge, never deployable forecasts.
"""
from __future__ import annotations

from itertools import combinations
import math

from research.ssq_dlt_d2_next.models import conditional_pair_probabilities


MIXTURE_LAMBDA = 60.0 / 260.0
SHRINK_ALPHA = 0.5
MOMENT_MAXITER = 200
MOMENT_TOLERANCE = 1e-9
SNAPSHOT_INDICES = (0, 60, 120, 180, 239)


def _dimensions(n, k):
    if type(n) is not int or type(k) is not int or n < 2 or not 0 <= k <= n:
        raise ValueError("LEGAL_FIXED_SIZE_DIMENSIONS_REQUIRED")


def _uniform_subset_probability(n, k, subset_size):
    """Probability a specified subset is included in a uniform k-subset."""
    if subset_size > k:
        return 0.0
    return math.comb(k, subset_size) / math.comb(n, subset_size)


def true_pair_probabilities(law, n, k, *, favoured_pair=(1, 2),
                            marginal_weight=3.0, odds_ratio=8.0,
                            ring=None, rho=0.25):
    """Exact oracle q for the four preregistered stationary generator laws.

    For the pair tilt with event A, q(B) = [P0(B)+(OR-1)P0(A union B)] /
    [1+(OR-1)P0(A)].  This retains the changed probabilities of every other
    pair, including overlapping and disjoint pairs.  A ring has uniform
    marginals k/n even though its pair probabilities are nonuniform.
    """
    _dimensions(n, k)
    aliases = {
        "FAIR": "UNIFORM", "SCRAMBLED_PAIR_STRONG": "UNIFORM",
        "RING_SCRAMBLED": "UNIFORM", "PRODUCT_WEIGHTS_3": "MARGINAL_STRONG",
        "PAIR_TILT_OR8": "PAIR_STRONG", "FIXED_RING_RHO_025": "RING_PERSISTENT",
    }
    law = aliases.get(law, law)
    pairs = tuple(combinations(range(1, n + 1), 2))
    p0 = _uniform_subset_probability(n, k, 2)
    if law == "UNIFORM":
        return dict.fromkeys(pairs, p0)
    if law in ("MARGINAL_STRONG", "PAIR_STRONG"):
        if (not isinstance(favoured_pair, (list, tuple)) or len(favoured_pair) != 2
                or any(type(i) is not int or not 1 <= i <= n for i in favoured_pair)
                or len(set(favoured_pair)) != 2):
            raise ValueError("LEGAL_FAVOURED_PAIR_REQUIRED")
        favoured = frozenset(favoured_pair)
        if law == "MARGINAL_STRONG":
            if (isinstance(marginal_weight, bool) or not isinstance(marginal_weight, (int, float))
                    or not math.isfinite(marginal_weight) or marginal_weight <= 0):
                raise ValueError("FINITE_POSITIVE_MARGINAL_WEIGHT_REQUIRED")
            weights = [marginal_weight if i in favoured else 1.0 for i in range(1, n + 1)]
            return conditional_pair_probabilities(weights, k)
        if (isinstance(odds_ratio, bool) or not isinstance(odds_ratio, (int, float))
                or not math.isfinite(odds_ratio) or odds_ratio <= 0):
            raise ValueError("FINITE_POSITIVE_PAIR_ODDS_RATIO_REQUIRED")
        z = 1.0 + (odds_ratio - 1.0) * p0
        return {pair: (p0 + (odds_ratio - 1.0) * _uniform_subset_probability(
            n, k, len(favoured.union(pair)))) / z for pair in pairs}
    if law == "RING_PERSISTENT":
        if (not isinstance(ring, (list, tuple)) or len(ring) != n
                or any(type(i) is not int for i in ring) or set(ring) != set(range(1, n + 1))):
            raise ValueError("COMPLETE_FIXED_RING_REQUIRED")
        if (isinstance(rho, bool) or not isinstance(rho, (int, float))
                or not math.isfinite(rho) or not 0.0 <= rho <= 1.0):
            raise ValueError("LEGAL_RING_MIXTURE_PROBABILITY_REQUIRED")
        position = {number: index for index, number in enumerate(ring)}
        result = {}
        for i, j in pairs:
            distance = (position[j] - position[i]) % n
            starts = max(k - distance, 0) + max(k - (n - distance), 0)
            result[i, j] = (1.0 - rho) * p0 + rho * starts / n
        return result
    raise ValueError("UNREGISTERED_ORACLE_LAW")


def _validate_map(probabilities, expected_keys=None):
    if not isinstance(probabilities, dict) or not probabilities:
        raise ValueError("NONEMPTY_COMPLETE_PAIR_MAP_REQUIRED")
    keys = set(probabilities)
    if any(not isinstance(pair, tuple) or len(pair) != 2
           or any(type(i) is not int for i in pair) or not 1 <= pair[0] < pair[1]
           for pair in keys):
        raise ValueError("ONE_BASED_ASCENDING_PAIR_KEYS_REQUIRED")
    n = max(i for pair in keys for i in pair)
    if keys != set(combinations(range(1, n + 1), 2)) or (expected_keys is not None and keys != expected_keys):
        raise ValueError("MATCHING_COMPLETE_PAIR_MAPS_REQUIRED")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in probabilities.values()):
        raise ValueError("FINITE_PAIR_PROBABILITIES_REQUIRED")
    return n, keys


def uniform_shrink(probabilities, n, k, alpha=SHRINK_ALPHA):
    """Return alpha*p+(1-alpha)*uniform solely as a calibration diagnostic.

    Strict ordering is preserved for alpha>0 in exact arithmetic.  The
    original D2 must be carried through unchanged: applying the registered
    12-decimal rounding anew can change boundary tie groups.  This function
    deliberately does not choose a pair or register a new candidate.
    """
    _dimensions(n, k)
    map_n, _ = _validate_map(probabilities)
    if map_n != n:
        raise ValueError("PAIR_MAP_DIMENSION_MISMATCH")
    if (isinstance(alpha, bool) or not isinstance(alpha, (int, float))
            or not math.isfinite(alpha) or not 0.0 < alpha <= 1.0):
        raise ValueError("STRICTLY_POSITIVE_SHRINK_ALPHA_REQUIRED")
    p0 = _uniform_subset_probability(n, k, 2)
    return {pair: alpha * value + (1.0 - alpha) * p0 for pair, value in probabilities.items()}


def brier_decomposition(empirical, prior, truth, front, *, lam=MIXTURE_LAMBDA):
    """Exact pathwise and conditional-mean identities for one draw.

    Every mean is across pairs within ONE draw, never independent pair
    observations.  The martingale labels require truth=E[Y|past] under the
    synthetic generator; they do not assert independence between pairs.
    """
    n, keys = _validate_map(empirical)
    _validate_map(prior, keys)
    _validate_map(truth, keys)
    if (not isinstance(front, (list, tuple)) or len(set(front)) != len(front)
            or any(type(i) is not int or not 1 <= i <= n for i in front)):
        raise ValueError("LEGAL_REALIZED_FRONT_REQUIRED")
    if (isinstance(lam, bool) or not isinstance(lam, (int, float))
            or not math.isfinite(lam) or not 0.0 <= lam <= 1.0):
        raise ValueError("LEGAL_MIXTURE_WEIGHT_REQUIRED")
    k = len(front)
    pair_mass = math.comb(k, 2)
    for probabilities in (empirical, prior, truth):
        if not math.isclose(math.fsum(probabilities.values()), pair_mass, abs_tol=2e-8, rel_tol=2e-8):
            raise ValueError("FIXED_K_PAIR_MASS_REQUIRED")
    ordered = tuple(sorted(keys))
    m = len(ordered)
    realized = set(combinations(sorted(front), 2))
    y = {pair: float(pair in realized) for pair in ordered}
    uniform = dict.fromkeys(ordered, pair_mass / m)
    mixture = {pair: lam * empirical[pair] + (1.0 - lam) * prior[pair] for pair in ordered}
    mean = lambda values: math.fsum(values) / m
    mse = lambda p: mean((p[pair] - truth[pair]) ** 2 for pair in ordered)
    loss = lambda p: mean((p[pair] - y[pair]) ** 2 for pair in ordered)
    empirical_mse, prior_mse, mix_mse, uniform_mse = map(mse, (empirical, prior, mixture, uniform))
    cross = mean((empirical[pair] - truth[pair]) * (prior[pair] - truth[pair]) for pair in ordered)
    empirical_term = lam ** 2 * empirical_mse
    prior_term = (1.0 - lam) ** 2 * prior_mse
    cross_term = 2.0 * lam * (1.0 - lam) * cross
    oracle_brier, empirical_brier, prior_brier, mix_brier, uniform_brier = map(
        loss, (truth, empirical, prior, mixture, uniform))
    oracle_martingale = 2.0 * mean((mixture[pair] - truth[pair]) * (truth[pair] - y[pair]) for pair in ordered)
    uniform_martingale = 2.0 * mean((mixture[pair] - uniform[pair]) * (truth[pair] - y[pair]) for pair in ordered)
    return {
        "empirical_mse": empirical_mse, "prior_mse": prior_mse,
        "error_cross_mean": cross, "mix_mse": mix_mse,
        "mix_mse_empirical_term": empirical_term, "mix_mse_prior_term": prior_term,
        "mix_mse_cross_term": cross_term,
        "mix_mse_identity_residual": mix_mse - empirical_term - prior_term - cross_term,
        "oracle_expected_brier": mean(truth[pair] * (1.0 - truth[pair]) for pair in ordered),
        "oracle_brier": oracle_brier, "empirical_brier": empirical_brier,
        "prior_brier": prior_brier, "mix_brier": mix_brier,
        "uniform_brier": uniform_brier, "uniform_mse": uniform_mse,
        "mix_oracle_realized_excess": mix_brier - oracle_brier,
        "mix_oracle_expected_excess": mix_mse,
        "mix_oracle_martingale_term": oracle_martingale,
        "mix_oracle_identity_residual": mix_brier - oracle_brier - mix_mse - oracle_martingale,
        "mix_uniform_realized_excess": mix_brier - uniform_brier,
        "mix_uniform_expected_excess": mix_mse - uniform_mse,
        "mix_uniform_martingale_term": uniform_martingale,
        "mix_uniform_identity_residual": mix_brier - uniform_brier - mix_mse + uniform_mse - uniform_martingale,
    }


def _logadd(a, b):
    if a == -math.inf:
        return b
    if b == -math.inf:
        return a
    hi, lo = max(a, b), min(a, b)
    return hi + math.log1p(math.exp(lo - hi))


def _log_elementary(logweights, degree):
    coefficients = [0.0] + [-math.inf] * degree
    for seen, value in enumerate(logweights, 1):
        for d in range(min(seen, degree), 0, -1):
            coefficients[d] = _logadd(coefficients[d], value + coefficients[d - 1])
    return coefficients


def _marginals(logweights, k):
    z = _log_elementary(logweights, k)[k]
    return [math.exp(min(0.0, logweights[i] + _log_elementary(
        logweights[:i] + logweights[i + 1:], k - 1)[k - 1] - z))
        for i in range(len(logweights))]


def fit_moment_matched_cb(target_marginals, k, *, maxiter=MOMENT_MAXITER,
                          tol=MOMENT_TOLERANCE):
    """Fit fixed-k product weights by deterministic cyclic odds scaling.

    Targets must be strictly interior and sum to k.  Each coordinate update
    exactly matches that marginal holding the other weights fixed.  One
    iteration is a complete ascending-number sweep, followed by a maximum
    marginal error check.  The gauge is centered after each sweep.  There is
    no restart, retuning, or success fallback on nonconvergence.  The fixed
    study uses maxiter=200 and tol=1e-9; optional arguments support small
    numerical unit tests, not experiment selection.
    """
    if not isinstance(target_marginals, (list, tuple)):
        raise ValueError("INTERIOR_MARGINAL_LIST_REQUIRED")
    n = len(target_marginals)
    _dimensions(n, k)
    if not 0 < k < n:
        raise ValueError("INTERIOR_FIXED_K_REQUIRED")
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or not 0.0 < p < 1.0 for p in target_marginals):
        raise ValueError("STRICTLY_INTERIOR_FINITE_MARGINALS_REQUIRED")
    target = [float(p) for p in target_marginals]
    if not math.isclose(math.fsum(target), k, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("TARGET_MARGINAL_SUM_MUST_EQUAL_K")
    if type(maxiter) is not int or maxiter < 1:
        raise ValueError("POSITIVE_INTEGER_MAXITER_REQUIRED")
    if (isinstance(tol, bool) or not isinstance(tol, (int, float))
            or not math.isfinite(tol) or tol <= 0.0):
        raise ValueError("POSITIVE_FINITE_TOLERANCE_REQUIRED")
    # Start from the original surrogate, to measure the same target mismatch.
    logweights = [math.log(p) - math.log1p(-p) for p in target]
    marginal = _marginals(logweights, k)
    initial_error = max(abs(a - b) for a, b in zip(marginal, target))
    error = initial_error
    iterations = 0
    while iterations < maxiter and error > tol:
        for i, p in enumerate(target):
            excluded = _log_elementary(logweights[:i] + logweights[i + 1:], k)
            # w_i <- w_i * odds(target_i)/odds(current_i), computed without
            # subtracting a rounded current_i from one.
            logweights[i] = math.log(p) - math.log1p(-p) + excluded[k] - excluded[k - 1]
        center = math.fsum(logweights) / n
        logweights = [value - center for value in logweights]
        iterations += 1
        marginal = _marginals(logweights, k)
        error = max(abs(a - b) for a, b in zip(marginal, target))
    # A scale-free log representation remains authoritative for extreme
    # targets.  Representable weights are supplied for ordinary shrunk inputs.
    peak = max(logweights)
    weights = [math.exp(value - peak) for value in logweights]
    if all(weight > 0.0 for weight in weights):
        probabilities = conditional_pair_probabilities(weights, k)
    else:
        z = _log_elementary(logweights, k)[k]
        probabilities = {}
        for i, j in combinations(range(n), 2):
            rest = [value for index, value in enumerate(logweights) if index != i and index != j]
            probabilities[i + 1, j + 1] = (0.0 if k < 2 else math.exp(min(0.0,
                logweights[i] + logweights[j] + _log_elementary(rest, k - 2)[k - 2] - z)))
        weights = None
    return {
        "weights": weights, "log_weights": logweights,
        "pair_probabilities": probabilities, "marginals": marginal,
        "target_marginals": target, "converged": error <= tol,
        "iterations": iterations, "max_abs_error": error,
        "initial_max_abs_error": initial_error,
        "maxiter": maxiter, "tolerance": tol,
        "algorithm": "CYCLIC_EXACT_COORDINATE_ODDS_SCALING_LOG_SPACE",
    }
