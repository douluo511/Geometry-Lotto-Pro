from __future__ import annotations
import hashlib, time, urllib.request
from .evidence import record

# All are first-party references named by the owned v2.0 corpus.
# A single publisher blocking hosted CI must not silently turn into fake data;
# the gate requires two independent official receipts and records every failure.
OFFICIAL_REFERENCES=(
    "https://www.nasa.gov/",
    "https://history.state.gov/",
    "https://www.federalreserve.gov/",
)

def fetch(url:str,timeout:float=15.0,retries:int=2)->dict:
    if not url.startswith("https://"): raise ValueError("HTTPS required")
    last=None
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={
                "User-Agent":"Mozilla/5.0 EarthOnlineLifeBase/0.1 evidence-check",
                "Accept":"text/html,application/xhtml+xml"
            })
            with urllib.request.urlopen(req,timeout=timeout) as res:
                body=res.read(512*1024)
                status=int(getattr(res,"status",200))
                if status != 200 or len(body)<100:
                    raise RuntimeError(f"unexpected HTTP/body: {status}/{len(body)}")
                return {"url":url,"status":"PASS","http_status":status,
                        "bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()}
        except Exception as exc:
            last=exc
            if attempt<retries: time.sleep(0.8*(2**attempt))
    raise RuntimeError(f"network fetch failed: {url}: {last}")

def official_reference_gate()->dict:
    receipts=[]; failures=[]
    for url in OFFICIAL_REFERENCES:
        try: receipts.append(fetch(url))
        except Exception as exc: failures.append({"url":url,"status":"FAIL","error":repr(exc)})
    status="PASS" if len(receipts)>=2 else "FAIL"
    out={
        "status":status,
        "required_independent_official_receipts":2,
        "pass_count":len(receipts),
        "receipts":receipts,
        "failures":failures,
        "claim_boundary":"official source reachability/hash receipts only; not proof that the 43-case/full corpus is imported"
    }
    record("real_network.json",out)
    return out
