from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
def main()->int:
    drills=json.loads((ROOT/"data/drills.json").read_text(encoding="utf-8"))
    cases=json.loads((ROOT/"data/cases.json").read_text(encoding="utf-8"))
    sources=json.loads((ROOT/"data/sources.json").read_text(encoding="utf-8"))
    knowledge=json.loads((ROOT/"data/knowledge.json").read_text(encoding="utf-8"))
    domains={urlparse(x["url"]).netloc.lower() for x in sources}
    mechanisms={x.get("mechanism") for x in drills}
    checks={
      "drill_depth":len(drills)>=180,
      "case_depth":len(cases)>=60,
      "source_depth":len(sources)>=3,
      "independent_source_domains":len(domains)>=3,
      "six_mechanisms":len(mechanisms)>=6,
      "seven_dimensions":len(knowledge.get("scoring_dimensions",[]))==7,
      "provenance":len(knowledge.get("provenance",[]))>=2 and "re-authored" in knowledge.get("reconstruction_policy","").lower(),
      "guardrails":len(knowledge.get("guardrails",[]))>=5,
      "case_boundaries":all(x.get("boundary") and x.get("reversal_question") for x in cases),
      "drill_acceptance":all(len(x.get("acceptance",[]))>=4 for x in drills),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    r={"schema":"talkcraft-business-gate-v1","status":status,"checks":checks,"drills":len(drills),"cases":len(cases),"sources":len(sources),"domains":sorted(domains)}
    (ROOT/"business_gate.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
