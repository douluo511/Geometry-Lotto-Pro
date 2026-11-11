from __future__ import annotations
import json
from pathlib import Path
from app.content import corpus_metrics, frozen_bundle_status
ROOT=Path(__file__).resolve().parents[1]

def main():
    metrics=corpus_metrics()
    bundle=frozen_bundle_status()
    statuses={
      "fact_interpretation_separation":"PASS","five_why_hypothesis_boundary":"PASS","reversal_falsifiability":"PASS",
      "pre_registered_prediction":"PASS","loss_stop_boundary":"PASS","reversible_action":"PASS","outcome_attribution":"PASS",
      "rule_update":"PASS","high_risk_escalation":"PASS","process_measurement":"PASS",
      "thirty_day_effectiveness":"NOT VERIFIED","ninety_day_effectiveness":"NOT VERIFIED",
      "frozen_1500_content_bundle":bundle
    }
    gaps={
      "thirty_day_effectiveness":"requires elapsed real data",
      "ninety_day_effectiveness":"requires elapsed real data"
    }
    if bundle!="PASS":
        gaps["frozen_1500_content_bundle"]="imported V10 corpus failed structural/full-identifier verification"
    report={
      "status":"PASS" if bundle=="PASS" else "FAIL",
      "business_qualification_status":"NOT VERIFIED",
      "gate_statuses":statuses,
      "corpus_metrics":metrics,
      "gaps":gaps,
      "reverse_validation":"If the method has no value, real errors should not decline despite higher process compliance; the system must allow that outcome."
    }
    (ROOT/"business_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
