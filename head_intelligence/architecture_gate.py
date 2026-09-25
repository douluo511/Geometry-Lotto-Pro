from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REQ=["ENGINEERING_SPEC.md","ARCHITECTURE.md","domain.py","engine.py","contracts.py","net_client.py","storage.py","evidence.py","service.py","app.py","release_gate.py"]
def main()->int:
 c={f"exists:{x}":(ROOT/x).exists() for x in REQ}; app=(ROOT/"app.py").read_text(encoding="utf-8"); c["ui_uses_service"]="service" in app.lower(); c["has_domain"]=(ROOT/"domain.py").exists(); c["has_engine"]=(ROOT/"engine.py").exists(); c["has_evidence"]=(ROOT/"evidence.py").exists(); s=(ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8");
 for m in ["Requirement / Purpose Model","5 Why","Risk Boundary","Domain Model","Architecture","Data Source / NetClient","Final Gate"]: c[f"spec:{m}"]=m in s
 st="PASS" if all(c.values()) else "FAIL"; print(json.dumps({"status":st,"checks":c},indent=2)); return 0 if st=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
