import urllib.request, urllib.error, hashlib, time, random, ssl
from dataclasses import dataclass

@dataclass
class NetResult:
    ok:bool; url:str; status:int; content_type:str; sha256:str; size:int; elapsed_ms:int; error:str=''

class NetClient:
    def __init__(self, connect_read_timeout=10, retries=2, max_bytes=1_500_000, user_agent='TalkCraftPro/1.0'):
        self.timeout=connect_read_timeout; self.retries=retries; self.max_bytes=max_bytes; self.ua=user_agent
    def get(self,url:str)->NetResult:
        last=''; start=time.time()
        for attempt in range(self.retries+1):
            try:
                req=urllib.request.Request(url,headers={'User-Agent':self.ua,'Accept':'text/html,application/xhtml+xml'})
                with urllib.request.urlopen(req,timeout=self.timeout,context=ssl.create_default_context()) as r:
                    status=getattr(r,'status',200); ct=(r.headers.get('content-type') or '').lower()
                    body=r.read(self.max_bytes+1)
                    if len(body)>self.max_bytes: raise ValueError('payload_too_large')
                    if status<200 or status>=300: raise ValueError(f'http_{status}')
                    if 'text/html' not in ct and 'application/xhtml+xml' not in ct: raise ValueError('unexpected_content_type')
                    return NetResult(True,url,status,ct,hashlib.sha256(body).hexdigest(),len(body),int((time.time()-start)*1000))
            except Exception as e:
                last=f'{type(e).__name__}:{e}'
                if attempt<self.retries:
                    time.sleep((0.35*(2**attempt))+random.uniform(0,0.15))
        return NetResult(False,url,0,'','',0,int((time.time()-start)*1000),last)
