from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.netclient import NetClient
from app.storage import Storage
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        s=Storage(Path(td)); p=s.canonical/"experiments.jsonl"; p.write_text("{broken",encoding="utf-8")
        x=s.repair(); assert x["status"]=="PASS" and x["quarantined"] and x["user_data_deleted"] is False
        n=NetClient(s.evidence/"network.jsonl")
        try:n.get("http://example.com")
        except ValueError:pass
        else:raise AssertionError("HTTP admitted")
    r={"status":"PASS","corrupt_experiment_quarantine":"PASS","https_fail_closed":"PASS","user_data_deleted":False}
    (ROOT/"fault_injection_evidence.json").write_text(json.dumps(r,indent=2),encoding="utf-8");print(json.dumps(r))
if __name__=="__main__":main()
