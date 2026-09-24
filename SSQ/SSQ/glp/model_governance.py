from __future__ import annotations

from typing import Any, Iterable

MODEL_STATES = ("VALIDATED_EDGE", "NO_EDGE", "UNVALIDATED")

# Frozen candidate universe. Every non-baseline family may compete in validation,
# but none receives production weight merely because it exists.
CANDIDATE_MODELS = (
    "random_baseline",
    "simple_frequency",
    "recency",
    "gap",
    "transition",
    "pair_graph",
    "geometry_state",
    "geometry_transition",
    "ranking_model",
    "logistic_regression",
    "decision_tree",
    "gradient_boosting",
    "research_ensemble",
)

INDIVIDUAL_VALIDATION_GATES = (
    "walk_forward_oos",
    "random_baseline",
    "bootstrap",
    "ablation",
    "reality_check",
    "holm",
    "leave_one_era_out",
    "leakage_sentinel",
    "null_world_fpr",
    "untouched_holdout",
)

ENSEMBLE_VALIDATION_GATES = (
    "model_correlation",
    "incremental_information",
    "remove_one_model_ablation",
    "ensemble_gain",
    "weight_stability",
)

PRODUCTION_CHAIN = (
    "CANDIDATE_POOL",
    "INDEPENDENT_VALIDATION",
    "FALSE_EDGE_REJECTION",
    "VALIDATED_EDGE_PROMOTION",
    "CHAMPION_OR_ENSEMBLE_FREEZE",
    "WINDOWS_EXE",
    "EXACT_PACKAGE_REVALIDATION",
    "SAME_HASH",
    "FINAL_RELEASE_GATE",
    "FINAL_ARTIFACT",
)


def _is_pass(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.upper() in {"PASS", "ACCEPT", "ACCEPT_EDGE", "SUPPORT_EDGE", "VALIDATED_EDGE"}
    if isinstance(value, dict):
        if "passed" in value:
            return bool(value["passed"])
        status = value.get("status")
        decision = value.get("decision")
        if status is not None and str(status).upper() != "PASS":
            return False
        if decision is None:
            return str(status).upper() == "PASS"
        return str(decision).upper() in {"PASS", "ACCEPT", "ACCEPT_EDGE", "SUPPORT_EDGE", "VALIDATED_EDGE"}
    return False


def classify_model(gates: dict[str, Any] | None) -> str:
    """Return the only allowed scientific state for one candidate model.

    Missing evidence is UNVALIDATED. Executed evidence that does not prove all
    required edge gates is NO_EDGE. Only a complete all-gates pass is VALIDATED_EDGE.
    """
    if not isinstance(gates, dict):
        return "UNVALIDATED"
    missing = [name for name in INDIVIDUAL_VALIDATION_GATES if name not in gates]
    if missing:
        return "UNVALIDATED"
    return "VALIDATED_EDGE" if all(_is_pass(gates[name]) for name in INDIVIDUAL_VALIDATION_GATES) else "NO_EDGE"


def production_members(
    model_states: dict[str, str],
    ensemble_gates: dict[str, Any] | None,
    *,
    allowed_models: Iterable[str] = CANDIDATE_MODELS,
) -> list[str]:
    """Select production members without automatic all-model fusion.

    A model must already be VALIDATED_EDGE. If more than one model survives,
    the ensemble itself must pass correlation/incremental/ablation/gain/stability
    gates before multiple members may be loaded together.
    """
    allowed = set(allowed_models)
    survivors = [
        name for name, state in model_states.items()
        if name in allowed and name != "random_baseline" and state == "VALIDATED_EDGE"
    ]
    survivors.sort()
    if len(survivors) <= 1:
        return survivors
    if not isinstance(ensemble_gates, dict):
        return []
    if any(name not in ensemble_gates for name in ENSEMBLE_VALIDATION_GATES):
        return []
    if not all(_is_pass(ensemble_gates[name]) for name in ENSEMBLE_VALIDATION_GATES):
        return []
    return survivors


def production_state(model_states: dict[str, str], members: list[str]) -> dict[str, Any]:
    """Machine-readable fail-closed production decision."""
    unknown = {k: v for k, v in model_states.items() if v not in MODEL_STATES}
    if unknown:
        raise ValueError(f"invalid model states: {unknown}")
    if not members:
        return {
            "state": "NO_EDGE",
            "champion": "random_baseline",
            "production_models": [],
            "production_weights": {"random_baseline": 1.0},
        }
    weight = 1.0 / len(members)
    return {
        "state": "VALIDATED_EDGE",
        "champion": "frozen_validated_ensemble" if len(members) > 1 else members[0],
        "production_models": list(members),
        "production_weights": {m: weight for m in members},
    }
