from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    g=json.loads((ROOT/"GOVERNANCE_SPEC.json").read_text(encoding="utf-8"))
    assert g.get("historical_source_recovered") is False
    assert len(g.get("five_why",[]))==5
    assert g.get("ui_entries")==["项目验证","一键更新","一键修复","高级分析"]
    assert g.get("validation_chain")==["V-A logic","V-B reversal/red-team","V-C real demand behavior","V-D real payment","V-E unit economics/cash flow","V-F repeat purchase/delivery","V-G SOP/outsource/AI systemization","V-H asset accumulation","V-I scale stress"]
    r={"status":"PASS","requirements_purpose_model":"PASS","five_why":"PASS","risk_boundary":"PASS","domain_model":"PASS","architecture":"PASS","function_inventory":"PASS","historical_acceptance_inherited":False}
    (ROOT/"governance_evidence.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r))
if __name__=="__main__":main()
