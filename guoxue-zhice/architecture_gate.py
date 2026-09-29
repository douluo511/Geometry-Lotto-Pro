from __future__ import annotations
import json, os
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main()->int:
    req=["ENGINEERING_SPEC.md","BUSINESS_SPEC.md","core.py","service.py","net_client.py","app.py"]
    checks={f"exists:{x}":(ROOT/x).exists() for x in req}
    spec=(ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8") if (ROOT/"ENGINEERING_SPEC.md").exists() else ""
    core=(ROOT/"core.py").read_text(encoding="utf-8")
    svc=(ROOT/"service.py").read_text(encoding="utf-8")
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    net=(ROOT/"net_client.py").read_text(encoding="utf-8")
    gates={
      "purpose_model":"PASS" if "## Requirement / Purpose Model" in spec else "FAIL",
      "five_why":"PASS" if "## 5 Why" in spec else "FAIL",
      "risk_boundary":"PASS" if "## Risk Boundary" in spec else "FAIL",
      "domain_model":"PASS" if "## Domain Model" in spec else "FAIL",
      "architecture":"PASS" if "## Architecture" in spec and "from service import" in app else "FAIL",
      "function_contract":"PASS" if "## Function Contract / Interface Contract" in spec else "FAIL",
      "interface_contract":"PASS" if "## Function Contract / Interface Contract" in spec else "FAIL",
      "data_source":"PASS" if "## Data Source" in spec and "MANIFEST_URLS" in core else "FAIL",
      "netclient":"PASS" if "NetClient" in core and "urllib.request" not in core and "RETRYABLE_STATUS" in net else "FAIL",
      "storage":"PASS" if "commit_network_update" in core and "_stage_bytes" in core else "FAIL",
      "engine":"PASS" if "GoalEngine" in core and "ReviewEngine" in core else "FAIL",
      "evidence":"PASS" if "network_evidence.json" in core and "knowledge_sha256" in core else "FAIL",
      "service":"PASS" if "class GuoxueService" in svc else "FAIL",
      "ui":"PASS" if "create_service" in app and all(x not in app for x in ["GoalEngine","MaintenanceEngine","ReviewEngine","Store("]) else "FAIL",
    }
    checks["no_direct_network_bypass"]="urllib.request" not in core
    status="PASS" if all(checks.values()) and all(v=="PASS" for v in gates.values()) else "FAIL"
    report={"schema":"guoxue-architecture-gate-v1","status":status,"github_sha":os.environ.get("GITHUB_SHA"),"gates":gates,"checks":checks}
    (ROOT/"architecture_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
