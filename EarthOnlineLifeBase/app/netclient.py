from __future__ import annotations
import hashlib, json, time, urllib.request, urllib.error
from .evidence import record

OFFICIAL_REFERENCES=(
    "https://www.nasa.gov/",
    "https://www.cdc.gov/",
)

def fetch(url:str,timeout:float=15.0,retries:int=2)->dict:
    if not url.startswith("https://"): raise ValueError("HTTPS required")
    last=None
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"EarthOnlineLifeBase/0.1 evidence-check"})
            with urllib.request.urlopen(req,timeout=timeout) as res:
                body=res.read(512*1024)
                if int(getattr(res,"status",200)) != 200 or len(body)<100:
                    raise RuntimeError("unexpected HTTP/body")
                return {"url":url,"status":"PASS","http_status":int(getattr(res,"status",200)),
                        "bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()}
        except Exception as exc:
            last=exc
            if attempt<retries: time.sleep(0.8*(2**attempt))
    raise RuntimeError(f"network fetch failed: {url}: {last}")

def official_reference_gate()->dict:
    receipts=[]
    for url in OFFICIAL_REFERENCES: receipts.append(fetch(url))
    out={"status":"PASS","receipts":receipts,"claim_boundary":"network/source availability only; not proof that all 43 cases are imported"}
    record("real_network.json",out)
    return out
