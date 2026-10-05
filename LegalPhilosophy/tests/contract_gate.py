from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from app.domain import SourceDocument, validate_result, validate_source
from app.engine import build_study_result, classify_section
from app.netclient import NetClient
from app.storage import Storage


def doc(source_id: str, role: str) -> SourceDocument:
    return SourceDocument(
        source_id=source_id,title=source_id,url="https://example.invalid/"+source_id,role=role,
        retrieved_at="2026-10-04T00:00:00+00:00",payload_sha256="a"*64,text_sha256="b"*64,
        content_type="text/html",validation_status="PASS",marker_hits=("marker",)
    )


def main() -> int:
    scholarship=doc("scholarship","AUTHORITATIVE_SCHOLARSHIP")
    authority=doc("authority","LEGAL_AUTHORITY")
    validate_source(scholarship)
    validate_source(authority)
    result=build_study_result("国家与自由之间有什么关系？",[scholarship,authority])
    validate_result(result)
    assert classify_section("财产权与契约")=="Abstract Right"
    assert classify_section("贫困与市民社会")=="Civil Society"
    assert "legal advice" in result.boundary.lower()
    assert len(result.five_why)==5 and result.reversal_tests and result.counterexample_prompts

    with tempfile.TemporaryDirectory() as td:
        store=Storage(Path(td))
        client=NetClient(store.evidence/"network.jsonl",max_attempts=1)
        try:
            client.get_text("http://example.com")
            raise AssertionError("HTTP source was accepted")
        except ValueError:
            pass
        # Storage rejects mismatched canonical/raw identity.
        bad=replace(scholarship,text_sha256="c"*64)
        try:
            store.persist_source(bad,"not-the-declared-hash")
            raise AssertionError("hash mismatch was accepted")
        except ValueError:
            pass

    report={
        "status":"PASS",
        "interface_contracts":"PASS",
        "domain_invariants":"PASS",
        "engine_boundary":"PASS",
        "claim_layer_separation":"PASS",
        "educational_not_legal_advice":"PASS",
        "five_why_reversal":"PASS",
    }
    Path("contract_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
