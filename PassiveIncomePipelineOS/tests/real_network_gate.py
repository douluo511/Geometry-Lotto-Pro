from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.service import PipelineService,HEALTH_ENDPOINTS
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        svc=PipelineService(Path(td));r=svc.update()
        assert r["status"]=="PASS" and r["connector_health_count"]==len(HEALTH_ENDPOINTS)
        for rec in r["receipts"].values():
            assert rec["status"]==200 and rec["payload_sha256"] and rec["bytes"]>0
        core=svc.core("network-backed candidate")
        assert core["production_income_verified"] is False
    report={"status":"PASS","connector_health_count":len(HEALTH_ENDPOINTS),"raw_hash_receipts":"PASS","service":"PASS","real_income":"NOT VERIFIED","reason":"network success is not payment evidence"}
    (ROOT/"real_network_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report))
if __name__=="__main__":main()
