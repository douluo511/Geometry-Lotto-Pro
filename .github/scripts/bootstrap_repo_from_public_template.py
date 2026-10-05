from __future__ import annotations
import json, os, urllib.error, urllib.request
from pathlib import Path

TOKEN=os.environ["GITHUB_TOKEN"]
OWNER="douluo511"
NAME="Geometry-Lotto-Pro-SSQ"
TEMPLATE="forcedotcom/dx-empty"

def call(url:str, method:str="GET", payload:dict|None=None):
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    headers={
        "Accept":"application/vnd.github+json",
        "Authorization":"Bearer "+TOKEN,
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"portfolio-template-repo-bootstrap",
    }
    if data is not None:
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read().decode("utf-8","replace")
            return int(r.status),dict(r.headers.items()),json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode("utf-8","replace")
        try: body=json.loads(raw) if raw else {}
        except Exception: body={"message":raw[:1000]}
        return int(exc.code),dict(exc.headers.items()),body

existing_code,_,existing=call(f"https://api.github.com/repos/{OWNER}/{NAME}")
out={
    "schema":"template-repository-bootstrap-v1",
    "target":f"{OWNER}/{NAME}",
    "template":TEMPLATE,
    "existing_lookup_http_status":existing_code,
    "status":"BLOCKED",
    "repository_created":False,
    "repository_exists":existing_code==200,
}
if existing_code==200:
    out["status"]="PASS_ALREADY_EXISTS"
    out["html_url"]=existing.get("html_url")
elif existing_code==404:
    code,headers,body=call(
        f"https://api.github.com/repos/{TEMPLATE}/generate",
        "POST",
        {
            "owner":OWNER,
            "name":NAME,
            "description":"Independent SSQ production repository for strict acceptance migration",
            "include_all_branches":False,
            "private":False,
        },
    )
    out["generate_http_status"]=code
    out["generate_message"]=str(body.get("message",""))
    out["accepted_permissions_header"]=next((v for k,v in headers.items() if k.lower()=="x-accepted-github-permissions"),"")
    if code==201:
        out["status"]="PASS"
        out["repository_created"]=True
        out["repository_exists"]=True
        out["html_url"]=body.get("html_url")
else:
    out["existing_lookup_message"]=str(existing.get("message",""))

Path("template_repo_bootstrap.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(out,sort_keys=True))
