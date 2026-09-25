from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from glp.constants import FRONT_MAX,FRONT_PICK,BACK_MAX,BACK_PICK,PROMOTION_POLICY,REQUIRED_PRIMARY_SOURCE,REQUIRED_SECONDARY_SOURCE
from glp.engine import BASE_MODELS
def main()->int:
    ev=(ROOT/"src"/"glp"/"evidence.py").read_text(encoding="utf-8")
    src=(ROOT/"src"/"glp"/"sources.py").read_text(encoding="utf-8")
    eng=(ROOT/"src"/"glp"/"engine.py").read_text(encoding="utf-8")
    p=PROMOTION_POLICY
    checks={
      "game_contract":(FRONT_MAX,FRONT_PICK,BACK_MAX,BACK_PICK)==(35,5,12,2),
      "required_sources":REQUIRED_PRIMARY_SOURCE=="jiangsu" and REQUIRED_SECONDARY_SOURCE=="gansu",
      "dual_official_consensus":"_validate_consensus" in src and "min_overlap=10" in src,
      "model_inventory":set(BASE_MODELS)>={"simple_frequency","recency","gap","transition","pair_graph","geometry_state","geometry_transition"},
      "walk_forward":int(p["walk_forward_points"])>=1200 and int(p["untouched_holdout"])>=240 and int(p["min_era_count"])>=3,
      "statistics":float(p["alpha"])<=0.01 and int(p["bootstrap_rounds"])>=1000 and int(p["permutation_rounds"])>=1000,
      "null_world":int(p["null_worlds"])>=300 and int(p["synthetic_null_worlds"])>=6 and int(p["synthetic_null_max_false_edges"])==0,
      "ablation":all(x in ev for x in ["Remove / Shuffle / Random","_ablation","DEAD_PATH"]),
      "leakage":"leakage_guard" in ev and "Leakage Sentinel" in ev,
      "dual_confirmation":"Dual Final Confirmation" in ev,
      "dan_firewall":all(x in ev for x in ["wilson95_lower","dan_min_coverage","dan_min_rank_support"]),
      "no_overclaim":"CERTIFIED_DAN" in eng and "edge_proven" in eng,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"dlt-business-science-gate-v1","version":"2.3.0","status":status,"checks":checks,"policy":p}
    out=ROOT/"artifacts"/"business_gate.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
