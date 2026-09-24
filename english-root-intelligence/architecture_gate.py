from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REQ=["ENGINEERING_SPEC.md","domain.py","contracts.py","net_client.py","storage.py","engine.py","evidence.py","service.py","app.py","release_gate.py","real_network_check.py"]
def main():
 c={f"exists:{x}":(ROOT/x).exists() for x in REQ}; app=(ROOT/"app.py").read_text(encoding="utf-8"); c["ui_service_only"]="from service import" in app and all(x not in app for x in ["from core import","from net_client import","from storage import","from engine import"]); svc=(ROOT/"service.py").read_text(encoding="utf-8"); c["service_engine"]="from engine import" in svc; c["service_storage"]="from storage import" in svc; c["service_net"]="from net_client import" in svc; st="PASS" if all(c.values()) else "FAIL"; print(json.dumps({"status":st,"checks":c},indent=2)); return 0 if st=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
