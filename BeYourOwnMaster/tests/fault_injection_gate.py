from __future__ import annotations
import json,tempfile
from pathlib import Path
from app.netclient import NetClient
from app.storage import Storage
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory() as td:
        s=Storage(Path(td)); p=s.canonical/"training_records.jsonl"; p.write_text("{broken",encoding="utf-8")
        r=s.repair(); assert r["status"]=="PASS" and r["quarantined"]
        n=NetClient(s.evidence/"net.jsonl")
        try: n.get_text("http://example.com")
        except ValueError: pass
        else: raise AssertionError("insecure HTTP admitted")
    report={"status":"PASS","corrupt_record_quarantine":"PASS","https_fail_closed":"PASS","user_data_deleted":False}
    (ROOT/"fault_injection_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
if __name__=="__main__": main()
