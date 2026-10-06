from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pymupdf
import requests

URL="https://www.bse.cn/uploads/6/file/public/202308/20230808182712_dpdhxktl9u.pdf"
OUT=Path("stock_bse_920090_ocr_adjudication.json")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE 920090 OCR adjudication"
DATE=r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"

def sha256(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def same_bse(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="bse.cn" or host.endswith(".bse.cn")

def iso(y,m,d):
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

def normalize(text:str)->str:
    text=text.replace("\r","\n")
    text=re.sub(r"[ \t\u3000]+"," ",text)
    text=re.sub(r"\n+","\n",text)
    return text

def direct_resume_dates(text:str):
    compact=re.sub(r"\s+","",text or "")
    generic_patterns=[
        re.compile(rf"(?:本公司股票|公司股票|股票)[^。；]{{0,80}}?(?:自|于){DATE}[^。；]{{0,60}}?(?:起|开市起)?[^。；]{{0,20}}?复牌"),
        re.compile(rf"(?:复牌日期|恢复交易日期)[：:]?{DATE}"),
        re.compile(rf"(?:自|于){DATE}(?:开市)?起复牌"),
        re.compile(rf"(?:自|于){DATE}复牌"),
    ]
    heading_patterns=[
        # Explicit section-bound relation. OCR may drop a connector such as
        # "自", but the section itself must contain exactly one full calendar
        # date before the direct "起复牌" action.
        re.compile(rf"(?:复牌依据及复牌日期)[^。；]{{0,420}}?{DATE}[^。；]{{0,20}}?起复牌"),
    ]
    # When the document exposes the stronger explicit section, weaker generic
    # relations are suppressed so narrative/publication dates cannot compete.
    patterns=heading_patterns if "复牌依据及复牌日期" in compact else generic_patterns
    out=[]
    evidence=[]
    for pid,pat in enumerate(patterns):
        for m in pat.finditer(compact):
            matched=m.group(0)
            date_matches=list(re.finditer(DATE,matched))
            if len(date_matches) != 1:
                continue
            groups=date_matches[0].groups()[:3]
            try:
                dt=iso(*groups)
            except Exception:
                continue
            out.append(dt)
            evidence.append({
                "pattern":("heading_" if patterns is heading_patterns else "generic_")+str(pid),
                "date":dt,
                "matched_text":matched[:520],
                "matched_sha256":sha256(matched.encode("utf-8")),
            })
    return sorted(set(out)),evidence

def diagnostic_date_tokens(text:str):
    compact=re.sub(r"\\s+","",text or "")
    exact=[]
    for m in re.finditer(DATE,compact):
        try:
            exact.append({"raw":m.group(0),"date":iso(*m.groups()[:3])})
        except Exception:
            pass
    flexible=[]
    for m in re.finditer(r"(20\\d{2})\\D{0,4}(\\d{1,2})\\D{0,4}(\\d{1,2})",compact):
        raw=m.group(0)
        try:
            value=iso(*m.groups()[:3])
        except Exception:
            continue
        flexible.append({"raw":raw,"date":value})
    def dedupe(rows):
        seen=set(); out=[]
        for row in rows:
            key=(row["raw"],row["date"])
            if key not in seen:
                seen.add(key); out.append(row)
        return out
    return dedupe(exact),dedupe(flexible)

def action_contexts(text:str):
    compact=re.sub(r"\\s+","",text or "")
    rows=[]
    for term in ("复牌","恢复交易","开市","停牌"):
        for m in re.finditer(term,compact):
            lo=max(0,m.start()-140); hi=min(len(compact),m.end()+180)
            snippet=compact[lo:hi]
            rows.append({
                "term":term,
                "snippet":snippet,
                "snippet_sha256":sha256(snippet.encode("utf-8")),
            })
    unique={}
    for row in rows:
        unique[(row["term"],row["snippet_sha256"])]=row
    return [unique[k] for k in sorted(unique)][:40]

def semantic_regression_self_check():
    positive="三、复牌依据及复牌日期根据规则并经申请，本公司股票2023年8月9日起复牌。"
    dates,hits=direct_resume_dates(positive)
    if dates != ["2023-08-09"] or not hits:
        raise RuntimeError(f"heading resume positive regression failed: {dates}")
    negative="三、复牌依据及复牌日期2023年8月8日审议，2023年8月9日起复牌。"
    dates2,_=direct_resume_dates(negative)
    if dates2:
        raise RuntimeError(f"multi-date heading must fail closed: {dates2}")

def run_ocr(png:Path,psm:int):
    cmd=["tesseract",str(png),"stdout","-l","chi_sim+eng","--psm",str(psm),"--dpi","300"]
    p=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",check=False)
    return {
        "cmd":cmd,
        "returncode":p.returncode,
        "stdout":normalize(p.stdout),
        "stderr":normalize(p.stderr),
    }

def main()->int:
    semantic_regression_self_check()
    r=requests.get(
        URL,
        headers={
            "User-Agent":UA,
            "Accept":"application/pdf,application/octet-stream,*/*",
            "Referer":"https://www.bse.cn/disclosure/announcement.html",
        },
        timeout=(10,45),
        allow_redirects=True,
    )
    meta={
        "status":r.status_code,
        "resolved_url":r.url,
        "content_type":r.headers.get("content-type"),
        "bytes":len(r.content),
        "sha256":sha256(r.content),
        "same_official_host":same_bse(r.url),
        "pdf_magic":r.content.startswith(b"%PDF"),
    }
    if r.status_code!=200 or not meta["same_official_host"] or not meta["pdf_magic"]:
        report={"schema":"stock-bse-920090-ocr-adjudication-v1","status":"NOT VERIFIED","transport":meta}
        OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=True,sort_keys=True))
        return 2

    version=subprocess.run(["tesseract","--version"],capture_output=True,text=True,check=False)
    langs=subprocess.run(["tesseract","--list-langs"],capture_output=True,text=True,check=False)
    lang_text=langs.stdout+"\n"+langs.stderr
    if "chi_sim" not in lang_text:
        raise RuntimeError("chi_sim language pack unavailable")

    doc=pymupdf.open(stream=r.content,filetype="pdf")
    page_evidence=[]
    ocr_by_psm={3:[],6:[]}
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for i,page in enumerate(doc):
            pix=page.get_pixmap(dpi=300,alpha=False)
            png=root/f"page_{i+1:03d}.png"
            pix.save(png.as_posix())
            png_bytes=png.read_bytes()
            page_rec={
                "page":i+1,
                "width":pix.width,
                "height":pix.height,
                "png_sha256":sha256(png_bytes),
                "png_bytes":len(png_bytes),
            }
            for psm in (3,6):
                o=run_ocr(png,psm)
                page_rec[f"psm_{psm}_returncode"]=o["returncode"]
                page_rec[f"psm_{psm}_text_sha256"]=sha256(o["stdout"].encode("utf-8"))
                page_rec[f"psm_{psm}_chars"]=len(o["stdout"])
                ocr_by_psm[psm].append(o["stdout"])
            page_evidence.append(page_rec)
    doc.close()

    psm_results={}
    for psm,texts in ocr_by_psm.items():
        joined=normalize("\n".join(texts))
        dates,hits=direct_resume_dates(joined)
        exact_tokens,flexible_tokens=diagnostic_date_tokens(joined)
        contexts=action_contexts(joined)
        psm_results[str(psm)]={
            "text_sha256":sha256(joined.encode("utf-8")),
            "text_chars":len(joined),
            "resume_dates":dates,
            "semantic_hits":hits,
            "exact_date_tokens":exact_tokens,
            "flexible_date_tokens":flexible_tokens,
            "action_contexts":contexts,
            "contains_title":"股票复牌公告" in re.sub(r"\\s+","",joined),
        }

    date3=psm_results["3"]["resume_dates"]
    date6=psm_results["6"]["resume_dates"]
    agreement=(len(date3)==1 and date3==date6)
    agreed=date3[0] if agreement else None

    report={
        "schema":"stock-bse-920090-ocr-adjudication-v1",
        "status":"SUPPORTED_DIAGNOSTIC" if agreement else "NOT VERIFIED",
        "transport":meta,
        "tesseract_version":version.stdout.splitlines()[0] if version.stdout else "",
        "languages_sha256":sha256(lang_text.encode("utf-8")),
        "page_count":len(page_evidence),
        "pages":page_evidence,
        "ocr":psm_results,
        "agreed_resume_date":agreed,
        "adjudication":{
            "same_primary_pdf_bound":"PASS",
            "dual_layout_ocr_agreement":"PASS" if agreement else "FAIL",
            "resume_date_from_primary_scan":"SUPPORTED_DIAGNOSTIC" if agreement else "NOT VERIFIED",
            "effective_resume_date":"SUPPORTED_DIAGNOSTIC" if agreement else "NOT VERIFIED",
            "bse_daily_suspension_pit":"NOT VERIFIED",
            "historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
        "boundary":"Last-resort OCR diagnostic over one fixed first-party BSE PDF after pypdf, PyMuPDF text extraction, full-row metadata and detail-endpoint discovery failed. Two Tesseract layout modes must independently yield the same single direct resume date. OCR support does not by itself establish daily PIT or Final.",
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "status":report["status"],
        "transport":report["transport"],
        "tesseract_version":report["tesseract_version"],
        "page_count":report["page_count"],
        "ocr":report["ocr"],
        "agreed_resume_date":report["agreed_resume_date"],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if agreement else 3

if __name__=="__main__":
    raise SystemExit(main())
