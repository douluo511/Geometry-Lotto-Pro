from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "SSQ" / "glp"
REQUIRED = [
    ROOT / "ENGINEERING_SPEC.md",
    PKG / "domain.py",
    PKG / "net_client.py",
    PKG / "storage.py",
    PKG / "engine.py",
    PKG / "evidence.py",
    PKG / "service.py",
    PKG / "gui.py",
    PKG / "sources.py",
]

def main() -> int:
    checks = {f"exists:{p.name}": p.exists() for p in REQUIRED}
    gui = (PKG / "gui.py").read_text(encoding="utf-8")
    sources = (PKG / "sources.py").read_text(encoding="utf-8")
    service = (PKG / "service.py").read_text(encoding="utf-8")
    checks["ui_uses_service"] = "LottoService" in gui
    checks["sources_use_netclient"] = "NET.get(" in sources and "requests.get(" not in sources
    checks["service_uses_engine"] = "from glp.engine import" in service
    checks["service_uses_storage"] = "from glp.storage import" in service
    checks["service_uses_evidence"] = "from glp.evidence import" in service
    status = "PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status": status, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
