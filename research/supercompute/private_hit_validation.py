"""Private, off-repository, historical-only paired SSQ/DLT validation.

This module never writes real lottery results to GitHub or to disk. It does
not issue current forecasts. Official source authenticity and predraw seals
are NOT inferred from a caller-supplied JSON file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from research.supercompute import auto_discovery as legacy
from research.supercompute import auto_discovery_v2 as v2
from research.supercompute import formula_acceleration as accel

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "SSQDLT_PRIVATE_RETROSPECTIVE_FROZEN_COMPARISON_V1"
MAX_INPUT_BYTES = 6 * 1024 * 1024
DEFAULT_VALIDATION = 60
DEFAULT_HOLDOUT = 120


def _strict_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON field")
        obj[key] = value
    return obj


def load_private(path, game):
    p = Path(path).expanduser().resolve(strict=True)
    if p.is_relative_to(ROOT.resolve()):
        raise ValueError("real lottery data must live OUTSIDE Git checkout")
    if not p.is_file() or not 1 <= p.stat().st_size <= MAX_INPUT_BYTES:
        raise ValueError("missing, unsafe or oversized private source")
    raw = p.read_bytes()
    parsed = json.loads(
        raw, object_pairs_hook=_strict_pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError("invalid floating JSON constant")))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("draws"), list):
        raise ValueError("expected private official history JSON containing draws")
    if str(parsed.get("game", "")).lower() != game:
        raise ValueError("game identity mismatch")
    rows = parsed["draws"]
    accel._validate_rows(rows, game)
    last = ""
    for row in rows:
        when = row.get("draw_date")
        if (not isinstance(when, str) or not re.fullmatch(
                r"20\d{2}-\d{2}-\d{2}", when)):
            raise ValueError("missing draw-date semantics")
        d = datetime.strptime(when, "%Y-%m-%d").date()
        if when <= last:
            raise ValueError("duplicate or out-of-order draw date")
        last = when
        if (game == "ssq" and row["issue"][:4] != when[:4]
                or game == "dlt" and row["issue"][:2] != when[2:4]):
            raise ValueError("issue-year mismatch")
    return rows, {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "record_count": len(rows),
        "latest_draw_date": rows[-1]["draw_date"],
        "official_source_authentication": "UNVERIFIED_CALLER_SUPPLIED",
        "independent_predraw_timestamp": "NOT_PRESENT",
    }


def _count_ticket(pick, actual):
    result = legacy.hit_counts(pick, actual)
    return {
        "d2": result["d2"], "exact": result["exact"],
        "front": result["front_hits"], "back": result["back_hits"],
    }


def _paired(a, b, key):
    left = sum(x[key] and not y[key] for x, y in zip(a, b))
    right = sum(y[key] and not x[key] for x, y in zip(a, b))
    both = sum(x[key] and y[key] for x, y in zip(a, b))
    return {
        "n": len(a), "first_only": left, "second_only": right,
        "both": both, "neither": len(a) - left - right - both,
        "p_exact_two_sided_exploratory": legacy.exact_paired_p(left, right),
    }


def evaluate_private_in_memory(rows, game, *, validation=60, holdout=120,
                               backend="numba", workers=1, expanded=True):
    """Selection freezes BEFORE any test outcome is read by the ranker."""
    accel._validate_rows(rows, game)
    if (not 20 <= validation <= 150 or not 20 <= holdout <= 300
            or len(rows) - holdout - validation < 180):
        raise ValueError("independent train, development and holdout intervals required")
    test_start = len(rows) - holdout
    start_val = test_start - validation
    dev = rows[:test_start]
    # These selectors see ONLY development/training records.
    frozen_v2 = v2.frozen_selection(dev, game, start_val, test_start)
    grammar = (
        accel.GRAMMAR if expanded else tuple(
            x for x in accel.GRAMMAR if x["window"] == 8)
    )
    frozen_v3 = accel.training_rank(
        dev, game, list(range(start_val, test_start)), expressions=grammar,
        backend=backend, workers=workers)
    selected = tuple(
        accel.FORMULA_BY_ID[x["formula_id"]]
        for x in frozen_v3["selection"])
    grid = accel.evaluate_grid(
        rows, game, list(range(test_start, len(rows))), selected,
        backend=backend, workers=workers)
    scores = {"FORMULA_V3": [], "FORMULA_V2": [],
              "FROZEN_RESEARCH_NULL": []}
    for step, target in enumerate(range(test_start, len(rows))):
        asof = rows[target - 1]["issue"]
        new_ticket = accel._ensemble(
            [grid[x["id"]][step] for x in selected], game, str(asof))
        old_ticket = v2.predict_frozen(
            rows[:target], game, frozen_v2)["candidate"]
        null_ticket = legacy.research_null(game, str(rows[target]["issue"]))
        actual = rows[target]  # Only the scorer can access outcome at target.
        for arm, ticket in (
                ("FORMULA_V3", new_ticket),
                ("FORMULA_V2", old_ticket),
                ("FROZEN_RESEARCH_NULL", null_ticket)):
            scores[arm].append(_count_ticket(ticket, actual))
    agg = {}
    for arm, values in scores.items():
        agg[arm] = {
            "d2_hits": sum(x["d2"] for x in values),
            "exact_tickets": sum(x["exact"] for x in values),
            "front_hits": sum(x["front"] for x in values),
            "back_hits": sum(x["back"] for x in values),
            "d2_wilson95": accel.wilson(sum(x["d2"] for x in values), holdout),
        }
    comparisons = {
        "v3_vs_research_null": _paired(
            scores["FORMULA_V3"], scores["FROZEN_RESEARCH_NULL"], "d2"),
        "v3_vs_v2": _paired(
            scores["FORMULA_V3"], scores["FORMULA_V2"], "d2"),
    }
    return {
        "game": game, "schema": PROTOCOL,
        "train_issue_count": start_val,
        "validation_count": validation, "holdout_count": holdout,
        "expanded_formula_count": len(grammar),
        "frozen_v3_sha256": frozen_v3["freeze_sha256"],
        "frozen_v2_sha256": frozen_v2["selection_sha256"],
        "arms": agg, "comparisons": comparisons,
        "theoretical_d2_chance": legacy.chance(game)["dan2_probability"],
        "source": "PRIVATE_CALLER_SUPPLIED_HISTORICAL_NOT_PROSPECTIVE",
        "official_source_authenticated": False,
        "independent_predraw_seal_verified": False,
        "prospective_scored": 0, "formal_A": 0, "edge": "NO_EDGE",
        "predictive_improvement_verified": False,
    }


def compare_both(ssq, dlt, *, validation=DEFAULT_VALIDATION,
                 holdout=DEFAULT_HOLDOUT, backend="numba", workers=1,
                 expanded=True):
    record = {}
    pvalues = []
    for game, rows in (("ssq", ssq), ("dlt", dlt)):
        result = evaluate_private_in_memory(
            rows, game, validation=validation, holdout=holdout,
            backend=backend, workers=workers, expanded=expanded)
        record[game] = result
        pvalues.extend(
            result["comparisons"][key]["p_exact_two_sided_exploratory"]
            for key in ("v3_vs_research_null", "v3_vs_v2"))
    adjusted = accel.holm_adjust(pvalues)
    for i, game in enumerate(("ssq", "dlt")):
        for j, key in enumerate(("v3_vs_research_null", "v3_vs_v2")):
            record[game]["comparisons"][key]["holm_four_test_exploratory"] = (
                adjusted[i * 2 + j])
    return {
        "schema": PROTOCOL, "games": record,
        "predeclared_family_size": 4,
        "scope": "RETROSPECTIVE_AND_NO_OFFICIAL_AUTHENTICATION",
        "formal_A": 0, "edge": "NO_EDGE",
        "predictive_improvement_verified": False,
        "sample_selection_warnings": [
            "Old draws were visible when selecting this research direction",
            "Historical split and p-values cannot establish prospective predictive edge",
            "Extra experimental variants outside the four-test family need correction",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ssq-private", type=Path, required=True)
    p.add_argument("--dlt-private", type=Path, required=True)
    p.add_argument("--validation", type=int, default=DEFAULT_VALIDATION)
    p.add_argument("--holdout", type=int, default=DEFAULT_HOLDOUT)
    p.add_argument("--backend", choices=("numpy", "numba"), default="numba")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--legacy-sized", action="store_true",
                   help="Limit expanded grammar to 78 for quicker diagnostic")
    a = p.parse_args(argv)
    ssq, ssq_source = load_private(a.ssq_private, "ssq")
    dlt, dlt_source = load_private(a.dlt_private, "dlt")
    result = compare_both(
        ssq, dlt, validation=a.validation, holdout=a.holdout,
        backend=a.backend, workers=a.workers, expanded=not a.legacy_sized)
    # Print AGGREGATES only in the user's private terminal; no file output.
    result["private_input_verification"] = {
        "ssq": ssq_source, "dlt": dlt_source,
    }
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
