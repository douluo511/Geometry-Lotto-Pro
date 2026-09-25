from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main()->int:
    import sys
    sys.path.insert(0,str(ROOT/"SSQ"))
    from glp.constants import FRONT_MAX,FRONT_PICK,BACK_MAX,BACK_PICK,FOUR_ENTRIES,PROMOTION_POLICY,SOURCE_NAMES
    engine=(ROOT/"SSQ"/"glp"/"engine.py").read_text(encoding="utf-8")
    evidence=(ROOT/"SSQ"/"glp"/"evidence.py").read_text(encoding="utf-8")
    service=(ROOT/"SSQ"/"glp"/"service.py").read_text(encoding="utf-8")
    source=(ROOT/"SSQ"/"glp"/"sources.py").read_text(encoding="utf-8")
    models=["simple_frequency","recency","gap","transition","pair_graph","geometry_state","geometry_transition","research_ensemble"]
    p=PROMOTION_POLICY
    checks={
      "business_game_contract": (FRONT_MAX,FRONT_PICK,BACK_MAX,BACK_PICK)==(33,6,16,1),
      "business_official_sources": set(SOURCE_NAMES)=={"national","shanghai","hebei"} and "SourceError" in source,
      "business_four_entries": tuple(FOUR_ENTRIES)==("预测下一期","一键更新","一键修复","高级分析"),
      "business_model_inventory": all(m in engine or m in evidence for m in models),
      "business_walk_forward": int(p["min_walk_forward"])>=1200 and int(p["min_prospective"])>=120 and int(p["min_era_count"])>=3,
      "business_statistics": float(p["alpha"])<=0.01 and int(p["bootstrap_rounds"])>=1000 and int(p["permutation_rounds"])>=1000 and int(p["null_worlds"])>=300,
      "business_ablation": set(p["ablation_modes"])=={"remove","shuffle","random_replace"},
      "business_leakage_and_confirmation": "leakage" in evidence.lower() and "dual_confirmation" in evidence,
      "business_freeze_audit_isolation": "formal_freeze_written" in service and "freeze" in service.lower(),
      "business_no_overclaim": "NULL_DAN" in service or "NO_EDGE" in service,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"ssq-business-gate-v1","status":status,"policy":p,"checks":checks}
    out=ROOT/"evidence"/"SSQ"/"BUSINESS_GATE.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
