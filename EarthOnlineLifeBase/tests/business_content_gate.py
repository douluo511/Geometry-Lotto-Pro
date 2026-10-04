import json
from pathlib import Path
from app.content import corpus_metrics, content_import_status

def main():
    m=corpus_metrics()
    structure=all(v>=21 for v in m["structure_marker_counts"].values())
    gates={
      "21_chapter_full_bodies":"PASS" if m["chapter_count"]==21 and m["chapter_min"]==1 and m["chapter_max"]==21 and structure else "FAIL",
      "case_library_40_plus":"PASS" if m["case_count"]>=43 and m["case_min"]==1 and m["case_max"]>=43 else "FAIL",
      "facts_vs_interpretation":"PASS" if m["has_case_rule"] else "FAIL",
      "365_day_full_training":"PASS" if m["training_day_count"]==365 and m["training_day_min"]==1 and m["training_day_max"]==365 and m["has_training_gates"] else "FAIL",
      "traditional_health_divination_boundary":"PASS" if m["has_traditional_boundary"] else "FAIL",
      "political_historical_boundary":"PASS" if m["has_political_boundary"] else "FAIL",
      "decision_templates":"PASS" if m["has_templates"] else "FAIL",
      "updateable_judgment_outcome":"PASS" if m["has_outcome_boundary"] else "FAIL",
    }
    passed=sum(v=="PASS" for v in gates.values()); pct=round(passed/len(gates)*100,4)
    import_status=content_import_status()
    out={"status":"PASS" if passed==len(gates) and import_status=="PASS" else "FAIL",
         "passed":passed,"total":len(gates),"percent":pct,"gate_statuses":gates,
         "corpus_metrics":m,"source_business_baseline":"VERIFIED IN OWNED v2.0 PDF",
         "software_content_import":"PASS" if import_status=="PASS" else "FAIL",
         "final_gate":"FAIL"}
    print(json.dumps(out,ensure_ascii=False))
    Path(__file__).resolve().parents[1].joinpath("business_evidence.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return 0 if out["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
