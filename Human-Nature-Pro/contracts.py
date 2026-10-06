from __future__ import annotations
from typing import Any

SOURCE_REGISTRY = {
    "knowledge": {
        "id": "github-raw-human-nature-kb",
        "purpose": "knowledge update",
        "url": "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/human-nature-pro-v1/Human-Nature-Pro/knowledge_base.json",
        "authority": "project-controlled",
        "freshness": "on-demand",
    }
}

SERVICE_METHODS = (
    "analyze",
    "update_all",
    "repair",
    "advanced_analysis",
    "self_test",
    "health",
)

def validate_knowledge(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("knowledge schema mismatch")
    if not isinstance(data.get("rules"), list) or not data["rules"]:
        raise ValueError("knowledge rules missing")
    if not isinstance(data.get("hypothesis_templates"), list) or not data["hypothesis_templates"]:
        raise ValueError("hypothesis templates missing")
    if not isinstance(data.get("sources"), list) or not data["sources"]:
        raise ValueError("knowledge sources missing")
    return data
