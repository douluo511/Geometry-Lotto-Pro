from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from service import create_service
ROOT=Path(__file__).resolve().parent
def main()->int:
    with tempfile.TemporaryDirectory(prefix="guoxue-business-") as td:
        svc=create_service(Path(td))
        negotiation=svc.analyze_goal("我要和长期合作伙伴谈价格，怎样判断底线、筹码和风险？")
        health=svc.analyze_goal("我想研究古代养生思想，但如何避免把古代经验当成现代医学结论？")
        checks={
          "action_hypothesis":negotiation.get("status")=="ACTION_HYPOTHESIS" and health.get("status")=="ACTION_HYPOTHESIS",
          "multiple_classical_views":len(negotiation.get("methods") or [])>=3,
          "facts_before_action":len(negotiation.get("questions") or [])>=3,
          "five_why":len(negotiation.get("five_whys") or [])==5,
          "counterexample_prompts":len(negotiation.get("reverse_validation") or [])>=3,
          "source_and_boundary":all(bool(x.get("source_note")) and bool(x.get("boundary")) for x in negotiation.get("methods") or []),
          "health_boundary":any("医学" in str(x.get("boundary","")) or "健康" in str(x.get("boundary","")) for x in health.get("methods") or []),
          "review_roundtrip":svc.save_review("谈合作","确认替代方案","拿到真实预算","下次先验证时间压力").get("goal")=="谈合作",
        }
        status="PASS" if all(checks.values()) else "FAIL"
        report={"schema":"guoxue-business-validation-v1","status":status,"github_sha":os.environ.get("GITHUB_SHA"),"business_validation":status,"counterexample_validation":"PASS" if checks["counterexample_prompts"] and checks["source_and_boundary"] else "FAIL","reversal_validation":"PASS" if checks["counterexample_prompts"] and checks["action_hypothesis"] else "FAIL","checks":checks}
    (ROOT/"business_validation_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
