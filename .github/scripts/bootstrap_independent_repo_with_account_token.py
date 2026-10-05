from __future__ import annotations
import json, os, urllib.error, urllib.request
from pathlib import Path

TARGET_OWNER="douluo511"
TARGET_REPO="Geometry-Lotto-Pro-SSQ"
CANDIDATES=[
    ("GH_PAT", os.environ.get("CANDIDATE_GH_PAT","")),
    ("GITHUB_PAT", os.environ.get("CANDIDATE_GITHUB_PAT","")),
    ("REPO_TOKEN", os.environ.get("CANDIDATE_REPO_TOKEN","")),
    ("PERSONAL_ACCESS_TOKEN", os.environ.get("CANDIDATE_PERSONAL_ACCESS_TOKEN","")),
    ("USER_PAT", os.environ.get("CANDIDATE_USER_PAT","")),
    ("ADMIN_PAT", os.environ.get("CANDIDATE_ADMIN_PAT","")),
]
label,token=next(((name,value) for name,value in CANDIDATES if value), (None,""))

def call(url:str, method:str="GET", payload:dict|None=None):
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    headers={
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"portfolio-independent-repo-bootstrap",
    }
    if token:
        headers["Authorization"]="Bearer "+token
    if data is not None:
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read().decode("utf-8","replace")
            return int(r.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode("utf-8","replace")
        try: body=json.loads(raw) if raw else {}
        except Exception: body={"message":raw[:1000]}
        return int(exc.code), body

out={
    "schema":"account-token-repository-bootstrap-v1",
    "target":f"{TARGET_OWNER}/{TARGET_REPO}",
    "candidate_secret_present":bool(token),
    "candidate_slot":label if token else None,
    "token_identity_status":"NOT VERIFIED",
    "token_identity_login":None,
    "repository_creation_status":"BLOCKED",
    "repository_created":False,
    "repository_exists":False,
}

if token:
    user_code,user=call("https://api.github.com/user")
    out["token_identity_http_status"]=user_code
    out["token_identity_login"]=user.get("login")
    out["token_identity_status"]="PASS" if user_code==200 and user.get("login")==TARGET_OWNER else "FAIL"
    if out["token_identity_status"]=="PASS":
        existing_code,existing=call(f"https://api.github.com/repos/{TARGET_OWNER}/{TARGET_REPO}")
        if existing_code==200:
            out["repository_exists"]=True
            out["repository_creation_status"]="PASS_ALREADY_EXISTS"
            out["repository_html_url"]=existing.get("html_url")
        elif existing_code==404:
            create_code,created=call("https://api.github.com/user/repos","POST",{
                "name":TARGET_REPO,
                "private":False,
                "auto_init":False,
                "description":"Independent SSQ production repository for strict acceptance migration",
            })
            out["create_http_status"]=create_code
            out["create_message"]=created.get("message","")
            if create_code==201:
                out["repository_created"]=True
                out["repository_exists"]=True
                out["repository_creation_status"]="PASS"
                out["repository_html_url"]=created.get("html_url")
            else:
                out["repository_creation_status"]="BLOCKED"
        else:
            out["repository_creation_status"]="BLOCKED"
            out["existing_lookup_http_status"]=existing_code
            out["existing_lookup_message"]=existing.get("message","")

Path("account_token_repo_bootstrap.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
safe=dict(out)
safe.pop("candidate_slot",None)
print(json.dumps(safe,sort_keys=True))
