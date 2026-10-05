from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

URLS=[
" https://www.szse.cn/disclosure/notice/temp/t20180102_507883.html",
" https://www.szse.cn/disclosure/notice/temp/t20180417_534970.html",
" https://www.szse.cn/disclosure/notice/temp/t20181109_557452.html",
" https://www.szse.cn/disclosure/notice/temp/t20200313_575034.html",
" https://www.szse.cn/disclosure/notice/temp/t20200825_580977.html",
" https://www.szse.cn/disclosure/notice/temp/t20201026_582553.html",
" https://www.szse.cn/disclosure/notice/temp/t20210106_584116.html",
" https://www.szse.cn/disclosure/notice/temp/t20210514_585918.html",
" https://www.szse.cn/disclosure/notice/temp/t20210917_588440.html",
" https://www.szse.cn/disclosure/notice/temp/t20220223_591382.html",
" https://www.szse.cn/disclosure/notice/temp/t20251009_616429.html",
" https://www.szse.cn/disclosure/notice/temp/t20260930_623154.html",
]
URLS=[x.strip() for x in URLS]
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
KEYWORDS=["停牌","复牌","暂停上市","恢复上市","风险警示","撤销风险警示","退市风险警示","其他风险警示"]

def official(u):
    h=(urlparse(u).hostname or "").lower()
    return h=="szse.cn" or h.endswith(".szse.cn")

def main():
    s=requests.Session(); rows=[]
    for u in URLS:
        rec={"url":u,"status":"NOT VERIFIED"}
        try:
            r=s.get(u,headers={"User-Agent":UA,"Referer":"https://www.szse.cn/disclosure/notice/temp/"},timeout=(8,30),allow_redirects=True)
            rec.update(http_status=r.status_code,final_url=str(r.url),content_type=r.headers.get("content-type"),bytes=len(r.content),sha256=hashlib.sha256(r.content).hexdigest())
            if r.status_code!=200 or not r.content or not official(r.url):
                rec["status"]="TRANSPORT_FAIL"; rows.append(rec); continue
            enc=r.encoding
            if not enc or str(enc).lower() in {"iso-8859-1","latin-1"}: enc=r.apparent_encoding or "utf-8"
            text=r.content.decode(enc,errors="replace")
            soup=BeautifulSoup(text,"html.parser")
            visible=" ".join(soup.get_text(" ",strip=True).split())
            titles=[]
            if soup.title and soup.title.get_text(strip=True): titles.append(soup.title.get_text(" ",strip=True))
            for sel in ["h1","h2",".title",".article-title",".tit",".news-title"]:
                for n in soup.select(sel)[:3]:
                    t=" ".join(n.get_text(" ",strip=True).split())
                    if t: titles.append(t)
            for attr in [{"property":"og:title"},{"name":"title"}]:
                n=soup.find("meta",attrs=attr)
                if n and n.get("content"): titles.append(str(n["content"]).strip())
            pdfs=[]
            for a in soup.find_all("a",href=True):
                href=urljoin(r.url,a.get("href"))
                label=" ".join(a.get_text(" ",strip=True).split())
                if ".pdf" in href.lower() or "pdf" in label.lower():
                    pdfs.append({"url":href,"label":label[:200],"official":official(href)})
            codes=sorted(set(re.findall(r"(?<!\d)(?:00[0-3]\d{3}|30[01]\d{3}|60[01358]\d{3}|68[08]\d{3})(?!\d)",visible)))
            rec.update(
                status="STRUCTURE_CAPTURED",
                title_candidates=list(dict.fromkeys(titles))[:10],
                visible_text_chars=len(visible),
                visible_text_sha256=hashlib.sha256(visible.encode("utf-8")).hexdigest(),
                visible_text_sample=visible[:1800],
                pdf_links=pdfs[:20],
                security_codes=codes[:50],
                keyword_counts={k:visible.count(k) for k in KEYWORDS},
                script_count=len(soup.find_all("script")),
                iframe_sources=[urljoin(r.url,x.get("src")) for x in soup.find_all("iframe",src=True)][:10],
            )
        except Exception as e:
            rec["status"]="TRANSPORT_FAIL"; rec["error"]=f"{type(e).__name__}: {e}"
        rows.append(rec)
    captured=sum(x["status"]=="STRUCTURE_CAPTURED" for x in rows)
    report={
      "schema":"stock-szse-suspension-article-structure-sample-v1",
      "sample_size":len(rows),"captured":captured,"rows":rows,
      "adjudication":{
        "article_transport_sample":"PASS" if captured==len(rows) else "NOT VERIFIED",
        "article_structure_understood":"SUPPORTED" if captured else "NOT VERIFIED",
        "archive_title_semantics":"NOT VERIFIED",
        "shenzhen_historical_suspension_state":"NOT VERIFIED",
        "shenzhen_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Twelve evenly-spaced first-party article identifiers from the already-verified 1849-link denominator are sampled only to discover document structure. Sample success cannot establish archive-wide semantics or daily PIT state."
    }
    Path("stock_szse_suspension_article_structure_sample.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"captured":captured,"sample_size":len(rows),"adjudication":report["adjudication"]},sort_keys=True))
    return 0 if captured==len(rows) else 2
if __name__=="__main__": raise SystemExit(main())
