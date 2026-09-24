from __future__ import annotations
import hashlib
from typing import Any

APP_NAME = "国学智策系统"
APP_VERSION = "0.2.0"

class ContractError(ValueError):
    pass

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ContractError("manifest schema mismatch")
    if not str(value.get("data_url", "")).startswith("https://"):
        raise ContractError("manifest data_url must be https")
    digest = str(value.get("sha256", "")).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ContractError("manifest sha256 invalid")
    if not str(value.get("version", "")).strip():
        raise ContractError("manifest version missing")
    return value

def validate_knowledge(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ContractError("knowledge schema mismatch")
    classics = value.get("classics")
    if not isinstance(classics, list) or len(classics) < 15:
        raise ContractError("knowledge base is incomplete")
    seen = set()
    for row in classics:
        if not isinstance(row, dict):
            raise ContractError("invalid classic row")
        title = str(row.get("title", "")).strip()
        if not title or title in seen:
            raise ContractError("empty or duplicate title")
        seen.add(title)
        if not isinstance(row.get("scenarios"), list) or not row["scenarios"]:
            raise ContractError(f"{title}: missing scenarios")
        if not isinstance(row.get("methods"), list) or not row["methods"]:
            raise ContractError(f"{title}: missing methods")
        if not str(row.get("source_note", "")).strip():
            raise ContractError(f"{title}: missing source note")
        if not str(row.get("boundary", "")).strip():
            raise ContractError(f"{title}: missing boundary")
    return value

def validate_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ContractError("state schema mismatch")
    value.setdefault("analyses", [])
    value.setdefault("reviews", [])
    value.setdefault("last_update", None)
    if not isinstance(value["analyses"], list) or not isinstance(value["reviews"], list):
        raise ContractError("state collections invalid")
    return value
