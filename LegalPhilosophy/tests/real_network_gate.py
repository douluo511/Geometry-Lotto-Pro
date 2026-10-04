from __future__ import annotations
import json
from pathlib import Path
import tempfile

from app.service import LegalPhilosophyService
from app.sources import SOURCE_SPECS


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        service=LegalPhilosophyService(Path(td))
        update=service.update()
        study=service.study("国家与自由之间有什么关系？")
        advanced=service.advanced()
        index=service.storage.load_index(validate_raw=True)

        expected_ids={spec["source_id"] for spec in SOURCE_SPECS}
        expected_urls={spec["url"] for spec in SOURCE_SPECS}
        assert update["status"]=="PASS"
        assert set(index)==expected_ids
        assert update["source_count"]==len(expected_ids)
        assert advanced["scholarship_lineage"]=="PASS"
        assert advanced["legal_authority_lineage"]=="PASS"
        assert advanced["source_conflict_handling"]=="PASS"
        assert advanced["case_source_lineage"]=="PASS"
        assert advanced["case_boundary"]=="PASS"
        # Edition/section-level Hegel primary text is deliberately not promoted by metadata or a scan identity alone.
        assert advanced["primary_source_lineage"]=="NOT VERIFIED"
        assert study["status"]=="PASS" and set(study["source_refs"])==expected_ids

        receipt_lines=(service.storage.evidence/"network.jsonl").read_text(encoding="utf-8").splitlines()
        parsed=[json.loads(line) for line in receipt_lines]
        verified_receipts=[]
        for url in sorted(expected_urls):
            successes=[item for item in parsed if item.get("url")==url and item.get("result")=="PASS"]
            assert successes, f"missing successful current network receipt for {url}"
            verified_receipts.append(successes[-1])

        result={
            "status":"PASS",
            "source_count":len(expected_ids),
            "expected_source_ids":sorted(expected_ids),
            "sources":update["sources"],
            "raw_canonical_integrity":"PASS",
            "study_service":"PASS",
            "advanced_analysis":"PASS",
            "source_conflict_handling":advanced["source_conflict_handling"],
            "case_source_lineage":advanced["case_source_lineage"],
            "primary_source_lineage":"NOT VERIFIED",
            "verified_network_receipts":verified_receipts,
            "network_receipts":parsed,
        }
    Path("real_network_evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
