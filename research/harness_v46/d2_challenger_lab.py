"""V4.7 isolated D2 challenger laboratory. RETROSPECTIVE / SHADOW ONLY.

This does not alter any registered 6-model forecast, original 8 formal slots,
negative-control seed, frozen prediction, or official D2 protocol. A candidate
picked from known history has *no established* ability to beat fair draws.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from functools import lru_cache
from itertools import combinations
from math import sqrt
from pathlib import Path

from . import core, statistics
from .statistics import clopper_pearson, exact_binomial_upper_tail

CHALLENGER_ID = "RECENCY_PAIR_H45_120_V1"
WINDOW = 120
HALF_LIFE = 45

def challenger_contract_sha256() -> str:
    """Fixed identity, including implementation bytes; not a preregistration."""
    return core.digest({
        "schema": "V47-EXPERIMENTAL-D2-CONTRACT-1",
        "id": CHALLENGER_ID,
        "window": WINDOW,
        "half_life_draws": HALF_LIFE,
        "rank": "descending_exponentially_weighted_pair_occurrences_then_lex",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixed_null_seed_id": core.NULL_SEED,
    })


def pick_recency_pair(history: list[dict], game: str) -> list[int]:
    """One fixed research pair, chosen solely from the preceding 120 draws.

    Weights 2**(-age_in_draws/45). It is a hypothesis rather than a
    calibrated posterior probability or an established predictive edge.
    """
    if game not in core.RULES:
        raise core.GateError("D2_CHALLENGER_UNKNOWN_LOTTERY")
    if not isinstance(history, list) or len(history) < WINDOW:
        raise core.GateError("D2_CHALLENGER_WARMUP_120_REQUIRED")
    pool = core.RULES[game]["pool"]
    size = core.RULES[game]["front"]
    weighted = Counter()
    for age, draw in enumerate(reversed(history[-WINDOW:])):
        if not isinstance(draw, dict):
            raise core.GateError("D2_CHALLENGER_INVALID_TRAINING_DRAW")
        core._balls(draw.get("front"), pool, size)
        weight = 2.0 ** (-age / HALF_LIFE)
        for pair in combinations(draw["front"], 2):
            weighted[pair] += weight
    best = min(combinations(range(1, pool + 1), 2),
               key=lambda pair: (-weighted[pair], pair))
    return list(best)


def _exact_statistics(rows: list[dict], game: str) -> dict:
    subset = [r for r in rows if r["lottery"] == game]
    n = len(subset)
    c = sum(r["d2_hits"]["challenger"] for r in subset)
    p = sum(r["d2_hits"]["pairwise_d2"] for r in subset)
    null = sum(r["d2_hits"]["random_null"] for r in subset)
    wins = sum(r["d2_hits"]["challenger"] == 1
               and r["d2_hits"]["random_null"] == 0 for r in subset)
    losses = sum(r["d2_hits"]["challenger"] == 0
                 and r["d2_hits"]["random_null"] == 1 for r in subset)
    fair = core.RULES[game]["d2"]
    return {
        "n": n, "challenger_hits": c, "challenger_rate": c / n,
        "pairwise_d2_hits": p, "random_null_hits": null,
        "random_null_rate": null / n, "fair_d2": fair,
        "challenger_minus_null_rate": (c - null) / n,
        "paired_wins": wins, "paired_losses": losses,
        "paired_p_unadjusted": exact_binomial_upper_tail(
            wins, wins + losses, 0.5) if wins + losses else 1.0,
        "fair_p_unadjusted": exact_binomial_upper_tail(c, n, fair),
        "challenger_ci95": list(clopper_pearson(c, n)),
        "registration": "NOT_PREREGISTERED",
        "hypothesis_test": "EXPLORATORY_UNADJUSTED_NOT_FOR_PROMOTION",
    }


def audit_walk_forward(bundle: dict) -> dict:
    """Expanding-origin contiguous retrospective audit; target labels never train themselves.

    For historical draw i, model uses only draw indices < i, and all prior
    publication timestamps MUST precede draw i's actual draw time.
    Does not certify that historical inputs or published timestamps are true.
    """
    if not isinstance(bundle, dict) or set(bundle) != set(core.RULES):
        raise core.GateError("EXACT_TWO_GAMES_REQUIRED")
    rows = []
    for game in ("SSQ", "DLT"):
        snapshot = bundle[game]
        if not isinstance(snapshot, dict) or snapshot.get("lottery") != game:
            raise core.GateError("D2_CHALLENGER_SNAPSHOT_GAME_MISMATCH")
        core.validate_study_snapshot(snapshot)
        history = snapshot["draws"]
        if len(history) <= WINDOW:
            raise core.GateError("D2_CHALLENGER_NO_HELDOUT_HISTORY")
        for i in range(WINDOW, len(history)):
            target = history[i]
            training = history[:i]
            drawn_at = core.dt(target["drawn_at"])
            if max(core.dt(d["published_at"]) for d in training) >= drawn_at:
                raise core.GateError("TRAINING_NOT_PUBLISHED_BEFORE_TEST_DRAW")
            pred = {
                "lottery": game, "draws": training, "target_issue": target["issue"],
            }
            pairs = {
                "challenger": pick_recency_pair(training, game),
                "pairwise_d2": core._model_ranking(pred, "pairwise_d2")[:2],
                "random_null": core._model_ranking(pred, "random_null")[:2],
            }
            actual = set(target["front"])
            rows.append({
                "lottery": game,
                "issue": str(target["issue"]),
                "draw_index": i,
                "max_training_published_at": max(d["published_at"] for d in training),
                "target_drawn_at": target["drawn_at"],
                "pairs": pairs,
                "d2_hits": {k: int(set(v).issubset(actual))
                            for k, v in pairs.items()},
            })
    return {
        "schema": "V47-D2-EXPLORATORY-WALKFORWARD-1",
        "model": CHALLENGER_ID,
        "challenger_contract_sha256": challenger_contract_sha256(),
        "fixed_null_seed_id": core.NULL_SEED,
        "input_bundle_sha256": core.digest(bundle),
        "evaluation_rows_sha256": core.digest(rows),
        "draws_by_game": {g: sum(r["lottery"] == g for r in rows)
                          for g in ("SSQ", "DLT")},
        "rows": rows,
        "exploratory_statistics": {
            g: _exact_statistics(rows, g) for g in ("SSQ", "DLT")
        },
        "data_provenance": "CALLER_SUPPLIED_UNVERIFIED_HISTORY",
        "evidence_class": "RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE",
        "qualified_prospective": False,
        "selection_and_multiple_testing": "NOT_PREREGISTERED_NO_PROMOTION",
        "historical_69_2880_negative_control": "UNRESOLVED_NOT_EXCLUDED",
        "formal_A": 0,
        "decision": "NO_EDGE",
        "limitations": [
            "Existing historical target labels were already exposed before the study; this is not future evidence.",
            "The candidate, pairwise, and NULL paths share unverified caller inputs.",
            "Official schedule completeness, publication truth, TSA, and independent result custody are not verified.",
            "No post-hoc window selection or retroactive replacement of the registered model is allowed.",
        ],
    }


# These diagnostics are a separate exploratory family, never formal producers.
ABLATION_ARMS = ("HOT30", "HOT60", "HOT120", "EWMA", "P-MARGIN",
                 "P-RESIDUAL", "P-COMBINED", "NULL")
ABLATION_SCOPES = ("train", "validation", "test", "all")
ABLATION_COMPARISONS = (
    ("P-COMBINED", "P-MARGIN"), ("P-COMBINED", "P-RESIDUAL"),
    ("P-RESIDUAL", "P-MARGIN"), ("HOT30", "HOT60"), ("HOT120", "HOT60"),
    ("EWMA", "HOT60"), ("P-MARGIN", "HOT60"), ("P-RESIDUAL", "HOT60"),
    ("P-COMBINED", "HOT60"),
)


def _ablation_contract() -> dict:
    """Fixed choices only: validation selects an arm, never a new parameter grid."""
    return {
        "schema": "V47-RECENCY-ABLATION-CONTRACT-1",
        "arms": list(ABLATION_ARMS), "warmup": 120,
        "split": "floor(.60*n_eval),floor(.80*n_eval);remaining_final_test",
        "hot_windows": [30, 60, 120],
        "ewma": {"window": 120, "decay": .92, "input_weight": .08},
        "pair": {"window": 120, "tau": 200,
                 "margin": "(count_a+count_b)/n",
                 "residual": "(pair_count-count_a*count_b*(k-1)/(n*k))/(n+200)",
                 "pair_tie_break": "lexicographic_ascending",
                 "filler": "HOT60_numeric_ascending_ties",
                 "combined": "unchanged_core_pairwise_d2"},
        "null_seed": core.NULL_SEED, "null_issue": "original_ASCII_issue_string",
        "core_parameters": json.loads(core.canon(core.PARAMETERS)),
        "lottery_rules": json.loads(core.canon(core.RULES)),
        "selection": "validation_D2_hits_descending_then_fixed_arm_order_without_NULL",
        "scopes": list(ABLATION_SCOPES),
        "comparisons": [list(pair) for pair in ABLATION_COMPARISONS],
        "joint_test": "max(exact_fair_upper_tail,exact_same_draw_NULL_paired_upper_tail)",
        "family": "EXPLICIT_128_EXPLORATORY_NOT_REGISTERED_FORMAL_FAMILY",
    }


def _validate_ablation_bundle(bundle: dict) -> dict:
    """Validate observed rows, without pretending an official calendar was supplied."""
    if not isinstance(bundle, dict) or set(bundle) != {"SSQ", "DLT"}:
        raise core.GateError("ABLATION_EXACT_TWO_GAMES_REQUIRED")
    splits = {}
    for game in ("SSQ", "DLT"):
        rows = bundle[game]
        if not isinstance(rows, list) or len(rows) < 125:
            raise core.GateError("ABLATION_AT_LEAST_125_OBSERVATIONS_REQUIRED")
        rules = core.RULES[game]
        previous_issue, previous_date = -1, None
        for row in rows:
            if (not isinstance(row, dict)
                    or set(row) != {"issue", "draw_date", "front", "back"}):
                raise core.GateError("ABLATION_DATE_ONLY_ROW_SCHEMA_REQUIRED")
            issue = row["issue"]
            if (not isinstance(issue, str) or not issue.isascii() or not issue.isdigit()
                    or int(issue) <= previous_issue):
                raise core.GateError("ABLATION_DUPLICATE_ALIAS_OR_UNORDERED_ISSUE")
            try:
                draw_date = date.fromisoformat(row["draw_date"])
            except (TypeError, ValueError) as exc:
                raise core.GateError("ABLATION_INVALID_DRAW_DATE") from exc
            if (draw_date.isoformat() != row["draw_date"]
                    or previous_date is not None and draw_date <= previous_date):
                raise core.GateError("ABLATION_NONCANONICAL_OR_UNORDERED_DATE")
            core._balls(row["front"], rules["pool"], rules["front"])
            core._balls(row["back"], rules["back_pool"], rules["back"])
            previous_issue, previous_date = int(issue), draw_date
        n = len(rows) - 120
        # Integer arithmetic avoids float rounding at larger cohort boundaries.
        train_end, validation_end = 120 + n * 3 // 5, 120 + n * 4 // 5
        if not 120 < train_end < validation_end < len(rows):
            raise core.GateError("ABLATION_EMPTY_SPLIT")
        splits[game] = {"warmup": [0, 120], "train": [120, train_end],
                        "validation": [train_end, validation_end],
                        "test": [validation_end, len(rows)], "all": [120, len(rows)]}
    return splits


def _ablation_rank_validated(history: list[dict], game: str, arm: str,
                             target_issue: str | None) -> list[int]:
    if arm in ("HOT30", "HOT60", "HOT120"):
        window = int(arm[3:])
        return core._rank(core._freq(history, window, core.RULES[game]["pool"]))
    snapshot = {"lottery": game, "draws": history, "target_issue": target_issue}
    incumbent = {"EWMA": "ewma", "P-COMBINED": "pairwise_d2", "NULL": "random_null"}
    if arm in incumbent:
        return core._model_ranking(snapshot, incumbent[arm])
    tail = history[-120:]
    n, k, pool = len(tail), core.RULES[game]["front"], core.RULES[game]["pool"]
    counts = Counter(ball for row in tail for ball in row["front"])
    pairs = Counter(pair for row in tail for pair in combinations(row["front"], 2))
    # Both component denominators are constant across pairs. Integer numerators
    # preserve exact mathematical ties for residual-only and marginal-only arms.
    def score(pair):
        a, b = pair
        if arm == "P-MARGIN":
            return counts[a] + counts[b]
        return pairs[pair] * n * k - counts[a] * counts[b] * (k - 1)
    best = min(combinations(range(1, pool + 1), 2), key=lambda p: (-score(p), p))
    hot = core._rank(core._freq(history, 60, pool))
    return list(best) + [ball for ball in hot if ball not in best]


def ablation_rank(history: list[dict], game: str, arm: str, *,
                  target_issue: str | None = None) -> list[int]:
    """Ordered full front ranking from prior rows only.

    NULL needs the actual target's original issue string; guessing the next issue
    or removing its leading zeros changes the registered deterministic control.
    """
    if not isinstance(game, str) or game not in core.RULES or arm not in ABLATION_ARMS:
        raise core.GateError("ABLATION_UNKNOWN_GAME_OR_ARM")
    if not isinstance(history, list) or len(history) < 120:
        raise core.GateError("ABLATION_WARMUP_120_REQUIRED")
    for row in history[-120:]:
        if not isinstance(row, dict):
            raise core.GateError("ABLATION_INVALID_TRAINING_ROW")
        core._balls(row.get("front"), core.RULES[game]["pool"], core.RULES[game]["front"])
    if arm == "NULL" and (not isinstance(target_issue, str)
                           or not target_issue.isascii() or not target_issue.isdigit()):
        raise core.GateError("ABLATION_NULL_REQUIRES_ORIGINAL_TARGET_ISSUE")
    return _ablation_rank_validated(history, game, arm, target_issue)


def _ablation_rows(bundle: dict, splits: dict, *, include_test: bool) -> list[dict]:
    rows = []
    for game in ("SSQ", "DLT"):
        history = bundle[game]
        stop = len(history) if include_test else splits[game]["test"][0]
        # This is exactly SHA256(core.canon(history[:i])), built once per row.
        # Rehashing every complete prefix for every arm is quadratic and unnecessary.
        prefix = hashlib.sha256(b"[")
        for i, target in enumerate(history[:stop]):
            if i >= 120:
                checksum = prefix.copy()
                checksum.update(b"]")
                past = history[max(0, i - 120):i]
                rankings = {arm: _ablation_rank_validated(past, game, arm, target["issue"])[:5]
                            for arm in ABLATION_ARMS}
                actual = set(target["front"])
                scope = ("train" if i < splits[game]["train"][1] else
                         "validation" if i < splits[game]["validation"][1] else "test")
                rows.append({
                    "lottery": game, "issue": target["issue"], "draw_date": target["draw_date"],
                    "draw_index": i, "scope": scope, "training_end_index": i - 1,
                    "training_prefix_sha256": checksum.hexdigest(),
                    "actual_front": list(target["front"]), "actual_back": list(target["back"]),
                    "rankings": rankings,
                    "pairs": {arm: ranking[:2] for arm, ranking in rankings.items()},
                    "all_hit": {arm: {f"D{d}": int(set(ranking[:d]).issubset(actual))
                                      for d in range(1, 6)} for arm, ranking in rankings.items()},
                    "top5_hits": {arm: len(actual.intersection(ranking))
                                  for arm, ranking in rankings.items()},
                })
            if i:
                prefix.update(b",")
            prefix.update(core.canon(target).encode("utf-8"))
    return rows


def _ablation_family_ids() -> list[str]:
    family = []
    for game in ("SSQ", "DLT"):
        for scope in ABLATION_SCOPES:
            family.extend(f"{game}:{scope}:{arm}:joint" for arm in ABLATION_ARMS[:-1])
            family.extend(f"{game}:{scope}:{left}>{right}:paired"
                          for left, right in ABLATION_COMPARISONS)
    return family


def prepare_ablation_study(bundle: dict) -> dict:
    """Score train/validation only and return the manifest to persist before evaluation.

    Hashing the full input identifies the cohort; it does not use test outcomes
    for model selection. Public historical data are not genuinely unseen data.
    """
    splits = _validate_ablation_bundle(bundle)
    rows = _ablation_rows(bundle, splits, include_test=False)
    selection = {}
    for game in ("SSQ", "DLT"):
        validation = [row for row in rows if row["lottery"] == game and row["scope"] == "validation"]
        hits = {arm: sum(row["all_hit"][arm]["D2"] for row in validation)
                for arm in ABLATION_ARMS[:-1]}
        selected = min(ABLATION_ARMS[:-1], key=lambda arm: (-hits[arm], ABLATION_ARMS.index(arm)))
        selection[game] = {"arm": selected, "validation_d2_hits": hits[selected],
                           "validation_n": len(validation)}
    manifest = {
        "schema": "V47-RECENCY-ABLATION-MANIFEST-1", "contract": _ablation_contract(),
        "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for name, path in (("lab", Path(__file__)),
                                             ("core", Path(core.__file__)),
                                             ("statistics", Path(statistics.__file__)))},
        "input_bundle_sha256": core.digest(bundle), "splits": splits,
        "prepared_target_indices": {game: list(range(120, splits[game]["test"][0]))
                                    for game in ("SSQ", "DLT")},
        "prepared_rows_sha256": core.digest(rows), "selection": selection,
        "family_ids": _ablation_family_ids(), "sequence": "observed-row-contiguous",
        "completeness": "NOT_VERIFIED", "publication_availability": "UNKNOWN_DATE_ONLY",
        "historical_withholding": "OPERATIONAL_ONLY_PUBLIC_LABELS_ALREADY_EXPOSED",
        "external_certification": "NONE", "decision": "NO_EDGE", "formal_A": 0,
    }
    manifest["manifest_sha256"] = core.digest(manifest)
    return manifest


def _ablation_validate_bits(left: list[int], right: list[int]) -> None:
    if (not isinstance(left, list) or not isinstance(right, list) or not left
            or len(left) != len(right)
            or any(type(bit) is not int or bit not in (0, 1) for bit in left + right)):
        raise core.GateError("ABLATION_NONEMPTY_PAIRED_BINARY_VECTORS_REQUIRED")


@lru_cache(maxsize=4096)
def _ablation_interval(hits: int, n: int, confidence: float) -> tuple[float, float]:
    return clopper_pearson(hits, n, confidence)


def _ablation_paired_statistics(left: list[int], right: list[int]) -> dict:
    """Same-draw conditional exact sign test and conservative marginal-CP interval."""
    _ablation_validate_bits(left, right)
    n = len(left)
    wins = sum(a == 1 and b == 0 for a, b in zip(left, right))
    losses = sum(a == 0 and b == 1 for a, b in zip(left, right))
    win_ci = _ablation_interval(wins, n, .975)
    loss_ci = _ablation_interval(losses, n, .975)
    return {
        "n": n, "wins": wins, "losses": losses, "ties": n - wins - losses,
        "rate_difference": (wins - losses) / n,
        "p_exact_paired": exact_binomial_upper_tail(wins, wins + losses, .5),
        "rate_difference_ci95_conservative": [max(-1.0, win_ci[0] - loss_ci[1]),
                                              min(1.0, win_ci[1] - loss_ci[0])],
    }


def _ablation_phi(left: list[int], right: list[int]) -> float | None:
    _ablation_validate_bits(left, right)
    a = sum(x == 1 and y == 1 for x, y in zip(left, right))
    b = sum(x == 1 and y == 0 for x, y in zip(left, right))
    c = sum(x == 0 and y == 1 for x, y in zip(left, right))
    d = len(left) - a - b - c
    denominator = (a + b) * (c + d) * (a + c) * (b + d)
    return (a * d - b * c) / sqrt(denominator) if denominator else None


def _ablation_scope_statistics(rows: list[dict], game: str) -> dict:
    n = len(rows)
    if not n:
        raise core.GateError("ABLATION_EMPTY_SCOPE")
    vectors = {arm: [row["all_hit"][arm]["D2"] for row in rows] for arm in ABLATION_ARMS}
    arms = {}
    for arm, bits in vectors.items():
        hits = sum(bits)
        pair = _ablation_paired_statistics(bits, vectors["NULL"])
        p_fair = exact_binomial_upper_tail(hits, n, core.RULES[game]["d2"])
        arms[arm] = {
            "n": n, "d2_hits": hits, "d2_rate": hits / n,
            "d2_ci95": list(_ablation_interval(hits, n, .95)),
            "fair_d2": core.RULES[game]["d2"], "p_exact_vs_fair": p_fair,
            "paired_wins_vs_null": pair["wins"], "paired_losses_vs_null": pair["losses"],
            "paired_ties_vs_null": pair["ties"], "p_exact_paired_vs_null": pair["p_exact_paired"],
            "rate_difference_vs_null": pair["rate_difference"],
            "rate_difference_vs_null_ci95_conservative": pair["rate_difference_ci95_conservative"],
            "p_joint": max(p_fair, pair["p_exact_paired"]),
            "all_hit_counts": {f"D{d}": sum(row["all_hit"][arm][f"D{d}"] for row in rows)
                               for d in range(1, 6)},
            "top5_total_hits": sum(row["top5_hits"][arm] for row in rows),
        }
    comparisons = {f"{left}>{right}": _ablation_paired_statistics(vectors[left], vectors[right])
                   for left, right in ABLATION_COMPARISONS}
    correlations = {}
    for left, right in combinations(ABLATION_ARMS, 2):
        agreement = sum(set(row["pairs"][left]) == set(row["pairs"][right]) for row in rows)
        correlations[f"{left}|{right}"] = {
            "n": n, "same_pair_count": agreement, "same_pair_rate": agreement / n,
            "binary_d2_phi": _ablation_phi(vectors[left], vectors[right]),
        }
    return {"n": n, "arms": arms, "comparisons": comparisons, "correlations": correlations}


def evaluate_ablation_study(bundle: dict, manifest: dict, *,
                            expected_manifest_sha256: str) -> dict:
    """Verify an externally recorded digest AND reconstruct the entire fixed manifest.

    A caller-rehashed edited manifest cannot create a new seed, family, boundary,
    source identity or selection. The digest is an operational custody check;
    neither this function nor the caller's disk provides external certification.
    """
    if not isinstance(manifest, dict) or not isinstance(expected_manifest_sha256, str):
        raise core.GateError("ABLATION_RECORDED_MANIFEST_SHA256_REQUIRED")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("manifest_sha256") != expected_manifest_sha256
            or core.digest(unsigned) != expected_manifest_sha256):
        raise core.GateError("ABLATION_FROZEN_MANIFEST_DIGEST_MISMATCH")
    expected = prepare_ablation_study(bundle)
    # Canonical JSON comparison also rejects bool/int aliases and extra schema keys.
    if core.canon(manifest) != core.canon(expected):
        raise core.GateError("ABLATION_FROZEN_MANIFEST_CONTRACT_OR_INPUT_MISMATCH")
    rows = _ablation_rows(bundle, manifest["splits"], include_test=True)
    report_statistics, pvalues = {}, {}
    for game in ("SSQ", "DLT"):
        report_statistics[game] = {}
        game_rows = [row for row in rows if row["lottery"] == game]
        for scope in ABLATION_SCOPES:
            sample = game_rows if scope == "all" else [row for row in game_rows if row["scope"] == scope]
            result = _ablation_scope_statistics(sample, game)
            report_statistics[game][scope] = result
            for arm in ABLATION_ARMS[:-1]:
                pvalues[f"{game}:{scope}:{arm}:joint"] = result["arms"][arm]["p_joint"]
            for left, right in ABLATION_COMPARISONS:
                pvalues[f"{game}:{scope}:{left}>{right}:paired"] = result["comparisons"][f"{left}>{right}"]["p_exact_paired"]
    adjusted = statistics.holm_adjust(pvalues, manifest["family_ids"])
    return {
        "schema": "V47-RECENCY-ABLATION-EXPLORATORY-1",
        "manifest_sha256": expected_manifest_sha256,
        "input_bundle_sha256": manifest["input_bundle_sha256"],
        "source_sha256": manifest["source_sha256"],
        "evaluation_rows_sha256": core.digest(rows), "rows": rows,
        "draws_by_game": {game: len(bundle[game]) - 120 for game in ("SSQ", "DLT")},
        "statistics": report_statistics, "p_unadjusted": pvalues, "holm_adjusted_p": adjusted,
        "family_ids": manifest["family_ids"], "family_size": len(manifest["family_ids"]),
        "family_status": "EXPLORATORY_NOT_THE_REGISTERED_FORMAL_FAMILY",
        "selection": {game: {**manifest["selection"][game],
                              "status": "DESCRIPTIVE_REFERENCE_NOT_ADDITIONAL_HYPOTHESIS",
                              "test_reference": f"{game}:test:{manifest['selection'][game]['arm']}:joint"}
                      for game in ("SSQ", "DLT")},
        "ENGINEERING_PASS": "NOT_YET", "RESEARCH_VALID": "NOT_YET",
        "D2_EDGE_CONFIRMED": "NO", "formal_A": 0, "decision": "NO_EDGE",
        "qualified_prospective": False, "external_certification": "NONE",
        "sequence": "observed-row-contiguous", "completeness": "NOT_VERIFIED",
        "evidence_class": "RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE",
        "limitations": [
            "Historical labels were already public; operational withholding is not unseen-data validation or preregistration.",
            "Date-only observations cannot authenticate publication availability, sales cutoffs, pre-draw freezes or official calendar completeness.",
            "Exact model-based arithmetic and exploratory Holm adjustment do not establish independence or calibrate adaptive overlapping forecasts.",
            "Validation-selected window/model performance is descriptive and references its existing arm; no new decay or tau search was performed.",
            "Original DLT 69/2880 versus 42/2880 is unresolved without its original cohort and protocol.",
            "No external human certification, formal historical roster denominator verification, promotion or qualifying future evidence is created.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental D2 walk-forward: NEVER official/prospective evidence"
    )
    parser.add_argument("--snapshot-bundle", required=True,
                        help="JSON with EXACT SSQ/DLT historical snapshots")
    args = parser.parse_args(argv)
    try:
        bundle = json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
        result = audit_walk_forward(bundle)
    except (core.GateError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
