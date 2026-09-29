from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQ=["ENGINEERING_SPEC.md","ARCHITECTURE.md","domain.py","engine.py","contracts.py","net_client.py","storage.py","evidence.py","service.py","app.py","release_gate.py"]

def main()->int:
    checks={f"exists:{x}":(ROOT/x).exists() for x in REQ}
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    checks["ui_uses_service"]="InformationService" in app or "service" in app.lower()
    spec=(ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8")
    required_sections={
        "purpose_model":"Requirement / Purpose Model",
        "five_why":"5 Why",
        "risk_boundary":"Risk Boundary",
        "domain_model":"Domain Model",
        "architecture":"Architecture",
        "function_contract":"Function Contract",
        "interface_contract":"Interface Contract",
        "data_source":"Data Source / NetClient",
        "storage":"Storage",
        "engine":"Engine / Evidence / Service / UI",
    }
    gates={name:("PASS" if marker in spec else "FAIL") for name,marker in required_sections.items()}
    gates.update({
        "netclient":"PASS" if (ROOT/"net_client.py").exists() else "FAIL",
        "evidence":"PASS" if (ROOT/"evidence.py").exists() else "FAIL",
        "service":"PASS" if (ROOT/"service.py").exists() else "FAIL",
        "ui":"PASS" if checks["ui_uses_service"] else "FAIL",
    })
    status="PASS" if all(checks.values()) and all(v=="PASS" for v in gates.values()) else "FAIL"
    report={"schema":"head-intelligence-architecture-gate-v2","status":status,"checks":checks,"gates":gates}
    (ROOT/"architecture_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
