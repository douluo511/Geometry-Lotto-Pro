from __future__ import annotations
import json, os, urllib.error, urllib.request
from pathlib import Path

token=os.environ["GITHUB_TOKEN"]
owner=os.environ["OWNER"]
name=os.environ["TARGET_REPO"]
payload=json.dumps({
    "name":name,
    "private":False,
    "auto_init":False,
    "description":"Independent SSQ production repository created by authorized portfolio migration probe",
}).encode("utf-8")
req=urllib.request.Request(
    "https://api.github.com/user/repos",
    data=payload,
    method="POST",
    headers={
        "Accept":"application/vnd.github+json",
        "Authorization":f"Bearer {token}",
        "X-GitHub-Api-Version":"2022-11-28",
        "Content-Type":"application/json",
        "User-Agent":"Geometry-Lotto-Pro-repository-capability-probe",
    },
)
code=0
body={}
accepted=""
try:
    with urllib.request.urlopen(req,timeout=30) as resp:
        code=int(resp.status)
        accepted=resp.headers.get("x-accepted-github-permissions","")
        raw=resp.read().decode("utf-8","replace")
        body=json.loads(raw) if raw else {}
except urllib.error.HTTPError as exc:
    code=int(exc.code)
    accepted=exc.headers.get("x-accepted-github-permissions","")
    raw=exc.read().decode("utf-8","replace")
    try: body=json.loads(raw) if raw else {}
    except Exception: body={"message":raw[:1000]}
except Exception as exc:
    body={"message":f"{type(exc).__name__}: {exc}"}

status="PASS" if code==201 else "BLOCKED"
out={
    "schema":"repository-creation-capability-probe-v1",
    "target":f"{owner}/{name}",
    "http_status":code,
    "message":str(body.get("message","")),
    "html_url":str(body.get("html_url","")),
    "accepted_permissions_header":accepted,
    "capability_status":status,
    "repository_created":code==201,
}
Path("repository_creation_probe.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(out,sort_keys=True))
