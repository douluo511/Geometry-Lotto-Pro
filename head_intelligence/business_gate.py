from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main()->int:
 from head_intelligence.engine import DEFAULT_SOURCES
 e=(ROOT/"engine.py").read_text(encoding="utf-8"); ev=(ROOT/"evidence.py").read_text(encoding="utf-8"); n=(ROOT/"net_client.py").read_text(encoding="utf-8")
 ids={x.id for x in DEFAULT_SOURCES}
 checks={
  "source_depth":len(DEFAULT_SOURCES)>=4,
  "source_families":{"federal_reserve_press","sec_press","bls_latest","bea_releases"}.issubset(ids),
  "strict_network_pass":"all_sources_pass" in e,
  "no_failed_overwrite":"if status == \"PASS\"" in e,
  "deduplication":"deduplicate" in e,
  "topic_classification":"classify_topic" in ev and "category=" in e,
  "corroboration":"corroboration_count" in e,
  "network_receipts":all(x in n for x in ["http_status","content_type","payload_hash","fetched_at"]),
  "decision_relevance":"decision_relevance" in ev,
 }
 status="PASS" if all(checks.values()) else "FAIL"
 report={"schema":"head-intelligence-business-gate-v1","status":status,"source_count":len(DEFAULT_SOURCES),"checks":checks}
 (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps(report,ensure_ascii=True)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
