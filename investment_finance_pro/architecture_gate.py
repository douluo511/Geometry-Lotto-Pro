from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQUIRED=[
    "ENGINEERING_FREEZE.md","BUSINESS_SPEC.md","domain.py","contracts.py","net_client.py",
    "storage.py","engine.py","evidence.py","service.py","app.py","release_gate.py","real_network_check.py",
]

def main()->int:
    checks={f"exists:{x}":(ROOT/x).exists() for x in REQUIRED}
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    service=(ROOT/"service.py").read_text(encoding="utf-8")
    storage=(ROOT/"storage.py").read_text(encoding="utf-8")
    engine=(ROOT/"engine.py").read_text(encoding="utf-8")
    freeze=(ROOT/"ENGINEERING_FREEZE.md").read_text(encoding="utf-8")
    checks["ui_service_only"]="from service import" in app and "legacy_backend" not in app
    checks["service_no_legacy_bypass"]="legacy_backend" not in service
    checks["storage_no_legacy_bypass"]="legacy_backend" not in storage
    checks["engine_no_legacy_bypass"]="legacy_backend" not in engine
    sections={
      "purpose_model":"需求 / 目的建模",
      "five_why":"5 Why",
      "risk_boundary":"风险边界",
      "domain_model":"Domain Model",
      "architecture":"架构图",
      "function_contract":"函数清单",
      "interface_contract":"接口契约",
      "data_source":"数据源",
      "netclient":"NetClient",
      "storage":"Storage",
      "engine":"Engine",
      "evidence":"Evidence",
      "service":"Service",
      "ui":"UI",
    }
    gates={name:("PASS" if marker in freeze else "FAIL") for name,marker in sections.items()}
    status="PASS" if all(checks.values()) and all(v=="PASS" for v in gates.values()) else "FAIL"
    report={"schema":"investment-finance-architecture-gate-v2","status":status,"checks":checks,"gates":gates}
    (ROOT/"architecture_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
