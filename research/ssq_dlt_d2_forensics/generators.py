"""New fixed-seed mechanism controls, isolated from the retained V46 failure.

These are synthetic laws, not lottery outcomes or predictive evidence.  The
three new generator paths do not use forecasts or fitted probabilities. The
legacy path deliberately calls the frozen tilted-draw helper, without reading
old stream outcomes or changing its specification.
The four negative laws are uniform fixed-cardinality sets by construction;
hash-derived pseudorandom streams are reproducible implementations, not a claim
of physical randomness or a proof that finite seeds are statistically typical.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date, timedelta


ROOT_SEED = 2026101921
DOMAIN = "FORENSICS_D2_CALIBRATION_V1"
NEGATIVE_SCENARIOS = ("MT_DIRECT", "SHA256_DIRECT", "SPLIT_SCRAMBLED_PAIR",
                      "LEGACY_SHARED_SCRAMBLE")
POSITIVE_SCENARIOS = ("MARGINAL_STRONG", "PAIR_STRONG", "RING_PERSISTENT")
SCENARIOS = NEGATIVE_SCENARIOS + POSITIVE_SCENARIOS
RULES = {"SSQ": (33, 6, 16, 1), "DLT": (35, 5, 12, 2)}
PAIR_ODDS_RATIO = 8
MARGINAL_WEIGHT = 3
RING_MIXTURE_PROBABILITY = 0.25


def stream_seed(game: str, scenario: str, replication: int, component: str,
                index: int | None = None, *, root_seed: int = ROOT_SEED) -> int:
    """SHA256 domain separation; requested total length is never in the seed."""
    if game not in RULES or scenario not in SCENARIOS:
        raise ValueError("REGISTERED_GAME_AND_SCENARIO_REQUIRED")
    if type(replication) is not int or replication < 0:
        raise ValueError("NONNEGATIVE_REPLICATION_REQUIRED")
    if type(component) is not str or not component:
        raise ValueError("NONEMPTY_COMPONENT_REQUIRED")
    if index is not None and (type(index) is not int or index < 0):
        raise ValueError("NONNEGATIVE_INDEX_REQUIRED")
    if type(root_seed) is not int:
        raise ValueError("INTEGER_ROOT_SEED_REQUIRED")
    payload = [DOMAIN, root_seed, game, scenario, replication, component, index]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest(), "big")


class SHA256CounterRNG:
    """Counter-mode digest words and rejection randbelow, without modulo bias.

    Blocks are SHA256(domain || seed-as-32-bytes || counter-as-16-bytes).
    Every randbelow consumes whole independent counter blocks; the accepted
    interval has length divisible by the requested bound.
    """

    def __init__(self, seed: int):
        if type(seed) is not int or not 0 <= seed < 1 << 256:
            raise ValueError("UNSIGNED_256_BIT_SEED_REQUIRED")
        self.seed = seed.to_bytes(32, "big")
        self.counter = 0

    def _word(self) -> int:
        if self.counter >= 1 << 128:
            raise OverflowError("SHA256_COUNTER_EXHAUSTED")
        raw = b"FORENSICS_SHA256_WORD_V1\x00" + self.seed + self.counter.to_bytes(16, "big")
        self.counter += 1
        return int.from_bytes(hashlib.sha256(raw).digest(), "big")

    def randbelow(self, upper: int) -> int:
        if type(upper) is not int or not 1 <= upper <= 1 << 256:
            raise ValueError("POSITIVE_AT_MOST_256_BIT_BOUND_REQUIRED")
        if upper == 1:
            return 0
        space = 1 << 256
        limit = space - space % upper
        while True:
            word = self._word()
            if word < limit:
                return word % upper


def _fisher_yates_subset(rng, n: int, k: int) -> list[int]:
    """Uniform fixed-k subset from partial Fisher-Yates and unbiased randbelow."""
    if type(n) is not int or type(k) is not int or not 0 <= k <= n:
        raise ValueError("LEGAL_INTEGER_CARDINALITY_REQUIRED")
    population = list(range(1, n + 1))
    for index in range(k):
        other = index + rng.randbelow(n - index)
        population[index], population[other] = population[other], population[index]
    return sorted(population[:k])


def _choose(n: int, k: int) -> int:
    return math.comb(n, k) if 0 <= k <= n else 0


def _group_weighted_subset(rng, n: int, k: int, pair: tuple[int, int],
                           group_weights: tuple[int, int, int]) -> list[int]:
    """Exact integer law, P(S) proportional to weight[|S intersect pair|].

    C(2,a)*C(n-2,k-a) counts the sets in group a.  Integer randrange
    chooses the group with exactly its total weight; samples within groups
    are uniform.  This does not use the original conditional sampler or
    reject-until-miss pair-tilt implementation.
    """
    if (type(n) is not int or type(k) is not int or not 2 <= n or not 0 <= k <= n
            or len(pair) != 2 or len(set(pair)) != 2
            or any(type(x) is not int or not 1 <= x <= n for x in pair)
            or len(group_weights) != 3
            or any(type(w) is not int or w <= 0 for w in group_weights)):
        raise ValueError("LEGAL_PAIR_CARDINALITY_AND_POSITIVE_INTEGER_WEIGHTS_REQUIRED")
    masses = [_choose(2, a) * _choose(n - 2, k - a) * group_weights[a]
              for a in range(3)]
    choice = rng.randrange(sum(masses))
    for a, mass in enumerate(masses):
        if choice < mass:
            others = [x for x in range(1, n + 1) if x not in pair]
            return sorted(rng.sample(list(pair), a) + rng.sample(others, k - a))
        choice -= mass
    raise AssertionError("WEIGHTED_GROUP_UNREACHABLE")


def _relabel(front: list[int], permutation: list[int]) -> list[int]:
    return sorted(permutation[number - 1] for number in front)


def synthetic_history(game: str, scenario: str, replication: int, *,
                      warmup: int = 240, evaluation_draws: int = 240,
                      root_seed: int = ROOT_SEED) -> tuple[list[dict], dict]:
    """Return (legal synthetic history, law metadata) for a new frozen stream.

    The caller fixes stream roster and lengths before analysis.  Parameters
    enable tiny unit tests and prefix checks, not outcome-driven extension.
    Split-scrambled latent draws and per-draw permutations use disjoint
    component domains.  Positive controls also have separate scenario domains.
    """
    if (type(warmup) is not int or warmup < 0
            or type(evaluation_draws) is not int or evaluation_draws < 0):
        raise ValueError("NONNEGATIVE_INTEGER_LENGTHS_REQUIRED")
    seed = stream_seed(game, scenario, replication, "FRONT", root_seed=root_seed)
    n, k, _, bk = RULES[game]
    direct_rng = random.Random(seed)
    sha_rng = SHA256CounterRNG(seed)
    latent_seed = stream_seed(game, scenario, replication, "LATENT_PAIR", root_seed=root_seed)
    latent_rng = random.Random(latent_seed)
    ring_seed = stream_seed(game, scenario, replication, "FIXED_RING", root_seed=root_seed)
    ring = random.Random(ring_seed).sample(range(1, n + 1), n) if scenario == "RING_PERSISTENT" else None
    if scenario == "LEGACY_SHARED_SCRAMBLE":
        # Exact old control flow, including the initial unused ring sample.
        # Only this new study's seed/domain changes.  Do not edit old SPEC.
        from research.ssq_dlt_d2_next.simulation import tilted_uniform
        direct_rng.sample(range(1, n + 1), n)
    pair = (1, 2)
    rows = []
    for index in range(warmup + evaluation_draws):
        if scenario == "MT_DIRECT":
            front = sorted(direct_rng.sample(range(1, n + 1), k))
        elif scenario == "SHA256_DIRECT":
            front = _fisher_yates_subset(sha_rng, n, k)
        elif scenario == "SPLIT_SCRAMBLED_PAIR":
            latent = _group_weighted_subset(latent_rng, n, k, pair, (1, 1, PAIR_ODDS_RATIO))
            permutation_seed = stream_seed(game, scenario, replication, "PERMUTATION", index,
                                           root_seed=root_seed)
            permutation = random.Random(permutation_seed).sample(range(1, n + 1), n)
            front = _relabel(latent, permutation)
        elif scenario == "LEGACY_SHARED_SCRAMBLE":
            latent = tilted_uniform(direct_rng, n, k, list(pair), PAIR_ODDS_RATIO)
            permutation = direct_rng.sample(range(1, n + 1), n)
            front = _relabel(latent, permutation)
        elif scenario == "MARGINAL_STRONG":
            front = _group_weighted_subset(direct_rng, n, k, pair,
                                           (1, MARGINAL_WEIGHT, MARGINAL_WEIGHT ** 2))
        elif scenario == "PAIR_STRONG":
            front = _group_weighted_subset(direct_rng, n, k, pair, (1, 1, PAIR_ODDS_RATIO))
        elif scenario == "RING_PERSISTENT":
            if direct_rng.random() < RING_MIXTURE_PROBABILITY:
                start = direct_rng.randrange(n)
                front = sorted(ring[(start + j) % n] for j in range(k))
            else:
                front = sorted(direct_rng.sample(range(1, n + 1), k))
        else:
            raise AssertionError("VALIDATED_SCENARIO_UNREACHABLE")
        rows.append({"game": game,
                     "issue": f"{index + 1:07d}" if game == "SSQ" else f"{index + 1:05d}",
                     "draw_date": (date(2000, 1, 1) + timedelta(days=index)).isoformat(),
                     "front": front, "back": list(range(1, bk + 1))})
    metadata = {
        "law": "UNIFORM" if scenario in NEGATIVE_SCENARIOS else scenario,
        "scenario": scenario, "n": n, "k": k, "favoured_pair": list(pair),
        "ring": ring, "rho": RING_MIXTURE_PROBABILITY,
        "marginal_weight": float(MARGINAL_WEIGHT), "odds_ratio": float(PAIR_ODDS_RATIO),
        "root_seed": root_seed, "domain": DOMAIN, "stream_seed": seed,
        "seed_derivation": "SHA256(JSON [domain,root_seed,game,scenario,replication,component,index]); no length in domain",
        "components": {"front": seed, "latent_pair": latent_seed, "fixed_ring": ring_seed},
        "permutation_domain": (
            "PERMUTATION with the absolute zero-based row index; independent of LATENT_PAIR"
            if scenario == "SPLIT_SCRAMBLED_PAIR" else
            "FRONT shared mutable MT RNG after original unused ring initialization and tilted draw"
            if scenario == "LEGACY_SHARED_SCRAMBLE" else "NOT_USED"),
        "legacy_shared_rng": scenario == "LEGACY_SHARED_SCRAMBLE",
        "legacy_initial_unused_ring_sample": scenario == "LEGACY_SHARED_SCRAMBLE",
        "legacy_seed_policy": "New FORENSICS root/domain; old simulation SPEC and seed never changed",
        "scope": "SYNTHETIC_MECHANISM_CONTROL_ONLY_NOT_LOTTERY_EVIDENCE",
    }
    return rows, metadata
