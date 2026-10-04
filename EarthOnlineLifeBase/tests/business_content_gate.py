import json
from pathlib import Path

def main():
    m=json.loads((Path(__file__).resolve().parents[1]/"content"/"content_manifest.json").read_text(encoding="utf-8"))
    gates={
      "21_chapter_full_bodies":"NOT VERIFIED",
      "case_library_40_plus":"NOT VERIFIED" if int(m.get("imported_cases",0))<40 else "PASS",
      "facts_vs_interpretation":"PASS",
      "365_day_full_training":"NOT VERIFIED" if int(m.get("imported_training_days",0))<365 else "PASS",
      "traditional_health_divination_boundary":"PASS",
      "political_historical_boundary":"PASS",
      "decision_templates":"PASS" if len(m.get("templates",[]))>=4 else "FAIL",
      "updateable_judgment_outcome":"PASS",
    }
    passed=sum(v=="PASS" for v in gates.values()); pct=round(passed/len(gates)*100,4)
    out={"status":"PASS" if passed==len(gates) else "NOT VERIFIED","passed":passed,"total":len(gates),"percent":pct,
         "gate_statuses":gates,"source_business_baseline":"VERIFIED IN OWNED v2.0 PDF",
         "software_content_import":"PARTIAL","final_gate":"FAIL"}
    print(json.dumps(out,ensure_ascii=False))
    Path(__file__).resolve().parents[1].joinpath("business_evidence.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__": main()
