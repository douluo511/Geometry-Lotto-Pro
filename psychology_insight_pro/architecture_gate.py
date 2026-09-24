from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQUIRED=["ENGINEERING_SPEC.md","domain.py","engine.py","contracts.py","net_client.py","storage.py","evidence.py","service.py","app.py","release_gate.py","real_network_check.py"]

def main()->int:
    checks={f"exists:{x}":(ROOT/x).exists() for x in REQUIRED}
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    checks["ui_not_import_netclient"]="from net_client" not in app
    checks["ui_not_import_storage"]="from storage" not in app
    checks["ui_uses_service"]="from service import" in app
    svc=(ROOT/"service.py").read_text(encoding="utf-8")
    checks["service_uses_engine"]="from engine import" in svc
    spec=(ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8")
    for marker in ["Requirement / Purpose Model","5 Why","Risk Boundary","Domain Model","Architecture","Data Source","NetClient","Storage","Evidence","Final Gate"]:
        checks[f"spec:{marker}"]=marker in spec
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},ensure_ascii=False,indent=2))
    return 0 if status=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
