from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, random, time
from pathlib import Path
from urllib.parse import urlparse
import requests

class NetClient:
    def __init__(self,evidence:Path,connect_timeout=5.0,read_timeout=15.0,max_attempts=3,max_bytes=1500000):
        self.evidence=Path(evidence); self.evidence.parent.mkdir(parents=True,exist_ok=True)
        self.connect_timeout=connect_timeout; self.read_timeout=read_timeout; self.max_attempts=max_attempts; self.max_bytes=max_bytes
        self.session=requests.Session()
        self.session.headers.update({"User-Agent":"BeYourOwnMaster/0.1 evidence-first","Accept":"text/html,text/plain,*/*;q=0.2"})
    def _record(self,obj:dict)->None:
        with self.evidence.open("a",encoding="utf-8") as f: f.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+"\n")
    def get_text(self,url:str)->tuple[str,dict]:
        if urlparse(url).scheme.lower()!="https": raise ValueError("HTTPS-only source policy")
        last=None
        for attempt in range(1,self.max_attempts+1):
            now=datetime.now(timezone.utc).isoformat()
            try:
                r=self.session.get(url,timeout=(self.connect_timeout,self.read_timeout),allow_redirects=True)
                chain=[x.url for x in r.history]+[r.url]
                if any(urlparse(x).scheme.lower()!="https" for x in chain): raise RuntimeError("HTTPS downgrade rejected")
                if r.status_code in {429,500,502,503,504}: raise requests.HTTPError(f"retryable HTTP {r.status_code}",response=r)
                if r.status_code!=200: raise RuntimeError(f"HTTP {r.status_code}")
                raw=r.content
                if not raw or len(raw)>self.max_bytes: raise RuntimeError(f"invalid payload size {len(raw)}")
                rec={"url":url,"final_url":r.url,"status":200,"retrieved_at":now,"bytes":len(raw),"payload_sha256":hashlib.sha256(raw).hexdigest(),"attempt":attempt,"result":"PASS","content_type":(r.headers.get("Content-Type") or "").split(";",1)[0].lower()}
                self._record(rec); return raw.decode(r.encoding or "utf-8",errors="replace"),rec
            except Exception as exc:
                last=exc; self._record({"url":url,"status":getattr(getattr(exc,"response",None),"status_code",None),"retrieved_at":now,"attempt":attempt,"result":"FAIL","error":repr(exc)})
                if attempt>=self.max_attempts or not isinstance(exc,(requests.ConnectionError,requests.Timeout,requests.HTTPError)): break
                time.sleep(min(2.0,.25*(2**(attempt-1)))+random.uniform(0,.15))
        raise RuntimeError(f"network request failed: {last!r}")
