from __future__ import annotations
import json, os
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main()->int:
    kb=json.loads((ROOT/"data"/"knowledge.json").read_text(encoding="utf-8"))
    classics=kb.get("classics") or []
    core=(ROOT/"core.py").read_text(encoding="utf-8")
    checks={
      "business_scope":len(classics)>=20,
      "business_source_notes":all(bool(str(x.get("source_note","")).strip()) for x in classics),
      "business_boundaries":all(bool(str(x.get("boundary","")).strip()) for x in classics),
      "business_methods":all(isinstance(x.get("methods"),list) and len(x["methods"])>=1 for x in classics),
      "business_scenarios":all(isinstance(x.get("scenarios"),list) and len(x["scenarios"])>=1 for x in classics),
      "business_disputed_texts_surface":sum(1 for x in classics if x.get("authorship_status") not in (None,"常规传世文本"))>=1,
      "business_five_why":"five_whys" in core and "reverse_validation" in core,
      "business_action_hypothesis":"ACTION_HYPOTHESIS" in core,
      "business_health_boundary":"不替代现代医学" in (ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8"),
      "business_update_integrity":"commit_network_update" in core and "knowledge_sha256" in core,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"guoxue-business-gate-v1","status":status,"github_sha":(os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),"version":kb.get("version"),"classics":len(classics),"checks":checks}
    (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
