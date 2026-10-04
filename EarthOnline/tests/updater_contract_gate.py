from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.updater import check_context
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);assert check_context(root)["status"]=="BLOCKED"
        (root/"updater.json").write_text(json.dumps({"enabled":True,"repository":"douluo511/Geometry-Lotto-Pro","manifest_url":"https://example.com/m","trusted_public_key_hex":"00"*32}),encoding="utf-8")
        assert check_context(root)["status"]=="BLOCKED"
    r={"status":"PASS","missing_context_blocked":"PASS","shared_repo_rejected":"PASS","positive_production_update":"BLOCKED"}
    (ROOT/"updater_contract_evidence.json").write_text(json.dumps(r,indent=2),encoding="utf-8");print(json.dumps(r))
if __name__=="__main__":main()
