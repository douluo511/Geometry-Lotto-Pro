from __future__ import annotations
import json
from pathlib import Path
import tempfile

from app.netclient import NetClient
from app.storage import Storage


class Response:
    def __init__(self,status=503,body=b"fail",content_type="text/html",url="https://example.invalid/x"):
        self.status_code=status
        self.content=body
        self.url=url
        self.history=[]
        self.headers={"Content-Type":content_type}
        self.encoding="utf-8"


class Session:
    def __init__(self,responses):
        self.responses=list(responses)
        self.calls=0
    def get(self,*args,**kwargs):
        self.calls+=1
        item=self.responses[min(self.calls-1,len(self.responses)-1)]
        if isinstance(item,Exception):
            raise item
        return item


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        net=NetClient(root/"network.jsonl",max_attempts=3,connect_timeout=.01,read_timeout=.01)
        net.session=Session([Response(503),Response(503),Response(503)])
        try:
            net.get_text("https://example.invalid/x")
            raise AssertionError("503 sequence was accepted")
        except RuntimeError:
            pass
        assert net.session.calls==3

        net=NetClient(root/"network2.jsonl",max_attempts=3)
        net.session=Session([Response(200,b"{}","application/json")])
        try:
            net.get_text("https://example.invalid/x")
            raise AssertionError("wrong Content-Type was accepted")
        except RuntimeError:
            pass
        assert net.session.calls==1

        store=Storage(root/"store")
        (store.canonical/"sources.json").write_text('{"broken":true}',encoding="utf-8")
        repair=store.repair()
        assert repair["status"]=="PASS" and repair["user_data_deleted"] is False
        assert (store.evidence/"repair-invalid-sources.json").is_file()

    report={
        "status":"PASS",
        "bounded_503_retry":"PASS",
        "content_type_fail_closed":"PASS",
        "corrupt_canonical_repair_preserves_evidence":"PASS",
        "false_success":"REJECTED",
    }
    Path("fault_injection_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
