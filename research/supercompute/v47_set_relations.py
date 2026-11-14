"""Strict element and set relations for SSQ/DLT V4.7 model scoring.

Distinguishes:
  member: x in R
  nonmember: x not in R
  contained: A subset of R
  not_contained: A not subset of R (at least one absent)
  disjoint: A intersection R is empty (EVERY element absent)

In our M+ / M- contracts, M+ succeeds on contained, and M- succeeds
ONLY on disjoint.  The literal negation 'not_contained' is merely a
diagnostic and MUST NOT substitute for strict M- success.

All four lottery areas use these exact same rules.  Empty constraint sets
are allowed in variable-count interval search but explicitly marked VACUOUS.
"""
from __future__ import annotations

from research.supercompute.v47_models import SPECS, validate_ticket


def evaluate_relation(game, area, selected, actual):
    """Return per-element membership and strict set events for a draw area.

    selected: list of distinct integers, possibly [] for an inactive filter.
    actual: whole draw dict with legal sorted front/back lists.
    """
    if game not in SPECS:
        raise ValueError("unknown lottery")
    validate_ticket(actual, game)
    if area not in ("front", "back"):
        raise ValueError("unknown area")
    if not isinstance(selected, list):
        raise ValueError("selected numbers must be a list")
    max_number = SPECS[game][0 if area == "front" else 2]
    if (any(type(n) is not int or n < 1 or n > max_number for n in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError("selected numbers out of range or duplicated")
    draw = set(actual[area])
    selected_set = set(selected)
    overlap = sorted(selected_set & draw)
    missing = sorted(selected_set - draw)
    subset = not missing
    disjoint = not overlap
    count = len(selected)
    # not_subset is the set-theoretic complement of subset, not disjoint.
    return {
        "game": game,
        "area": area,
        "selected": sorted(selected),
        "active_constraint": count > 0,
        "vacuous_when_empty": count == 0,
        "selected_count": count,
        "members": overlap,
        "nonmembers": missing,
        "member_count": len(overlap),
        "nonmember_count": len(missing),
        "element_membership": [
            {"number": n, "belongs": n in draw, "not_belongs": n not in draw}
            for n in sorted(selected)
        ],
        "contained": subset,
        "not_contained": not subset,
        "disjoint": disjoint,
        "partial_absence_not_full_exclusion":
            bool(overlap) and bool(missing),
        "m_plus_all_contained": subset,
        "m_minus_all_absent": disjoint,
        "m_minus_success": disjoint if count else None,
        "m_plus_success": subset if count else None,
        "semantics": "M_PLUS_SUBSET__M_MINUS_DISJOINT",
    }


def score_model_relation(game, direction, selected, actual, area="front"):
    """Score genuine + or - with the strict, nonvacuous model event."""
    if direction not in ("subset", "disjoint"):
        raise ValueError("legacy non-subset is not a strict M- event")
    report = evaluate_relation(game, area, selected, actual)
    if not report["active_constraint"]:
        raise ValueError("an individual M+/M- model cannot assert an empty event")
    report["model_direction"] = direction
    report["success"] = (report["contained"] if direction == "subset"
                         else report["disjoint"])
    report["scoring_event"] = ("A_SUBSET_DRAW" if direction == "subset"
                               else "E_DISJOINT_DRAW")
    return report
