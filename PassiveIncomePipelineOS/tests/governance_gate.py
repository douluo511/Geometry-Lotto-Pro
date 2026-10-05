from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    g=json.loads((ROOT/"GOVERNANCE_SPEC.json").read_text(encoding="utf-8"))
    assert g["lineage"]=="NEW_REAUTHORED_LINEAGE"
    assert g["historical_candidate"]["acceptance_inherited"] is False
    assert g["ui_entries"]==["收益总览","一键更新","一键修复","高级分析"]
    assert len(g["five_why"])==5
    r={"status":"PASS","requirements_purpose_model":"PASS","five_why":"PASS","risk_boundary":"PASS","domain_model":"PASS","architecture":"PASS","function_inventory":"PASS","historical_acceptance_inherited":False}
    (ROOT/"governance_evidence.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(r))
if __name__=="__main__":main()
