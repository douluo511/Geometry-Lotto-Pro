from __future__ import annotations
import hashlib, json, time
from datetime import datetime, timezone
import requests
from domain import SourceReceipt

class NetClient:
    def __init__(self, connect_timeout: float=5.0, read_timeout: float=15.0, max_attempts: int=3, backoff_base: float=0.35):
        self.connect_timeout=connect_timeout; self.read_timeout=read_timeout; self.max_attempts=max(1,min(int(max_attempts),4)); self.backoff_base=backoff_base
    def get_bytes(self,url:str)->tuple[bytes,SourceReceipt]:
        if not url.startswith("https://"): raise ValueError("only HTTPS sources are allowed")
        last=None
        for attempt in range(1,self.max_attempts+1):
            try:
                r=requests.get(url,timeout=(self.connect_timeout,self.read_timeout),headers={"User-Agent":"EnglishRootIntelligence/0.2"})
                if r.status_code==429 or 500<=r.status_code<=599:
                    if attempt<self.max_attempts:
                        time.sleep(self.backoff_base*(2**(attempt-1)) + 0.01*attempt); continue
                r.raise_for_status()
                ctype=(r.headers.get("Content-Type") or "").lower()
                if not any(x in ctype for x in ("json","text/plain","octet-stream")): raise ValueError(f"unexpected content type: {ctype}")
                raw=r.content
                if not raw or len(raw)>5_000_000: raise ValueError("invalid response size")
                rec=SourceReceipt(url=url,status_code=r.status_code,content_type=ctype,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=datetime.now(timezone.utc).isoformat(),attempts=attempt)
                return raw,rec
            except (requests.Timeout,requests.ConnectionError,requests.HTTPError,ValueError) as e:
                last=e
                retryable=isinstance(e,(requests.Timeout,requests.ConnectionError))
                if isinstance(e,requests.HTTPError) and getattr(e.response,"status_code",0) in [429,500,502,503,504]: retryable=True
                if attempt>=self.max_attempts or not retryable: raise
                time.sleep(self.backoff_base*(2**(attempt-1)) + 0.01*attempt)
        raise RuntimeError(str(last))
    def get_json(self,url:str):
        raw,rec=self.get_bytes(url)
        return json.loads(raw.decode("utf-8-sig")),rec
