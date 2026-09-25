from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main()->int:
    k=json.loads((ROOT/"knowledge.json").read_text(encoding="utf-8"))
    hs=k.get("hypotheses",[])
    src=k.get("sources",[])
    keys=[h.get("key") for h in hs]
    checks={
      "business_hypothesis_depth": len(hs)>=20 and len(keys)==len(set(keys)),
      "business_competing_evidence": all(h.get("support_keywords") and h.get("contradict_keywords") for h in hs),
      "business_boundaries": all(bool(h.get("boundary")) for h in hs),
      "business_sources": len(src)>=4 and all(str(x.get("url","")).startswith("https://") for x in src),
      "business_principles": len(k.get("system_principles",[]))>=5,
      "business_reverse_validation": "reverse_validate" in (ROOT/"core.py").read_text(encoding="utf-8"),
      "business_baseline": "baseline_text" in (ROOT/"core.py").read_text(encoding="utf-8"),
      "business_no_mindreading": "不是读心" in (ROOT/"core.py").read_text(encoding="utf-8"),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"psychology-business-gate-v1","version":k.get("version"),"status":status,"hypothesis_count":len(hs),"source_count":len(src),"checks":checks}
    (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
