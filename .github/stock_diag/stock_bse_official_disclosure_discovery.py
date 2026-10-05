from __future__ import annotations

import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOTS = [
    "https://www.bse.cn/",
    "https://www.bse.cn/myhead.html",
    # Direct first-party disclosure surfaces. The earlier discovery only
    # reached these as secondary links and could miss their iframe/module
    # contracts or mis-decode their Chinese labels.
    "https://www.bse.cn/disclosure/announcement.html",
    "https://www.bse.cn/disclosure/risk_warning_board.html",
]
KEYWORDS = (
    "上市公司公告",
    "风险警示",
    "退市整理",
    "信息披露",
)
PATH_HINTS = (
    "disclosure",
    "announcement",
    "risk",
    "warning",
    "listed",
    "company",
    "xxpl",
)
MAX_SCRIPTS = 40
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = []
        self.frames = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag in ("iframe", "frame") and a.get("src"):
            self.frames.append(a["src"])
    def handle_data(self, data):
        t = (data or "").strip()
        if t:
            self.text.append(t)


def fetch(session, url, attempts=4):
    errors=[]
    for attempt in range(1, attempts+1):
        try:
            r=session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.8",
                    "Referer": "https://www.bse.cn/",
                },
                timeout=(8,30),
                allow_redirects=True,
            )
            if r.status_code in (403,429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            return r, {
                "attempt": attempt,
                "prior_errors": errors,
                "status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "final_url": r.url,
                "bytes": len(r.content),
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt-1)))


def decode_html(response):
    """Decode first-party HTML without trusting requests' ISO-8859-1 fallback.

    BSE pages can omit an HTTP charset while containing UTF-8/GB-family Chinese.
    Discovery must not turn that transport ambiguity into a false "no disclosure
    surface" result.  We select only among byte decodings and never infer any
    business status from the decoded text.
    """
    encodings=[]
    if response.encoding and response.encoding.lower() not in ("iso-8859-1", "latin-1"):
        encodings.append(response.encoding)
    encodings.extend(["utf-8", "gb18030"])
    try:
        if response.apparent_encoding:
            encodings.append(response.apparent_encoding)
    except Exception:
        pass
    best=None
    best_score=None
    seen=set()
    for enc in encodings:
        key=(enc or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            text=response.content.decode(enc,errors="replace")
        except Exception:
            continue
        keyword_hits=sum(text.count(k) for k in KEYWORDS)
        replacement_count=text.count("\ufffd")
        score=(keyword_hits, -replacement_count)
        if best_score is None or score > best_score:
            best=text
            best_score=score
    if best is None:
        best=response.content.decode("utf-8",errors="replace")
    return best


def normalized_url(base, value):
    try:
        u=urljoin(base,value)
        p=urlparse(u)
        if p.scheme not in ("http","https"):
            return None
        if not p.netloc.endswith("bse.cn"):
            return None
        return u
    except Exception:
        return None


def context_matches(text):
    rows=[]
    for kw in KEYWORDS:
        start=0
        while True:
            i=text.find(kw,start)
            if i<0:
                break
            rows.append({
                "keyword":kw,
                "context":text[max(0,i-180):i+260],
            })
            start=i+len(kw)
            if len(rows)>=100:
                return rows
    return rows


def url_candidates(text, base):
    # Extract quoted URL/path-like strings only; discovery, not execution proof.
    pats = re.findall(r'["\']([^"\']{3,300})["\']', text)
    out=[]
    for raw in pats:
        low=raw.lower()
        if not any(h in low for h in PATH_HINTS):
            continue
        if raw.startswith(("javascript:","#","data:")):
            continue
        u=normalized_url(base,raw)
        if u:
            out.append(u)
    return sorted(set(out))


def main():
    s=requests.Session()
    pages=[]
    all_links=set()
    script_urls=set()
    page_keyword_contexts=[]

    for url in ROOTS:
        try:
            r,meta=fetch(s,url)
            text=decode_html(r)
            c=Collector()
            c.feed(text)
            resolved_links=[u for x in c.links if (u:=normalized_url(r.url,x))]
            resolved_scripts=[u for x in c.scripts if (u:=normalized_url(r.url,x))]
            resolved_frames=[u for x in c.frames if (u:=normalized_url(r.url,x))]
            inline_candidates=url_candidates(text,r.url)
            all_links.update(resolved_links)
            all_links.update(resolved_frames)
            all_links.update(inline_candidates)
            script_urls.update(resolved_scripts)
            page_keyword_contexts.extend(
                {"source":r.url,**x} for x in context_matches(text)
            )
            pages.append({
                "requested_url":url,
                "fetch":meta,
                "link_count":len(resolved_links),
                "frame_count":len(resolved_frames),
                "script_count":len(resolved_scripts),
                "inline_candidate_count":len(inline_candidates),
                "keyword_context_count":len(context_matches(text)),
            })
        except Exception as exc:
            pages.append({
                "requested_url":url,
                "error":f"{type(exc).__name__}: {exc}",
            })

    hinted_links=sorted(
        u for u in all_links if any(h in u.lower() for h in PATH_HINTS)
    )

    scripts=[]
    js_candidates=set()
    for url in sorted(script_urls)[:MAX_SCRIPTS]:
        try:
            r,meta=fetch(s,url)
            text=decode_html(r)
            matches=url_candidates(text,r.url)
            js_candidates.update(matches)
            contexts=context_matches(text)
            scripts.append({
                "url":url,
                "fetch":meta,
                "candidate_count":len(matches),
                "candidates":matches[:100],
                "keyword_contexts":contexts[:30],
            })
        except Exception as exc:
            scripts.append({
                "url":url,
                "error":f"{type(exc).__name__}: {exc}",
            })

    # Candidate pages get a real GET probe. Success means only reachable surface.
    candidates=sorted(set(hinted_links)|js_candidates)
    candidate_probes=[]
    for url in candidates[:120]:
        try:
            r,meta=fetch(s,url,attempts=2)
            candidate_probes.append({
                "url":url,
                "fetch":meta,
                "looks_like_disclosure_surface": any(
                    kw in decode_html(r) for kw in KEYWORDS
                ),
            })
        except Exception as exc:
            candidate_probes.append({
                "url":url,
                "error":f"{type(exc).__name__}: {exc}",
            })

    reachable=[x for x in candidate_probes if x.get("fetch",{}).get("status")==200]
    keyword_reachable=[x for x in reachable if x.get("looks_like_disclosure_surface")]
    endpoint_like=[
        x for x in reachable
        if any(k in x["url"].lower() for k in (".do","api","query","search","ajax"))
    ]

    report={
        "schema":"stock-bse-official-disclosure-discovery-v1",
        "official_host":"www.bse.cn",
        "roots":pages,
        "page_keyword_contexts":page_keyword_contexts[:100],
        "hinted_links":hinted_links[:200],
        "scripts_scanned":scripts,
        "candidate_probe_count":len(candidate_probes),
        "candidate_probes":candidate_probes,
        "summary":{
            "official_pages_reached":sum(1 for x in pages if x.get("fetch",{}).get("status")==200),
            "script_urls_found":len(script_urls),
            "hinted_link_count":len(hinted_links),
            "js_candidate_count":len(js_candidates),
            "reachable_candidate_count":len(reachable),
            "keyword_reachable_count":len(keyword_reachable),
            "endpoint_like_reachable_count":len(endpoint_like),
        },
        "adjudication":{
            "bse_official_disclosure_surface":"SUPPORTED" if keyword_reachable else "NOT VERIFIED",
            "bse_machine_query_endpoint":"SUPPORTED" if endpoint_like else "NOT VERIFIED",
            "bse_historical_st_event_corpus":"NOT VERIFIED",
            "bse_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":"Discovery only. Reachable pages or endpoint-like URLs do not prove query semantics, completeness, daily ST identity, suspension state, or point-in-time reconstruction.",
    }
    Path("stock_bse_official_disclosure_discovery.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    # Discovery surface is useful even if no machine endpoint is found.
    return 0 if report["adjudication"]["bse_official_disclosure_surface"]=="SUPPORTED" else 2


if __name__=="__main__":
    raise SystemExit(main())
