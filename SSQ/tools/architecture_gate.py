from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "SSQ" / "glp"
SPEC = ROOT / "ENGINEERING_SPEC.md"
REQUIRED = [
    SPEC,
    ROOT / "BUSINESS_SPEC.md",
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
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    gui = (PKG / "gui.py").read_text(encoding="utf-8")
    sources = (PKG / "sources.py").read_text(encoding="utf-8")
    service = (PKG / "service.py").read_text(encoding="utf-8")
    net = (PKG / "net_client.py").read_text(encoding="utf-8")

    gates = {
        "purpose_model": "PASS" if "## Requirement / Purpose Model" in spec else "FAIL",
        "five_why": "PASS" if "## 5 Why" in spec else "FAIL",
        "risk_boundary": "PASS" if "## Risk Boundary" in spec else "FAIL",
        "domain_model": "PASS" if "## Domain Model" in spec and "CanonicalDataset" in spec else "FAIL",
        "architecture": "PASS" if "## Architecture" in spec and "LottoService" in gui else "FAIL",
        "function_contract": "PASS" if "## Function / Interface Contract" in spec else "FAIL",
        "interface_contract": "PASS" if "predict / update / repair / audit" in spec else "FAIL",
        "data_source": "PASS" if "## Data Sources" in spec and "official" in sources.lower() else "FAIL",
        "netclient": "PASS" if (
            "NET.get(" in sources
            and "requests.get(" not in sources
            and "RETRYABLE_STATUS" in net
            and "glp_attempts" in net
            and "rng.random()" in net
            and "timeout_value" in net
        ) else "FAIL",
        "storage": "PASS" if "from glp.storage import" in service else "FAIL",
        "engine": "PASS" if "from glp.engine import" in service else "FAIL",
        "evidence": "PASS" if "from glp.evidence import" in service else "FAIL",
        "service": "PASS" if "class LottoService" in service else "FAIL",
        "ui": "PASS" if "LottoService" in gui else "FAIL",
    }
    checks["sources_use_netclient"] = gates["netclient"] == "PASS"
    checks["ui_uses_service"] = gates["ui"] == "PASS"
    checks["service_uses_engine"] = gates["engine"] == "PASS"
    checks["service_uses_storage"] = gates["storage"] == "PASS"
    checks["service_uses_evidence"] = gates["evidence"] == "PASS"

    status = "PASS" if all(checks.values()) and all(v == "PASS" for v in gates.values()) else "FAIL"
    report = {
        "schema": "ssq-architecture-gate-v2",
        "status": status,
        "gates": gates,
        "checks": checks,
    }
    out = ROOT / "evidence" / "SSQ" / "ARCHITECTURE_GATE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
