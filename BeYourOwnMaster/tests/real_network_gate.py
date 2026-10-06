from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.service import MasterService,OFFICIAL_REFERENCES
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        svc=MasterService(Path(td)); result=svc.update()
        assert result["status"]=="PASS" and result["source_count"]==len(OFFICIAL_REFERENCES)
        for rec in result["receipts"].values():
            assert rec["status"]==200 and rec["payload_sha256"] and rec["bytes"]>0
        assert svc.core("真实网络后的训练")["status"]=="PASS"
    report={"status":"PASS","official_reference_count":len(OFFICIAL_REFERENCES),"raw_hash_receipts":"PASS","study_service":"PASS","note":"authority availability only; not individualized professional advice"}
    (ROOT/"real_network_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
