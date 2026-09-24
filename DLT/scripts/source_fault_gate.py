from __future__ import annotations
import json
from unittest.mock import patch

from glp.net_client import NetClient
from glp import sources

class Response:
    def __init__(self, code):
        self.status_code=code
        self.headers={}
        self.content=b"{}"
    def raise_for_status(self):
        return None

def main()->int:
    checks={}
    calls=[Response(429),Response(200)]
    with patch("glp.net_client.requests.get", side_effect=lambda *a,**k:calls.pop(0)):
        client=NetClient(max_attempts=2,sleeper=lambda _:None)
        result=client.get("https://example.test/data")
        checks["429_retry_then_200"]=result.status_code==200 and not calls

    def offline(*args,**kwargs):
        raise sources.SourceError("injected offline")
    with patch.object(sources,"fetch_national_history",offline), patch.object(sources,"fetch_jiangsu_recent",offline), patch.object(sources,"fetch_gansu_recent",offline):
        try:
            sources.build_canonical(baseline_draws=[])
            checks["offline_not_pass"]=False
        except Exception:
            checks["offline_not_pass"]=True

    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
