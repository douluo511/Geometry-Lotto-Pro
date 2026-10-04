from __future__ import annotations
import json
from pathlib import Path
import tempfile

from app.service import LegalPhilosophyService


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        service=LegalPhilosophyService(Path(td))
        update=service.update()
        study=service.study("国家与自由之间有什么关系？")
        advanced=service.advanced()
        index=service.storage.load_index(validate_raw=True)
        assert update["status"]=="PASS" and len(index)==2
        assert advanced["scholarship_lineage"]=="PASS"
        assert advanced["legal_authority_lineage"]=="PASS"
        assert advanced["primary_source_lineage"]=="NOT VERIFIED"
        assert study["status"]=="PASS" and len(study["source_refs"])==2
        receipts=(service.storage.evidence/"network.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(receipts)>=2
        parsed=[json.loads(line) for line in receipts]
        assert all(item["result"]=="PASS" for item in parsed[-2:])
        result={
            "status":"PASS",
            "source_count":2,
            "sources":update["sources"],
            "raw_canonical_integrity":"PASS",
            "study_service":"PASS",
            "advanced_analysis":"PASS",
            "primary_source_lineage":"NOT VERIFIED",
            "network_receipts":parsed,
        }
    Path("real_network_evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
