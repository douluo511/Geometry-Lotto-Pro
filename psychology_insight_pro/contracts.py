from __future__ import annotations

from typing import Any, Dict

KNOWLEDGE_SCHEMA_VERSION = 1

REQUIRED_HYPOTHESIS_KEYS = {
    "key",
    "name",
    "explanation",
    "support_keywords",
    "contradict_keywords",
}


def validate_knowledge(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("knowledge root must be object")
    if not isinstance(data.get("version"), str) or not data["version"].strip():
        raise ValueError("knowledge.version missing")
    hypotheses = data.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("knowledge.hypotheses missing")
    seen = set()
    for item in hypotheses:
        if not isinstance(item, dict):
            raise ValueError("hypothesis must be object")
        if not REQUIRED_HYPOTHESIS_KEYS.issubset(item):
            raise ValueError("invalid hypothesis schema")
        if item["key"] in seen:
            raise ValueError("duplicate hypothesis key")
        seen.add(item["key"])
        for field in ("support_keywords", "contradict_keywords"):
            if not isinstance(item[field], list) or not all(isinstance(x, str) for x in item[field]):
                raise ValueError(f"{field} must be list[str]")


def parse_version(v: str):
    parts = []
    for p in str(v).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)
