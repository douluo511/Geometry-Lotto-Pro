from __future__ import annotations

SERVICE_METHODS = (
    "opportunities",
    "update_all",
    "repair",
    "advanced_analysis",
    "self_test",
    "network_smoke",
    "health",
)

ALLOWED_MODEL_STATUS = {"UNVALIDATED", "VALIDATED_EDGE", "NO_EDGE"}

def validate_snapshot(data: dict) -> dict:
    required = {"version", "update_state", "model_status", "metrics", "ranking", "providers"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise ValueError("snapshot schema mismatch")
    if data["model_status"] not in ALLOWED_MODEL_STATUS:
        raise ValueError("invalid model_status")
    if data["update_state"] not in {"PASS", "PARTIAL", "FAILED"}:
        raise ValueError("invalid update_state")
    return data
