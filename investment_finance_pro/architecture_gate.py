from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "ENGINEERING_FREEZE.md",
    "domain.py",
    "contracts.py",
    "net_client.py",
    "storage.py",
    "engine.py",
    "evidence.py",
    "service.py",
    "app.py",
    "release_gate.py",
    "real_network_check.py",
]

def main() -> int:
    checks = {f"exists:{x}": (ROOT / x).exists() for x in REQUIRED}
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    checks["ui_service_only"] = "from service import" in app and "legacy_backend" not in app
    service = (ROOT / "service.py").read_text(encoding="utf-8")
    checks["service_layers"] = all(
        token in service
        for token in ("from engine import", "from storage import", "from net_client import", "from evidence import")
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status": status, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
