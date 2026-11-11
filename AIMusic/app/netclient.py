from __future__ import annotations
import hashlib, json, ssl, time, urllib.request
from pathlib import Path

OFFICIAL_REFERENCE_URLS=[
    "https://huggingface.co/docs/api-inference/index",
    "https://github.com/facebookresearch/audiocraft"
]

def official_reference_gate(evidence_dir:Path)->dict:
    evidence_dir.mkdir(parents=True,exist_ok=True)
    receipts=[]
    for url in OFFICIAL_REFERENCE_URLS:
        item={"url":url,"status":"FAIL"}
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"AI-Music-Reauthored/1.0"})
            with urllib.request.urlopen(req,timeout=20,context=ssl.create_default_context()) as r:
                raw=r.read(512*1024)
                final=r.geturl()
                if not final.startswith("https://"):
                    raise RuntimeError("https downgrade")
                item.update({"status":"PASS","http_status":getattr(r,"status",200),"final_url":final,
                             "raw_sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)})
        except Exception as exc:
            item["error"]=f"{type(exc).__name__}: {exc}"
        receipts.append(item)
        time.sleep(.2)
    passed=sum(x["status"]=="PASS" for x in receipts)
    out={
        "status":"PASS" if passed>=1 else "FAIL",
        "passed":passed,"total":len(receipts),"receipts":receipts,
        "boundary":"Reference-network health only. This does not prove cloud AI generation, model access, output quality or licensing."
    }
    (evidence_dir/"network_reference.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return out
