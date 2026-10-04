from __future__ import annotations
import json, os, time, urllib.error, urllib.request
from pathlib import Path

TOKEN=os.environ["GITHUB_TOKEN"]
OWNER=os.environ["OWNER"]
NAME=os.environ["TARGET_REPO"]
BASE_HEADERS={
    "Accept":"application/vnd.github+json",
    "Authorization":f"Bearer {TOKEN}",
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"Geometry-Lotto-Pro-repository-capability-probe",
}

def request_json(url:str, *, method:str="GET", payload:dict|None=None):
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    headers=dict(BASE_HEADERS)
    if data is not None:
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=30) as resp:
            raw=resp.read().decode("utf-8","replace")
            body=json.loads(raw) if raw else {}
            return int(resp.status),dict(resp.headers.items()),body
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode("utf-8","replace")
        try: body=json.loads(raw) if raw else {}
        except Exception: body={"message":raw[:1000]}
        return int(exc.code),dict(exc.headers.items()),body

def pick_rate(headers:dict)->dict:
    lower={str(k).lower():str(v) for k,v in headers.items()}
    keys=[
        "x-ratelimit-limit","x-ratelimit-remaining","x-ratelimit-used",
        "x-ratelimit-reset","x-ratelimit-resource","retry-after",
        "x-accepted-github-permissions","x-oauth-scopes"
    ]
    return {k:lower.get(k,"") for k in keys}

user_code,user_headers,user_body=request_json("https://api.github.com/user")
rate_code,rate_headers,rate_body=request_json("https://api.github.com/rate_limit")

payload={
    "name":NAME,
    "private":False,
    "auto_init":False,
    "description":"Independent SSQ production repository created by authorized portfolio migration probe",
}
attempts=[]
for attempt in (1,2):
    code,headers,body=request_json("https://api.github.com/user/repos",method="POST",payload=payload)
    attempts.append({
        "attempt":attempt,
        "http_status":code,
        "message":str(body.get("message","")),
        "html_url":str(body.get("html_url","")),
        "rate_headers":pick_rate(headers),
    })
    if code in (201,422):
        break
    retry_after=str(dict((str(k).lower(),str(v)) for k,v in headers.items()).get("retry-after","")).strip()
    if attempt==1 and retry_after.isdigit() and int(retry_after)<=15:
        time.sleep(int(retry_after)+1)
        continue
    break

last=attempts[-1]
created=last["http_status"]==201
out={
    "schema":"repository-creation-capability-probe-v2",
    "target":f"{OWNER}/{NAME}",
    "token_identity":{
        "http_status":user_code,
        "login":str(user_body.get("login","")),
        "type":str(user_body.get("type","")),
        "message":str(user_body.get("message","")),
        "rate_headers":pick_rate(user_headers),
    },
    "rate_limit":{
        "http_status":rate_code,
        "core":((rate_body.get("resources") or {}).get("core") or {}),
        "graphql":((rate_body.get("resources") or {}).get("graphql") or {}),
        "rate_headers":pick_rate(rate_headers),
    },
    "create_attempts":attempts,
    "capability_status":"PASS" if created else "BLOCKED",
    "repository_created":created,
}
Path("repository_creation_probe.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(out,sort_keys=True))
