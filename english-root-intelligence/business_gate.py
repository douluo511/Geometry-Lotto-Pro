from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main()->int:
    roots=json.loads((ROOT/"data"/"roots.json").read_text(encoding="utf-8"))
    catalog=json.loads((ROOT/"data"/"root_catalog.json").read_text(encoding="utf-8"))
    active=roots.get("roots",[])
    entries=catalog.get("entries",[])
    ids=[f"{x.get('type')}:{x.get('morpheme')}" for x in entries]
    sources=roots.get("sources",[])
    checks={
        "business_scope": {x.get("type") for x in entries} >= {"prefix","root","suffix"},
        "business_catalog_252": len(entries) >= 252 and len(ids)==len(set(ids)),
        "business_active_families": len(active) >= 36,
        "business_word_depth": all(isinstance(x.get("words"),list) and len(x["words"])>=3 for x in active),
        "business_chunk_depth": all(isinstance(x.get("chunks"),list) and len(x["chunks"])>=3 for x in active),
        "business_provenance": len(sources) >= 3 and all(x.get("url") for x in sources),
        "business_uncertainty_boundary": "需要结合词典语境确认" in (ROOT/"core.py").read_text(encoding="utf-8"),
        "business_update_integrity": "sha256" in (ROOT/"service.py").read_text(encoding="utf-8").lower() and "replace_roots" in (ROOT/"service.py").read_text(encoding="utf-8"),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"english-root-business-gate-v1","version":roots.get("version"),"status":status,"active_families":len(active),"catalog_entries":len(entries),"checks":checks}
    (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
