from __future__ import annotations
import hashlib, io, json, re
from pathlib import Path
import requests
from pypdf import PdfReader

URL="https://www.sse.com.cn/services/tradingtech/development/c/10822594/files/2096257019bf484f9b9935fa73f94721.pdf"
KEYWORDS=("cpxx0201","文件传输","下载","EzSTEP","STEP","接口","开市前发布","包含停牌的产品","交易日使用的日期")
OUT=Path("rmf_sse_product_file_distribution_context.json")

def main():
    r=requests.get(URL,headers={"User-Agent":"Mozilla/5.0 Chrome/154","Referer":"https://www.sse.com.cn/","Accept":"application/pdf,*/*"},timeout=(8,35))
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"): raise SystemExit("not PDF")
    reader=PdfReader(io.BytesIO(r.content))
    text="\n".join((p.extract_text() or "") for p in reader.pages)
    compact="".join(text.replace("\u200b","").split())
    contexts=[]
    for kw in KEYWORDS:
        start=0
        while True:
            i=compact.find(kw,start)
            if i<0: break
            a=max(0,i-350); b=min(len(compact),i+len(kw)+700)
            contexts.append({"keyword":kw,"context":compact[a:b],"context_sha256":hashlib.sha256(compact[a:b].encode()).hexdigest()})
            start=i+len(kw)
            if sum(1 for x in contexts if x["keyword"]==kw)>=5: break
    protocols=sorted(set(re.findall(r"(?:https?|ftp|sftp)://[^\s<>\"']+",text,re.I)))
    report={
      "schema":"rmf-sse-product-file-distribution-context-v1",
      "source_url":r.url,"http_status":r.status_code,"pdf_sha256":hashlib.sha256(r.content).hexdigest(),
      "page_count":len(reader.pages),"text_sha256":hashlib.sha256(text.encode()).hexdigest(),
      "keyword_hits":{kw:sum(1 for x in contexts if x["keyword"]==kw) for kw in KEYWORDS},
      "contexts":contexts,"protocol_urls":protocols[:100],
      "adjudication":{
        "distribution_context_extracted":"PASS" if any(x["keyword"]=="cpxx0201" for x in contexts) else "NOT VERIFIED",
        "public_historical_download_endpoint":"NOT VERIFIED",
        "historical_file_contents_replayable_now":"NOT VERIFIED",
        "historical_pit_content_availability":"NOT VERIFIED",
        "survivorship_selection_control":"NOT VERIFIED",
        "capital_deployment_ready":False,
        "product_bytes_changed":False,
        "final_gate":"FAIL"
      },
      "boundary":"Specification context can identify the distribution mechanism and filename semantics. It cannot prove public historical replay without a verified accessible historical file surface."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"keyword_hits":report["keyword_hits"],"protocol_urls":report["protocol_urls"],"adjudication":report["adjudication"],"contexts":contexts[:8]},ensure_ascii=True,sort_keys=True))
    return 0 if report["adjudication"]["distribution_context_extracted"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
