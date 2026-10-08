from __future__ import annotations
import hashlib
import json
import re
import time
from collections import Counter
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

URLS = (
    "https://www.szse.cn/disclosure/notice/temp/t20180102_507883.html",
    "https://www.szse.cn/disclosure/notice/temp/t20200911_581438.html",
    "https://www.szse.cn/disclosure/notice/temp/t20260930_623153.html",
)
TERMS = ("停牌", "复牌", "暂停交易", "恢复交易")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"

def fetch(url):
    assert urlparse(url).hostname == "www.szse.cn"
    errors = []
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.szse.cn/disclosure/notice/temp/"}, timeout=(8, 30))
            host = urlparse(r.url).hostname
            if host not in ("szse.cn", "www.szse.cn") and not str(host).endswith(".szse.cn"):
                raise RuntimeError("cross-domain redirect")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty official response")
            return r, errors
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}:{str(exc)[:130]}")
            if attempt < 2:
                time.sleep(attempt + 1)
    return None, errors

def summary(r, errors, url):
    if r is None:
        return {"url": url, "status": "NOT VERIFIED", "errors": errors}
    r.encoding = r.apparent_encoding if str(r.encoding).lower() in ("none","iso-8859-1") else r.encoding
    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    selectors = ["article","[itemprop='articleBody']","#article",".article-content",".content","#content"]
    text_elements = []
    for tag in soup.find_all(["article","section","main","div","p","td","table","span","h1","h2","h3","iframe","frame"]):
        if tag.name in ("iframe", "frame"):
            continue
        txt = re.sub(r"\\s+", "", tag.get_text(" ", strip=True))
        if len(txt) < 15 or len(txt) > 15000:
            continue
        if not any(w in txt for w in TERMS):
            continue
        ancestors=[]
        parent=tag
        for _ in range(4):
            if parent is None or not getattr(parent,"name",None):
                break
            ancestors.append({"tag":parent.name,"id":parent.get("id"),"class":parent.get("class")})
            parent=parent.parent
        text_elements.append({"chars":len(txt),"path":ancestors,"snippet":txt[:180]})
    text_elements.sort(key=lambda x:(x["chars"],len(x["path"])))
    containers=[]
    for tag in soup.find_all(["div","section","article","main","table","iframe","frame"]):
        id_=str(tag.get("id") or "")
        cls=" ".join(tag.get("class") or [])
        if id_ or cls or tag.name in ("iframe","frame"):
            containers.append({"tag":tag.name,"id":id_[:80],"class":cls[:110],"src":str(tag.get("src") or "")[:180]})
    return {"url":url, "status":"DIAGNOSTIC_ONLY", "http":r.status_code, "resolved":r.url,
            "sha256":hashlib.sha256(r.content).hexdigest(),"bytes":len(r.content),
            "title":(soup.title.get_text(" ",strip=True) if soup.title else None),
            "meta_refresh":[str(x.get("content"))[:200] for x in soup.find_all("meta",attrs={"http-equiv":"refresh"})],
            "iframes":[{"tag":t.name,"src":str(t.get("src"))[:200]} for t in soup.find_all(["iframe","frame"])],
            "all_tags":dict(Counter(t.name for t in soup.find_all()).most_common(20)),
            "containers":containers[:80], "terms_present_in_html":{w:(w in html) for w in TERMS},
            "candidate_text_elements":text_elements[:25],
            "current_primary_selector_matches":{sel:len(soup.select(sel)) for sel in selectors},
            "first_visible_text":soup.get_text(" ",strip=True)[:450],
            "error_ledger":errors}

def main():
    rows=[]
    for url in URLS:
        r, errors=fetch(url)
        result=summary(r,errors,url)
        rows.append(result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    report={"schema":"szse-official-html-layout-probe-v1","qualification":"NOT VERIFIED",
            "scope":"official markup diagnostic only; never infer suspension state from html shell",
            "sample_count":len(URLS),"results":rows}
    with open("stock_szse_primary_layout_probe.json","w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,sort_keys=True)
    return 0 if all(r["status"]=="DIAGNOSTIC_ONLY" for r in rows) else 2

if __name__ == "__main__":
    raise SystemExit(main())
