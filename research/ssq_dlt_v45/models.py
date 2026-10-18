"""Isolated, deterministic V4.5 research producers. Never formal M04--M07.

These algorithms make no claim of predictive edge. History has to be admitted
by the source/as-of layer before calling generate; this module only validates
numbers and issue ordering. A local SHA is not a trusted pre-draw timestamp.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from types import MappingProxyType


class ModelBlocked(ValueError):
    """Malformed input or an attempted replacement of the research registry."""


RULES = MappingProxyType({"SSQ": (33, 6, 16, 1), "DLT": (35, 5, 12, 2)})
NULL_MODEL = "R45-RANDOM-NULL"
PRIMARY_MODEL = "R45-PAIRWISE-D2"
DEFAULT_SEED = 20261018
_SPECS = (
    ("R45-HOT60", "1.0.0", "Last 60 draws, frequency, ascending-number ties"),
    ("R45-EWMA", "1.0.0", "All supplied draws, half-life 20 draws, ascending-number ties"),
    ("R45-SHRINKMIX", "1.0.0", "Half Hot60 and half EWMA, each shrunk by 20 uniform pseudo-draws"),
    ("R45-PAIRWISE-D2", "1.0.0", "D2 maximizes last-60 pair count then marginal sum; other Dk use Hot60"),
    (NULL_MODEL, "1.0.0", "SHA256-domain-separated Python MT19937 sample, independent stream per k and zone"),
)
MODEL_VERSIONS = MappingProxyType({key: version for key, version, _ in _SPECS})


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ModelBlocked("NON_CANONICAL_JSON") from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def registry() -> dict:
    """Fresh copy: caller mutations cannot change the fixed registry."""
    return {
        "schema": "ssq-dlt-v45-research-registry-1",
        "scope": "RESEARCH_ONLY",
        "models": {key: {"version": version, "algorithm": algorithm}
                   for key, version, algorithm in _SPECS},
        "primary_model": PRIMARY_MODEL,
        "null_model": NULL_MODEL,
        "default_seed": DEFAULT_SEED,
        "ticket_policy": "Contains that model's fixed D2, fills from its front ranking; back uses that model's marginal ranking",
        "random_domain": "JSON [seed, game, issue, model, zone, k] -> SHA256 -> MT19937; no outcome-dependent reseeding",
        "formal_aliases": False,
    }


REGISTRY_SHA256 = digest(registry())


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate_numbers(value: object, count: int, upper: int) -> None:
    if (type(value) is not list or len(value) != count
            or any(type(n) is not int or not 1 <= n <= upper for n in value)
            or len(set(value)) != count):
        raise ModelBlocked("INVALID_NUMBERS")


def _issue(value: object, *, allow_unassigned: bool = False) -> int | None:
    if allow_unassigned and value == "UNASSIGNED":
        return None
    if (type(value) is not str or not value or not value.isascii()
            or not value.isdigit() or int(value) <= 0):
        raise ModelBlocked("NUMERIC_ISSUE_REQUIRED")
    return int(value)


def validate_history(game: str, issue: str, history: list[dict]) -> list[dict]:
    if type(game) is not str or game not in RULES:
        raise ModelBlocked("UNKNOWN_GAME")
    target = _issue(issue, allow_unassigned=True)
    if type(history) is not list:
        raise ModelBlocked("HISTORY_LIST_REQUIRED")
    front_upper, front_count, back_upper, back_count = RULES[game]
    previous = 0
    width = None if target is None else len(issue)
    for row in history:
        if type(row) is not dict or row.get("game") != game:
            raise ModelBlocked("HISTORY_GAME_MISMATCH")
        number = _issue(row.get("issue"))
        if width is None:
            width = len(row["issue"])
        if len(row["issue"]) != width or number <= previous:
            raise ModelBlocked("DUPLICATE_OR_UNSORTED_HISTORY")
        if target is not None and number >= target:
            raise ModelBlocked("F01_FUTURE_OR_TARGET_DRAW_IN_HISTORY")
        validate_numbers(row.get("front"), front_count, front_upper)
        validate_numbers(row.get("back"), back_count, back_upper)
        previous = number
    return history


def _scores(history: list[dict], zone: str, upper: int, count: int) -> dict[str, list[float]]:
    recent = history[-60:]
    hot = [0.0] * (upper + 1)
    ewma = [0.0] * (upper + 1)
    for row in recent:
        for number in row[zone]:
            hot[number] += 1
    total_weight = 0.0
    for age, row in enumerate(reversed(history)):
        weight = 2.0 ** (-age / 20.0)
        total_weight += weight
        for number in row[zone]:
            ewma[number] += weight
    prior = 20.0 * count / upper
    mix = [0.0] + [0.5 * (hot[n] + prior) / (len(recent) + 20.0)
                   + 0.5 * (ewma[n] + prior) / (total_weight + 20.0)
                   for n in range(1, upper + 1)]
    return {"R45-HOT60": hot, "R45-EWMA": ewma,
            "R45-SHRINKMIX": mix, "R45-PAIRWISE-D2": hot}


def _ranking(scores: list[float], upper: int) -> list[int]:
    return sorted(range(1, upper + 1), key=lambda number: (-scores[number], number))


def _sample(seed: int, game: str, issue: str, model: str,
            zone: str, k: int, upper: int) -> list[int]:
    encoded = canonical_bytes([seed, game, issue, model, zone, k])
    integer = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
    return random.Random(integer).sample(range(1, upper + 1), k)


def _best_pair(history: list[dict], scores: list[float], upper: int) -> list[int]:
    pairs = Counter(pair for row in history[-60:]
                    for pair in itertools.combinations(sorted(row["front"]), 2))
    # Pairwise D2 is selected directly; it is not a slice of a five-number rank.
    best = min(itertools.combinations(range(1, upper + 1), 2),
               key=lambda pair: (-pairs[pair], -sum(scores[n] for n in pair), pair))
    return list(best)


def generate(game: str, issue: str, history: list[dict], seed: int = DEFAULT_SEED) -> dict:
    """Generate separate D1--D5 sets, one pre-fixed D2 and legal single tickets.

    UNASSIGNED produces an explicitly untargeted preview when the official next
    issue cannot be verified. It cannot enter prospective competition.
    """
    validate_history(game, issue, history)
    if type(seed) is not int or seed < 0:
        raise ModelBlocked("NONNEGATIVE_INTEGER_SEED_REQUIRED")
    front_upper, front_count, back_upper, back_count = RULES[game]
    front_scores = _scores(history, "front", front_upper, front_count)
    back_scores = _scores(history, "back", back_upper, back_count)
    models = {}
    for model, version in MODEL_VERSIONS.items():
        if model == NULL_MODEL:
            dan = {str(k): sorted(_sample(seed, game, issue, model, "dan", k, front_upper))
                   for k in range(1, 6)}
            front_rank = _sample(seed, game, issue, model, "ticket_front", front_upper, front_upper)
            back = sorted(_sample(seed, game, issue, model, "ticket_back", back_count, back_upper))
        else:
            front_rank = _ranking(front_scores[model], front_upper)
            dan = {str(k): sorted(front_rank[:k]) for k in range(1, 6)}
            if model == PRIMARY_MODEL:
                dan["2"] = _best_pair(history, front_scores[model], front_upper)
            back = sorted(_ranking(back_scores[model], back_upper)[:back_count])
        front = list(dan["2"])
        front.extend(n for n in front_rank if n not in front)
        models[model] = {"version": version, "dan": dan,
                         "primary_d2": list(dan["2"]),
                         "ticket": {"front": sorted(front[:front_count]), "back": back}}
    result = {"schema": "ssq-dlt-v45-research-prediction-1", "game": game, "issue": issue,
              "target_status": "UNASSIGNED_PREVIEW" if issue == "UNASSIGNED" else "CALLER_TARGET_REQUIRES_OFFICIAL_ADMISSION",
              "seed": seed, "history_size": len(history),
              "history_sha256": digest(history), "registry_sha256": REGISTRY_SHA256,
              "model_source_sha256": source_sha256(), "models": models,
              "primary_model": PRIMARY_MODEL,
              "primary_d2": list(models[PRIMARY_MODEL]["primary_d2"]),
              "admission": "RESEARCH_ONLY", "formal_A": 0, "decision": "NO_EDGE"}
    validate_prediction(result)
    return result


def validate_prediction(value: object) -> None:
    """Validate fixed identities and explicit Dk/ticket contracts, without admission."""
    if (type(value) is not dict or type(value.get("game")) is not str
            or value["game"] not in RULES):
        raise ModelBlocked("INVALID_PREDICTION_GAME")
    _issue(value.get("issue"), allow_unassigned=True)
    if (value.get("schema") != "ssq-dlt-v45-research-prediction-1"
            or type(value.get("seed")) is not int or value["seed"] < 0
            or type(value.get("history_size")) is not int or value["history_size"] < 0
            or type(value.get("history_sha256")) is not str
            or len(value["history_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in value["history_sha256"])
            or value.get("model_source_sha256") != source_sha256()):
        raise ModelBlocked("MODEL_SOURCE_OR_REPRODUCIBILITY_METADATA_MISMATCH")
    if (value.get("registry_sha256") != REGISTRY_SHA256
            or value.get("primary_model") != PRIMARY_MODEL
            or type(value.get("models")) is not dict
            or set(value["models"]) != set(MODEL_VERSIONS)):
        raise ModelBlocked("RESEARCH_REGISTRY_OR_PRIMARY_REPLACED")
    if (value.get("admission") != "RESEARCH_ONLY" or type(value.get("formal_A")) is not int
            or value["formal_A"] != 0 or value.get("decision") != "NO_EDGE"):
        raise ModelBlocked("RESEARCH_CANNOT_PROMOTE_FORMAL_OR_EDGE")
    front_upper, front_count, back_upper, back_count = RULES[value["game"]]
    for model, version in MODEL_VERSIONS.items():
        candidate = value["models"][model]
        if (type(candidate) is not dict or candidate.get("version") != version
                or type(candidate.get("dan")) is not dict
                or set(candidate["dan"]) != {str(k) for k in range(1, 6)}):
            raise ModelBlocked("MODEL_VERSION_OR_D1_D5_MISMATCH")
        for k in range(1, 6):
            validate_numbers(candidate["dan"][str(k)], k, front_upper)
        validate_numbers(candidate.get("primary_d2"), 2, front_upper)
        if candidate["primary_d2"] != candidate["dan"]["2"]:
            raise ModelBlocked("POST_HOC_PRIMARY_D2_REPLACED")
        ticket = candidate.get("ticket")
        if type(ticket) is not dict:
            raise ModelBlocked("LEGAL_SINGLE_TICKET_REQUIRED")
        validate_numbers(ticket.get("front"), front_count, front_upper)
        validate_numbers(ticket.get("back"), back_count, back_upper)
        if not set(candidate["primary_d2"]).issubset(ticket["front"]):
            raise ModelBlocked("TICKET_MUST_CONTAIN_REGISTERED_D2")
    if value.get("primary_d2") != value["models"][PRIMARY_MODEL]["primary_d2"]:
        raise ModelBlocked("POST_HOC_GLOBAL_PRIMARY_REPLACED")
