from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REQ=[
    "BUSINESS_SPEC.md","ENGINEERING_FREEZE.md","app.py","TalkCraftPro.spec",
    "talkcraft/domain.py","talkcraft/engine/scoring.py","talkcraft/engine/reversal.py",
    "talkcraft/engine/training.py","talkcraft/net/client.py",
    "talkcraft/storage/sqlite_store.py","talkcraft/service/training_service.py",
    "talkcraft/service/self_test.py","talkcraft/ui/main_window.py",
    "data/drills.json","data/cases.json","data/sources.json","data/knowledge.json",
]
def main()->int:
    checks={f"exists:{p}":(ROOT/p).exists() for p in REQ}
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    service=(ROOT/"talkcraft/service/training_service.py").read_text(encoding="utf-8")
    net=(ROOT/"talkcraft/net/client.py").read_text(encoding="utf-8")
    freeze=(ROOT/"ENGINEERING_FREEZE.md").read_text(encoding="utf-8")
    checks["ui_service_only"]="TrainingService" in app and "TalkCraftApp" in app
    checks["service_layers"]=all(x in service for x in ("TrainingEngine","NetClient","Store","analyze_text","compare_variants"))
    checks["strict_netclient_tokens"]=all(x in net for x in ("connect_timeout","read_timeout","RETRY_HTTP","RETRY_EXCEPTION","FINAL_INSECURE_REDIRECT","body_b64","requested_url","final_url"))
    gates={
      "purpose_model":"PASS" if "Business Purpose" in (ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8") else "FAIL",
      "five_why":"PASS" if "5 Why" in (ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8") else "FAIL",
      "risk_boundary":"PASS" if "Risk Boundary" in (ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8") else "FAIL",
      "domain_model":"PASS" if (ROOT/"talkcraft/domain.py").exists() else "FAIL",
      "architecture":"PASS" if "Frozen sequence" in freeze else "FAIL",
      "function_contract":"PASS" if (ROOT/"talkcraft/service/training_service.py").exists() else "FAIL",
      "interface_contract":"PASS" if "四入口" in (ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8") else "FAIL",
      "data_source":"PASS" if (ROOT/"data/sources.json").exists() else "FAIL",
      "netclient":"PASS" if checks["strict_netclient_tokens"] else "FAIL",
      "storage":"PASS" if (ROOT/"talkcraft/storage/sqlite_store.py").exists() else "FAIL",
      "engine":"PASS" if (ROOT/"talkcraft/engine/scoring.py").exists() else "FAIL",
      "evidence":"PASS" if "save_evidence" in service else "FAIL",
      "service":"PASS" if checks["service_layers"] else "FAIL",
      "ui":"PASS" if checks["ui_service_only"] else "FAIL",
    }
    status="PASS" if all(checks.values()) and all(v=="PASS" for v in gates.values()) else "FAIL"
    r={"schema":"talkcraft-architecture-gate-v1","status":status,"checks":checks,"gates":gates}
    (ROOT/"architecture_gate.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
