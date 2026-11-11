"""Exploratory inverse-formula fitting; NEVER a formal lottery forecast.

Fits every sorted ball position exactly with a finite-field Newton polynomial.
Its high degree exposes interpolation overfitting, not predictability.
No official V4.7 model identity, seed, freeze, or ledger is read or changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

PRIMES = (257, 65537)
MULTIPLIERS = (0, 1, 2, 3, 5)


@dataclass(frozen=True)
class Draw:
    issue: int
    front: tuple[int, ...]
    back: tuple[int, ...]


@dataclass(frozen=True)
class Game:
    name: str
    front_max: int
    front_pick: int
    back_max: int
    back_pick: int


SSQ = Game("SSQ", 33, 6, 16, 1)
DLT = Game("DLT", 35, 5, 12, 2)


def load_history(path: Path, game: Game) -> tuple[list[Draw], str]:
    raw = path.read_bytes()
    draws = []
    for record in raw.decode("utf-8").replace("\n", ";").split(";"):
        record = record.strip()
        if not record:
            continue
        issue, ticket = record.split(":", 1)
        front, back = ticket.split("+", 1)
        if (not issue.isdecimal() or len(front) != 2 * game.front_pick
                or len(back) != 2 * game.back_pick):
            raise ValueError("invalid historical row")
        a = tuple(int(front[i:i+2]) for i in range(0, len(front), 2))
        b = tuple(int(back[i:i+2]) for i in range(0, len(back), 2))
        if (a != tuple(sorted(set(a))) or b != tuple(sorted(set(b)))
                or not all(1 <= x <= game.front_max for x in a)
                or not all(1 <= x <= game.back_max for x in b)):
            raise ValueError(f"invalid ticket in issue {issue}")
        draws.append(Draw(int(issue), a, b))
    draws.sort(key=lambda x: x.issue)
    if len(draws) < 90 or any(draws[i].issue != draws[i-1].issue + 1 for i in range(1, len(draws))):
        raise ValueError("need at least 90 unique contiguous historical issues")
    return draws, hashlib.sha256(raw).hexdigest()


def newton_coefficients(values: list[int], prime: int) -> tuple[int, ...]:
    """Exact interpolation over GF(prime) at integer nodes 0..n-1."""
    if len(values) >= prime:
        raise ValueError("field must have more elements than training points")
    coef = values.copy()
    for order in range(1, len(coef)):
        for i in range(len(coef)-1, order-1, -1):
            coef[i] = ((coef[i] - coef[i-1]) * pow(order, -1, prime)) % prime
    return tuple(coef)


def evaluate(coef: tuple[int, ...], x: int, prime: int, multiplier: int = 0) -> int:
    y = coef[-1]
    for i in range(len(coef)-2, -1, -1):
        y = (y * (x-i) + coef[i]) % prime
    # Infinitely many formulas agree on the training nodes; changing this
    # parameter changes predictions without changing a single training fit.
    vanishes = 1
    for i in range(len(coef)):
        vanishes = vanishes * (x-i) % prime
    return (y + multiplier * vanishes) % prime


def normalize(values: list[int], maximum: int) -> tuple[int, ...]:
    """Map polynomial output to a legal unique ticket, without outcome access."""
    chosen = set()
    for value in values:
        n = (value - 1) % maximum + 1
        while n in chosen:
            n = n % maximum + 1
        chosen.add(n)
    return tuple(sorted(chosen))


class Formula:
    def __init__(self, training: list[Draw], game: Game, prime: int, multiplier: int):
        self.game, self.prime, self.multiplier = game, prime, multiplier
        self.n = len(training)
        self.front_coefs = [newton_coefficients([d.front[i] for d in training], prime)
                            for i in range(game.front_pick)]
        self.back_coefs = [newton_coefficients([d.back[i] for d in training], prime)
                           for i in range(game.back_pick)]

    def predict(self, x: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
        front = normalize([evaluate(c, x, self.prime, self.multiplier)
                           for c in self.front_coefs], self.game.front_max)
        back = normalize([evaluate(c, x, self.prime, self.multiplier)
                          for c in self.back_coefs], self.game.back_max)
        return front, back


def compare(pred: tuple[tuple[int, ...], tuple[int, ...]], actual: Draw) -> dict[str, int]:
    a, b = pred
    f = len(set(a) & set(actual.front))
    h = len(set(b) & set(actual.back))
    return {"full": int(a == actual.front and b == actual.back),
            "d2": int(set(a[:2]).issubset(actual.front)),
            "front_hits": f, "back_hits": h}


def evaluate_formula(training: list[Draw], test: list[Draw], game: Game,
                     prime: int, multiplier: int) -> dict:
    model = Formula(training, game, prime, multiplier)
    training_stats = [compare(model.predict(i), row) for i, row in enumerate(training)]
    test_stats = [compare(model.predict(len(training)+i), row) for i, row in enumerate(test)]
    return {"prime": prime, "vanishing_multiplier": multiplier,
            "train_exact": sum(x["full"] for x in training_stats),
            "test_exact": sum(x["full"] for x in test_stats),
            "test_d2": sum(x["d2"] for x in test_stats),
            "test_front_hits": sum(x["front_hits"] for x in test_stats),
            "test_back_hits": sum(x["back_hits"] for x in test_stats),
            "old_fit_extrapolation_after_holdout": model.predict(len(training)+len(test))}


def experiment(path: Path, game: Game) -> dict:
    all_draws, sha = load_history(path, game)
    window = all_draws[-90:]
    training, holdout = window[:60], window[60:]
    trials = [evaluate_formula(training, holdout, game, p, k)
              for p in PRIMES for k in MULTIPLIERS]
    # Independent research control, seeded per issue, no official NULL identity.
    control = {"test_exact": 0, "test_d2": 0, "test_front_hits": 0, "test_back_hits": 0}
    for d in holdout:
        rng = random.Random(20261111 + d.issue)
        pick = (tuple(sorted(rng.sample(range(1, game.front_max+1), game.front_pick))),
                tuple(sorted(rng.sample(range(1, game.back_max+1), game.back_pick))))
        for key, value in compare(pick, d).items():
            control["test_" + key if key != "full" else "test_exact"] += value
    return {"game": game.name, "source_sha256": sha,
            "source_scope": "third-party DLT / official regional SSQ; not full formal source authentication",
            "train_issues": [training[0].issue, training[-1].issue],
            "holdout_issues": [holdout[0].issue, holdout[-1].issue],
            "train_size": 60, "holdout_size": 30,
            "theoretical_d2": (game.front_pick * (game.front_pick - 1)) /
                              (game.front_max * (game.front_max - 1)),
            "formulas": trials, "null_research": control,
            "asof_issue": all_draws[-1].issue, "target_issue": all_draws[-1].issue + 1,
            "future_research_from_all_history": {
                "interpolant_65537_k0": Formula(all_draws, game, 65537, 0).predict(len(all_draws)),
                "interpolant_65537_k1": Formula(all_draws, game, 65537, 1).predict(len(all_draws)),
            },
            "status": "EXPLORATORY_ONLY_NO_EDGE"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssq", type=Path, default=Path(__file__).with_name("ssq_2026.txt"))
    parser.add_argument("--dlt", type=Path, default=Path(__file__).with_name("dlt_2026.txt"))
    args = parser.parse_args()
    print(json.dumps({"experiments": [experiment(args.ssq, SSQ), experiment(args.dlt, DLT)]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
