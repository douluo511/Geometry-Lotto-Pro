from __future__ import annotations

import argparse
import json
from pathlib import Path

from .storage import Storage


def check_context(root: Path) -> dict:
    cfg_path = root / "updater.json"
    if not cfg_path.is_file():
        return {
            "status": "BLOCKED",
            "reason": "independent production repository/release manifest/trusted signing key not configured",
        }
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    required = ("enabled", "repository", "manifest_url", "trusted_public_key_hex")
    missing = [key for key in required if key not in cfg]
    if missing:
        return {"status": "FAIL", "reason": f"updater configuration missing: {missing}"}
    if cfg.get("enabled") is not True:
        return {"status": "BLOCKED", "reason": "production updater disabled"}
    if cfg.get("repository") == "douluo511/Geometry-Lotto-Pro":
        return {"status": "BLOCKED", "reason": "shared monorepo is rejected as production repository"}
    if not str(cfg.get("manifest_url", "")).startswith("https://"):
        return {"status": "FAIL", "reason": "manifest URL must be HTTPS"}
    key = str(cfg.get("trusted_public_key_hex", ""))
    if len(key) != 64:
        return {"status": "FAIL", "reason": "Ed25519 trusted public key must be 32 bytes"}
    return {
        "status": "NOT VERIFIED",
        "reason": "configuration shape is valid but real signed Release N->N+1 execution is not implemented/verified on this candidate",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = check_context(root)
    Storage.atomic_json(root / "updater_result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if args.self_test:
        return 0 if result["status"] in {"BLOCKED", "NOT VERIFIED"} else 2
    return 3 if result["status"] == "BLOCKED" else (0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
