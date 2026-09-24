import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FILES=["ENGINEERING_SPEC.md","domain.py","net_client.py","storage.py","engine.py","evidence.py","service.py","contracts.py","release_gate.py","real_network_check.py","app.py","tests/test_contracts.py","tests/test_fault_injection.py"]
TERMS=["需求/目的建模","5 Why","风险边界","Domain Model","架构图","函数清单","接口契约","数据源","NetClient","Storage","Engine","Evidence","Service","UI","Self-Test","Contract Test","Fault Injection","Real Network","Windows Build","Exact EXE","GUI Smoke","Same Hash","Final Gate","唯一成品"]
def main():
    checks={f"file:{p}":(ROOT/p).exists() for p in FILES}; spec=(ROOT/"ENGINEERING_SPEC.md").read_text(encoding="utf-8")
    checks.update({f"spec:{t}":t in spec for t in TERMS}); app=(ROOT/"app.py").read_text(encoding="utf-8")
    checks["ui_routes_through_service"]="from service import GuoxueService" in app; checks["ui_no_direct_engine"]="from engine import" not in app; checks["ui_no_direct_storage"]="from storage import" not in app; checks["ui_no_direct_netclient"]="from net_client import" not in app
    status="PASS" if all(checks.values()) else "FAIL"; print(json.dumps({"status":status,"checks":checks},ensure_ascii=False)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
