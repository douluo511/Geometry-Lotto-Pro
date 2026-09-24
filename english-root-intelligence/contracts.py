from __future__ import annotations
from typing import Any
from core import validate_roots

def validate_manifest(v: Any) -> dict:
    if not isinstance(v, dict) or v.get("schema") != 1:
        raise ValueError("manifest schema mismatch")
    for k in ("data_url","sha256"):
        if not isinstance(v.get(k), str) or not v[k].strip():
            raise ValueError(f"manifest missing {k}")
    if not v["data_url"].startswith("https://"):
        raise ValueError("data_url must be HTTPS")
    return v

__all__=["validate_roots","validate_manifest"]
