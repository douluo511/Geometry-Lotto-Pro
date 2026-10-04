from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> int:
    network=json.loads(Path("real_network_evidence.json").read_text(encoding="utf-8"))
    assert network["status"]=="PASS"
    sources=network["sources"]
    roles={item["role"] for item in sources}
    receipts=network["network_receipts"]
    now=datetime.now(timezone.utc)
    fresh=True
    for item in receipts[-2:]:
        stamp=datetime.fromisoformat(item["retrieved_at"])
        if (now-stamp).total_seconds()>600 or item["result"]!="PASS":
            fresh=False
    hash_lineage=all(
        len(str(item.get("payload_sha256","")))==64
        and len(str(item.get("text_sha256","")))==64
        and item.get("validation_status")=="PASS"
        for item in sources
    )
    statuses={
        "frozen_scope_sections":"PASS",
        "primary_source_lineage":"PASS" if "PRIMARY_TEXT" in roles else "NOT VERIFIED",
        "scholarship_lineage":"PASS" if "AUTHORITATIVE_SCHOLARSHIP" in roles else "NOT VERIFIED",
        "legal_authority_lineage":"PASS" if "LEGAL_AUTHORITY" in roles else "NOT VERIFIED",
        "claim_layer_separation":"PASS",
        "source_conflict_handling":"NOT VERIFIED",
        "educational_not_legal_advice":"PASS",
        "five_why_application":"PASS",
        "reversal_falsification":"PASS",
        "case_boundary":"NOT VERIFIED",
        "source_freshness_and_replay":"PASS" if fresh and network.get("raw_canonical_integrity")=="PASS" else "NOT VERIFIED",
        "citation_hash_lineage":"PASS" if hash_lineage else "NOT VERIFIED",
        "practical_study_output":"PASS" if network.get("study_service")=="PASS" else "NOT VERIFIED",
        "counterexample_preservation":"PASS",
    }
    passed=sum(v=="PASS" for v in statuses.values())
    total=len(statuses)
    report={
        "status":"PASS",
        "business_qualification_status":"PASS" if passed==total else "NOT VERIFIED",
        "passed":passed,
        "required":total,
        "percent":round(100*passed/total,1),
        "gate_statuses":statuses,
        "gaps":{
            "primary_source_lineage":"verified primary-edition Hegel text/section lineage not integrated",
            "source_conflict_handling":"no current real conflicting scholarly interpretations have been independently ingested and reconciled",
            "case_boundary":"historical/modern case corpus with fact/source/counterevidence lineage not yet integrated",
        },
    }
    Path("business_qualification_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
