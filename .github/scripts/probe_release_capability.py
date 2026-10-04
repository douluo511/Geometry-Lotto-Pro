from __future__ import annotations
import json, os, urllib.error, urllib.request
from pathlib import Path

TOKEN=os.environ["GITHUB_TOKEN"]
REPO=os.environ["GITHUB_REPOSITORY"]
HEAD=os.environ["PROBE_HEAD_SHA"]
TAG="capability-probe-"+os.environ["GITHUB_RUN_ID"]
BASE="https://api.github.com/repos/"+REPO
HEADERS={
    "Accept":"application/vnd.github+json",
    "Authorization":"Bearer "+TOKEN,
    "X-GitHub-Api-Version":"2022-11-28",
    "Content-Type":"application/json",
    "User-Agent":"release-capability-probe",
}
def call(url,method="GET",payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,method=method,headers=HEADERS)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read().decode("utf-8","replace")
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw=e.read().decode("utf-8","replace")
        try:b=json.loads(raw) if raw else {}
        except Exception:b={"message":raw[:1000]}
        return e.code,b

create_code,body=call(BASE+"/releases","POST",{
    "tag_name":TAG,
    "target_commitish":HEAD,
    "name":"Capability Probe "+TAG,
    "body":"Temporary draft release capability probe; should be deleted in the same job.",
    "draft":True,
    "prerelease":True,
})
release_id=body.get("id")
delete_code=None
tag_delete_code=None
if create_code==201 and release_id:
    delete_code,_=call(BASE+"/releases/"+str(release_id),"DELETE")
    tag_delete_code,_=call(BASE+"/git/refs/tags/"+TAG,"DELETE")
out={
    "schema":"release-capability-probe-v1",
    "repository":REPO,
    "head_sha":HEAD,
    "create_http_status":create_code,
    "create_message":str(body.get("message","")),
    "release_created":create_code==201,
    "release_deleted":delete_code==204,
    "delete_http_status":delete_code,
    "tag_delete_http_status":tag_delete_code,
    "capability_status":"PASS" if create_code==201 and delete_code==204 else "BLOCKED",
    "boundary":"Temporary draft only; not production Release N->N+1 evidence."
}
Path("release_capability_probe.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(out,sort_keys=True))
