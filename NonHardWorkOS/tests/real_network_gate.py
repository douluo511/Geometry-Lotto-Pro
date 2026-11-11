from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.service import NonHardWorkService,REFERENCES
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        svc=NonHardWorkService(Path(td)); result=svc.update()
        assert result["status"]=="PASS" and result["source_count"]==len(REFERENCES)
        for rec in result["receipts"].values():
            assert rec["status"]==200 and rec["payload_sha256"] and rec["bytes"]>0
        core=svc.core("真实市场验证候选")
        assert core["business_gate_statuses"]["real_payment"]=="NOT VERIFIED"
    report={"status":"PASS","official_reference_count":len(REFERENCES),"raw_hash_receipts":"PASS","service":"PASS","commercial_validation":"NOT VERIFIED","reason":"reference availability cannot substitute for customer/payment evidence"}
    (ROOT/"real_network_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report))
if __name__=="__main__":main()
