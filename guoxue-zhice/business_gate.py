from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main()->int:
 k=json.loads((ROOT/"data"/"knowledge.json").read_text(encoding="utf-8")); rows=k.get("classics",[])
 methods=sum(len(x.get("methods",[])) for x in rows); scenarios={s for x in rows for s in x.get("scenarios",[])}
 e=(ROOT/"engine.py").read_text(encoding="utf-8"); s=(ROOT/"service.py").read_text(encoding="utf-8")
 checks={"classic_depth":len(rows)>=20,"method_depth":methods>=60,"scenario_coverage":len(scenarios)>=9,"provenance":all(x.get("source_note") and x.get("boundary") for x in rows) and bool(k.get("sources")),"case_counterexample":all(x.get("case_prompt") and x.get("counterexample_prompt") for x in rows),"multi_method_engine":"row[\"methods\"][:2]" in e,"no_downgrade":"NOOP_OLDER_REMOTE" in s,"reverse_validation":"reverse_validation" in e and "five_whys" in e}
 status="PASS" if all(checks.values()) else "FAIL"; report={"schema":"guoxue-business-gate-v1","version":k.get("version"),"status":status,"classic_count":len(rows),"method_count":methods,"checks":checks}
 (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=True)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
