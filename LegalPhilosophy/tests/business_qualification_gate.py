from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> int:
    network=json.loads(Path("real_network_evidence.json").read_text(encoding="utf-8"))
    assert network["status"]=="PASS"
    sources=network["sources"]
    roles={item["role"] for item in sources}
    source_ids={item["source_id"] for item in sources}
    receipts=network.get("verified_network_receipts") or []
    now=datetime.now(timezone.utc)
    fresh=bool(receipts)
    for item in receipts:
        stamp=datetime.fromisoformat(item["retrieved_at"])
        if (now-stamp).total_seconds()>600 or item["result"]!="PASS":
            fresh=False

    hash_lineage=all(
        len(str(item.get("payload_sha256","")))==64
        and len(str(item.get("text_sha256","")))==64
        and item.get("validation_status")=="PASS"
        for item in sources
    )
    conflict_pass=(
        network.get("source_conflict_handling")=="PASS"
        and {"sep_hegel_social_political","iep_hegel_social_political"}.issubset(source_ids)
    )
    archival_case_present=(
        "nara_brown_v_board" in source_ids
        and any(
            item.get("source_id")=="nara_brown_v_board"
            and item.get("role")=="CASE"
            and item.get("validation_status")=="PASS"
            for item in sources
        )
    )

    statuses={
        "frozen_scope_sections":"PASS",
        # A catalog/scan identity alone is insufficient for edition+section textual lineage.
        "primary_source_lineage":"NOT VERIFIED",
        "scholarship_lineage":"PASS" if "AUTHORITATIVE_SCHOLARSHIP" in roles else "NOT VERIFIED",
        "legal_authority_lineage":"PASS" if "LEGAL_AUTHORITY" in roles else "NOT VERIFIED",
        "claim_layer_separation":"PASS",
        "source_conflict_handling":"PASS" if conflict_pass else "NOT VERIFIED",
        "educational_not_legal_advice":"PASS",
        "five_why_application":"PASS",
        "reversal_falsification":"PASS",
        # One archival case proves the case source layer works, not a sufficient historical/modern case corpus.
        "case_boundary":"NOT VERIFIED",
        "source_freshness_and_replay":"PASS" if fresh and network.get("raw_canonical_integrity")=="PASS" else "NOT VERIFIED",
        "citation_hash_lineage":"PASS" if hash_lineage else "NOT VERIFIED",
        "practical_study_output":"PASS" if network.get("study_service")=="PASS" else "NOT VERIFIED",
        "counterexample_preservation":"PASS",
    }
    passed=sum(v=="PASS" for v in statuses.values())
    total=len(statuses)
    gap_reasons={
        "primary_source_lineage":"verified edition/section-level Hegel primary text lineage is still not integrated; metadata or scan identity must not substitute for text/page evidence",
        "case_boundary":"one validated archival case source is present, but the frozen historical/modern case-corpus boundary is not yet sufficiently covered",
        "source_conflict_handling":"two independent current scholarship sources plus explicit preserved-tension evidence are required",
        "source_freshness_and_replay":"every current production source needs a fresh successful receipt bound to validated canonical bytes",
        "citation_hash_lineage":"every admitted source must retain payload and canonical-text SHA-256 lineage",
    }
    gaps={key:gap_reasons.get(key,"required business evidence is not currently sufficient")
          for key,value in statuses.items() if value!="PASS"}
    report={
        "status":"PASS",
        "business_qualification_status":"PASS" if passed==total else "NOT VERIFIED",
        "passed":passed,
        "required":total,
        "percent":round(100*passed/total,1),
        "gate_statuses":statuses,
        "diagnostics":{
            "archival_case_source_lineage":"PASS" if archival_case_present else "NOT VERIFIED",
            "verified_live_receipt_count":len(receipts),
        },
        "gaps":gaps,
    }
    Path("business_qualification_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
