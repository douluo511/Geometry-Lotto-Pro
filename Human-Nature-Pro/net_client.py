from __future__ import annotations
import base64
import hashlib
import random
import time
from datetime import datetime, timezone

import requests


class NetClient:
    RETRY_STATUSES=(408,429,500,502,503,504)

    def __init__(
        self,
        connect_timeout=5.0,
        read_timeout=15.0,
        max_attempts=3,
        backoff_base=0.35,
        session=None,
        sleeper=time.sleep,
        rng=None,
    ):
        self.connect_timeout=float(connect_timeout)
        self.read_timeout=float(read_timeout)
        self.max_attempts=int(max_attempts)
        self.backoff_base=float(backoff_base)
        if self.connect_timeout<=0 or self.read_timeout<=0:
            raise ValueError("timeouts must be positive")
        if self.max_attempts<1 or self.max_attempts>4:
            raise ValueError("max_attempts must be between 1 and 4")
        if self.backoff_base<0:
            raise ValueError("backoff_base must be nonnegative")
        self.session=session or requests.Session()
        self.sleeper=sleeper
        self.rng=rng or random.Random()
        self.last_receipt={}

    def _delay(self,attempt:int,retry_after:str|None=None)->float:
        if retry_after and str(retry_after).isdigit():
            return min(float(retry_after),5.0)
        return min(self.backoff_base*(2**(attempt-1))*(0.5+self.rng.random()),5.0)

    def get(self,url:str):
        self.last_receipt={}
        if not str(url).startswith("https://"):
            raise ValueError("HTTPS required")
        ledger=[]
        for attempt in range(1,self.max_attempts+1):
            try:
                r=self.session.get(
                    url,
                    timeout=(self.connect_timeout,self.read_timeout),
                    headers={
                        "User-Agent":"Human-Nature-Pro/0.4 (+https://github.com/douluo511/Geometry-Lotto-Pro)",
                        "Accept":"application/json,text/plain;q=0.9,*/*;q=0.1",
                    },
                    allow_redirects=True,
                )
                status=int(getattr(r,"status_code",0) or 0)
                final_url=str(getattr(r,"url","") or url)
                raw=bytes(getattr(r,"content",b"") or b"")
                ctype=(r.headers.get("Content-Type") or "").lower()
                if not final_url.startswith("https://"):
                    ledger.append({
                        "attempt":attempt,"outcome":"FINAL_INSECURE_REDIRECT",
                        "status_code":status,"error_type":None,"retry_delay":0.0,
                        "requested_url":url,"final_url":final_url,
                    })
                    exc=ValueError(f"HTTPS request redirected to non-HTTPS URL: {final_url}")
                    setattr(exc,"glp_attempts",tuple(ledger))
                    raise exc
                if status in self.RETRY_STATUSES and attempt<self.max_attempts:
                    delay=self._delay(attempt,r.headers.get("Retry-After"))
                    ledger.append({
                        "attempt":attempt,"outcome":"RETRY_HTTP","status_code":status,
                        "error_type":None,"retry_delay":delay,
                        "requested_url":url,"final_url":final_url,
                    })
                    self.sleeper(delay)
                    continue
                r.raise_for_status()
                if not raw or len(raw)>5_000_000:
                    raise ValueError("invalid payload size")
                if "json" not in ctype and "text/plain" not in ctype and not raw.lstrip().startswith((b"{",b"[")):
                    raise ValueError(f"unexpected content type: {ctype}")
                ledger.append({
                    "attempt":attempt,"outcome":"HTTP_RESPONSE","status_code":status,
                    "error_type":None,"retry_delay":0.0,
                    "requested_url":url,"final_url":final_url,
                })
                receipt={
                    "requested_url":url,
                    "final_url":final_url,
                    "http_status":status,
                    "content_type":ctype,
                    "payload_hash":hashlib.sha256(raw).hexdigest(),
                    "bytes":len(raw),
                    "fetched_at":datetime.now(timezone.utc).isoformat(),
                    "attempts":list(ledger),
                    "body_b64":base64.b64encode(raw).decode("ascii"),
                }
                self.last_receipt=dict(receipt)
                return raw,receipt
            except (requests.Timeout,requests.ConnectionError) as exc:
                if attempt<self.max_attempts:
                    delay=self._delay(attempt)
                    ledger.append({
                        "attempt":attempt,"outcome":"RETRY_EXCEPTION","status_code":None,
                        "error_type":type(exc).__name__,"retry_delay":delay,
                        "requested_url":url,"final_url":url,
                    })
                    self.sleeper(delay)
                    continue
                ledger.append({
                    "attempt":attempt,"outcome":"FINAL_EXCEPTION","status_code":None,
                    "error_type":type(exc).__name__,"retry_delay":0.0,
                    "requested_url":url,"final_url":url,
                })
                setattr(exc,"glp_attempts",tuple(ledger))
                raise
            except (requests.HTTPError,ValueError) as exc:
                if getattr(exc,"glp_attempts",None):
                    raise
                code=int(getattr(getattr(exc,"response",None),"status_code",0) or 0)
                if code in self.RETRY_STATUSES and attempt<self.max_attempts:
                    delay=self._delay(attempt)
                    ledger.append({
                        "attempt":attempt,"outcome":"RETRY_EXCEPTION","status_code":code or None,
                        "error_type":type(exc).__name__,"retry_delay":delay,
                        "requested_url":url,"final_url":url,
                    })
                    self.sleeper(delay)
                    continue
                ledger.append({
                    "attempt":attempt,"outcome":"FINAL_EXCEPTION","status_code":code or None,
                    "error_type":type(exc).__name__,"retry_delay":0.0,
                    "requested_url":url,"final_url":url,
                })
                setattr(exc,"glp_attempts",tuple(ledger))
                raise
        raise RuntimeError("network retry loop exhausted")
