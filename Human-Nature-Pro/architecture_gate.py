from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQ=[
    "MASTER_SYSTEM_ARCHITECTURE.md","BUSINESS_SPEC.md","domain.py","contracts.py",
    "net_client.py","storage.py","engine.py","evidence.py","service.py","app.py",
    "release_gate.py","real_network_check.py",
]

def main()->int:
    checks={f"exists:{x}":(ROOT/x).exists() for x in REQ}
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    service=(ROOT/"service.py").read_text(encoding="utf-8")
    updater=(ROOT/"updater.py").read_text(encoding="utf-8")
    master=(ROOT/"MASTER_SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    checks["ui_service_only"]="from service import" in app and "from core import" not in app and "from updater import" not in app
    checks["service_layers"]=all(x in service for x in ("from engine import","from storage import","from net_client import","from evidence import"))
    checks["no_urllib_network_bypass"]="urllib.request" not in updater and "urlopen(" not in updater
    checks["strict_netclient_tokens"]=all(x in (ROOT/"net_client.py").read_text(encoding="utf-8") for x in (
        "FINAL_INSECURE_REDIRECT","RETRY_HTTP","RETRY_EXCEPTION","body_b64","requested_url","final_url"
    ))
    required={
        "purpose_model":"Business Purpose",
        "five_why":"5 Why",
        "risk_boundary":"Risk Boundary",
        "domain_model":"Domain",
        "architecture":"Master architecture",
        "function_contract":"function inventory",
        "interface_contract":"interface contracts",
        "data_source":"Information / Data Source",
        "storage":"Storage",
        "engine":"Engine",
    }
    gates={k:("PASS" if token.lower() in master.lower() else "FAIL") for k,token in required.items()}
    gates.update({
        "netclient":"PASS" if checks["strict_netclient_tokens"] else "FAIL",
        "evidence":"PASS" if (ROOT/"evidence.py").exists() else "FAIL",
        "service":"PASS" if checks["service_layers"] else "FAIL",
        "ui":"PASS" if checks["ui_service_only"] else "FAIL",
    })
    status="PASS" if all(checks.values()) and all(v=="PASS" for v in gates.values()) else "FAIL"
    report={"schema":"human-nature-architecture-gate-v2","status":status,"checks":checks,"gates":gates}
    (ROOT/"architecture_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
