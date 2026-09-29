from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "ENGINEERING_SPEC.md", "BUSINESS_SPEC.md", "domain.py", "engine.py",
    "contracts.py", "net_client.py", "storage.py", "evidence.py",
    "service.py", "app.py", "release_gate.py", "real_network_check.py",
]


def main() -> int:
    checks = {f"exists:{x}": (ROOT / x).exists() for x in REQUIRED}
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    svc = (ROOT / "service.py").read_text(encoding="utf-8")
    net = (ROOT / "net_client.py").read_text(encoding="utf-8")
    storage = (ROOT / "storage.py").read_text(encoding="utf-8")
    spec = (ROOT / "ENGINEERING_SPEC.md").read_text(encoding="utf-8")

    checks["ui_not_import_netclient"] = "from net_client" not in app
    checks["ui_not_import_storage"] = "from storage" not in app
    checks["ui_uses_service"] = "from service import" in app
    checks["service_uses_engine"] = "from engine import" in svc
    checks["service_uses_storage"] = "from storage import" in svc
    checks["service_uses_netclient"] = "from net_client import" in svc

    gates = {
        "purpose_model": "PASS" if "Requirement / Purpose Model" in spec else "FAIL",
        "five_why": "PASS" if "5 Why" in spec else "FAIL",
        "risk_boundary": "PASS" if "Risk Boundary" in spec else "FAIL",
        "domain_model": "PASS" if "Domain Model" in spec else "FAIL",
        "architecture": "PASS" if "Architecture" in spec and checks["ui_uses_service"] else "FAIL",
        "function_contract": "PASS" if "Function" in spec and "Contract" in spec else "FAIL",
        "interface_contract": "PASS" if "Interface" in spec and "Contract" in spec else "FAIL",
        "data_source": "PASS" if "Data Source" in spec else "FAIL",
        "netclient": "PASS" if (
            "timeout=(self.connect_timeout, self.read_timeout)" in net
            and "RETRYABLE_STATUS" in net
            and "attempts" in net
            and "raw_b64" in net
            and "self.rng.random()" in net
        ) else "FAIL",
        "storage": "PASS" if (
            "commit_id" in storage
            and "_stage(" in storage
            and "_restore(" in storage
        ) else "FAIL",
        "engine": "PASS" if "from engine import" in svc else "FAIL",
        "evidence": "PASS" if (ROOT / "evidence.py").exists() else "FAIL",
        "service": "PASS" if "class PsychologyService" in svc else "FAIL",
        "ui": "PASS" if checks["ui_uses_service"] else "FAIL",
    }

    for marker in [
        "Requirement / Purpose Model", "5 Why", "Risk Boundary", "Domain Model",
        "Architecture", "Data Source", "NetClient", "Storage", "Evidence", "Final Gate",
    ]:
        checks[f"spec:{marker}"] = marker in spec

    status = "PASS" if all(checks.values()) and all(v == "PASS" for v in gates.values()) else "FAIL"
    report = {
        "schema": "psychology-architecture-gate-v2",
        "status": status,
        "gates": gates,
        "checks": checks,
    }
    out = ROOT / "architecture_gate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
