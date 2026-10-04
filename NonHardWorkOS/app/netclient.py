from __future__ import annotations
from datetime import datetime, timezone
import hashlib,json,random,time
from pathlib import Path
from urllib.parse import urlparse
import requests

class NetClient:
    def __init__(self,evidence:Path,max_attempts=3):
        self.evidence=Path(evidence); self.evidence.parent.mkdir(parents=True,exist_ok=True)
        self.max_attempts=max_attempts; self.s=requests.Session()
        self.s.headers.update({"User-Agent":"NonHardWorkOS/0.1 evidence-first","Accept":"text/html,text/plain,*/*;q=0.2"})
    def _write(self,o):
        with self.evidence.open("a",encoding="utf-8") as f:f.write(json.dumps(o,ensure_ascii=False,sort_keys=True)+"\n")
    def get(self,url:str):
        if urlparse(url).scheme.lower()!="https": raise ValueError("HTTPS only")
        last=None
        for i in range(1,self.max_attempts+1):
            now=datetime.now(timezone.utc).isoformat()
            try:
                r=self.s.get(url,timeout=(5,15),allow_redirects=True)
                if any(urlparse(x.url).scheme.lower()!="https" for x in [*r.history,r]): raise RuntimeError("HTTPS downgrade")
                if r.status_code in {429,500,502,503,504}: raise requests.HTTPError(f"retryable HTTP {r.status_code}",response=r)
                if r.status_code!=200: raise RuntimeError(f"HTTP {r.status_code}")
                raw=r.content
                if not raw or len(raw)>1500000: raise RuntimeError("invalid payload size")
                rec={"url":url,"final_url":r.url,"status":200,"retrieved_at":now,"bytes":len(raw),"payload_sha256":hashlib.sha256(raw).hexdigest(),"attempt":i,"result":"PASS"}
                self._write(rec); return raw.decode(r.encoding or "utf-8",errors="replace"),rec
            except Exception as exc:
                last=exc; self._write({"url":url,"retrieved_at":now,"attempt":i,"result":"FAIL","error":repr(exc)})
                if i>=self.max_attempts or not isinstance(exc,(requests.ConnectionError,requests.Timeout,requests.HTTPError)): break
                time.sleep(min(2,.25*(2**(i-1)))+random.uniform(0,.15))
        raise RuntimeError(repr(last))
