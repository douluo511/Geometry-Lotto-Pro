from __future__ import annotations
import hashlib, json, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path

TOKEN=os.environ["GITHUB_TOKEN"]
REPO=os.environ["GITHUB_REPOSITORY"]
HEAD=os.environ["PROBE_HEAD_SHA"]
RUN=os.environ["GITHUB_RUN_ID"]
TAG="capability-probe-"+RUN
BASE="https://api.github.com/repos/"+REPO
HEADERS={
    "Accept":"application/vnd.github+json",
    "Authorization":"Bearer "+TOKEN,
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"release-capability-probe",
}
def call(url,method="GET",payload=None,headers=None):
    data=None if payload is None else (json.dumps(payload).encode() if isinstance(payload,dict) else payload)
    h=dict(HEADERS); h.update(headers or {})
    if isinstance(payload,dict): h["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=h)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read()
            ctype=(r.headers.get("content-type") or "").lower()
            if "json" in ctype and raw:
                try: body=json.loads(raw.decode("utf-8","replace"))
                except Exception: body={}
            else: body=raw
            return r.status,dict(r.headers.items()),body
    except urllib.error.HTTPError as e:
        raw=e.read()
        try: body=json.loads(raw.decode("utf-8","replace")) if raw else {}
        except Exception: body={"message":raw[:1000].decode("utf-8","replace")}
        return e.code,dict(e.headers.items()),body

asset=Path("release_probe_asset.txt")
asset.write_text("release capability probe\nhead="+HEAD+"\nrun="+RUN+"\n",encoding="utf-8",newline="\n")
before=hashlib.sha256(asset.read_bytes()).hexdigest()

create_code,_,body=call(BASE+"/releases","POST",{
    "tag_name":TAG,"target_commitish":HEAD,"name":"Capability Probe "+TAG,
    "body":"Temporary draft release asset capability probe; deleted in same job.",
    "draft":True,"prerelease":True,
})
release_id=body.get("id") if isinstance(body,dict) else None
upload_code=None; download_code=None; same_hash=False; delete_code=None
asset_id=None; after=None
try:
    if create_code==201 and release_id:
        upload_url="https://uploads.github.com/repos/"+REPO+"/releases/"+str(release_id)+"/assets?"+urllib.parse.urlencode({"name":asset.name})
        upload_code,_,upload_body=call(upload_url,"POST",asset.read_bytes(),{"Content-Type":"text/plain"})
        if isinstance(upload_body,dict): asset_id=upload_body.get("id")
        if upload_code==201 and asset_id:
            download_code,_,download_body=call(BASE+"/releases/assets/"+str(asset_id),"GET",None,{"Accept":"application/octet-stream"})
            raw=download_body if isinstance(download_body,(bytes,bytearray)) else b""
            Path("release_probe_redownload.txt").write_bytes(raw)
            after=hashlib.sha256(raw).hexdigest() if raw else None
            same_hash=bool(after and after==before)
finally:
    if release_id:
        delete_code,_,_=call(BASE+"/releases/"+str(release_id),"DELETE")

out={
    "schema":"release-capability-probe-v2",
    "repository":REPO,"head_sha":HEAD,
    "create_http_status":create_code,"release_created":create_code==201,
    "asset_upload_http_status":upload_code,"asset_uploaded":upload_code==201,
    "asset_download_http_status":download_code,"asset_redownloaded":download_code==200,
    "asset_sha256_before":before,"asset_sha256_after":after,
    "asset_redownload_same_hash":"PASS" if same_hash else "FAIL",
    "release_delete_http_status":delete_code,"release_deleted":delete_code==204,
    "capability_status":"PASS" if (create_code==201 and upload_code==201 and download_code==200 and same_hash and delete_code==204) else "BLOCKED",
    "boundary":"Temporary draft asset only; not production Release N->N+1 evidence."
}
Path("release_capability_probe.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(out,sort_keys=True))
