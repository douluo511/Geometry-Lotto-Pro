from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = [
    "ENGINEERING_SPEC.md","BUSINESS_SPEC.md","domain.py","contracts.py","net_client.py",
    "storage.py","engine.py","evidence.py","service.py","app.py","release_gate.py",
    "real_network_check.py","collect_final_gates.py","exact_candidate_gate.py",
]
def main() -> int:
    checks = {f"exists:{x}": (ROOT/x).exists() for x in REQ}
    spec = (ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8") if (ROOT/"ENGINEERING_SPEC.md").exists() else ""
    app = (ROOT/"app.py").read_text(encoding="utf-8")
    svc = (ROOT/"service.py").read_text(encoding="utf-8")
    core = (ROOT/"core.py").read_text(encoding="utf-8")
    net = (ROOT/"net_client.py").read_text(encoding="utf-8")
    gates = {
        "purpose_model": "PASS" if "## Requirement / Purpose Model" in spec else "FAIL",
        "five_why": "PASS" if "## 5 Why" in spec else "FAIL",
        "risk_boundary": "PASS" if "## Risk Boundary" in spec else "FAIL",
        "domain_model": "PASS" if "## Domain Model" in spec else "FAIL",
        "architecture": "PASS" if "## Architecture" in spec and "from service import" in app else "FAIL",
        "function_contract": "PASS" if "## Function Contract / Interface Contract" in spec else "FAIL",
        "interface_contract": "PASS" if "## Function Contract / Interface Contract" in spec else "FAIL",
        "data_source": "PASS" if "## Data Source" in spec else "FAIL",
        "netclient": "PASS" if (
            "from net_client import NetClient" in svc
            and "urllib.request" not in core
            and "connect_timeout" in net and "read_timeout" in net and "max_attempts" in net
        ) else "FAIL",
        "storage": "PASS" if "from storage import RootStorage" in svc else "FAIL",
        "engine": "PASS" if "from engine import EnglishRootEngine" in svc else "FAIL",
        "evidence": "PASS" if "from evidence import EvidenceLedger" in svc else "FAIL",
        "service": "PASS" if "class EnglishRootService" in svc else "FAIL",
        "ui": "PASS" if (
            "from service import" in app
            and all(x not in app for x in ["from core import","from net_client import","from storage import","from engine import"])
        ) else "FAIL",
    }
    checks["legacy_network_bypass_disabled"] = "urllib.request" not in core
    status = "PASS" if all(checks.values()) and all(v == "PASS" for v in gates.values()) else "FAIL"
    report = {
        "schema": "english-root-architecture-gate-v2",
        "status": status,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "gates": gates,
        "checks": checks,
    }
    (ROOT/"architecture_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if status == "PASS" else 2
if __name__=="__main__":
    raise SystemExit(main())
