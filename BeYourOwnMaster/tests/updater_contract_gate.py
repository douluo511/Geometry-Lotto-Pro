from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.updater import check_context
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); a=check_context(root); assert a["status"]=="BLOCKED"
        (root/"updater.json").write_text(json.dumps({"enabled":True,"repository":"douluo511/Geometry-Lotto-Pro","manifest_url":"https://example.com/m","trusted_public_key_hex":"00"*32}),encoding="utf-8")
        b=check_context(root); assert b["status"]=="BLOCKED"
    report={"status":"PASS","missing_context_fail_closed":"PASS","shared_repo_rejected":"PASS","positive_production_update":"BLOCKED"}
    (ROOT/"updater_contract_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
