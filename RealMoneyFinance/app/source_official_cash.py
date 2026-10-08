"""Read original issuer PDFs; present-day download receipts do not prove past availability."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import hashlib
import io
import re
import time
from urllib.parse import urlparse
from pypdf import PdfReader

# URLs are reviewed original issuer documents, not mirrors. The 2022 convertible
# adjustment notice is retained as corroboration, never an ordinary-share proof.
OFFICIAL_CASH_DOCUMENTS = [
    ("2022-07-21","2022-07-12","0.41","convertible_cash_corroboration",
     "https://news.spdb.com.cn/investor_relation/company_report/202207/P020220712640732257009.pdf"),
    ("2023-07-21","2023-07-12","0.32","ordinary_cash_implementation",
     "https://news.spdb.com.cn/investor_relation/company_report/202307/P020230712640521382645.pdf"),
    ("2024-07-18","2024-07-10","0.321","ordinary_cash_implementation",
     "https://news.spdb.com.cn/investor_relation/company_report/202407/P020240710607607691605.pdf"),
    ("2025-07-16","2025-07-09","0.41","ordinary_cash_implementation",
     "https://news.spdb.com.cn/investor_relation/company_report/202507/P020250709652132836194.pdf"),
]

def parse_cash_document(body, *, url, expected_ex_date, expected_published_date,
                        expected_cash_per_share, document_kind):
    if not isinstance(body,bytes) or not body.startswith(b"%PDF-") or len(body)>2_000_000:
        raise ValueError("issuer cash PDF is malformed or exceeds bounded size")
    reader=PdfReader(io.BytesIO(body),strict=True)
    if reader.is_encrypted or not 1<=len(reader.pages)<=6:
        raise ValueError("issuer cash PDF must be an unencrypted short original notice")
    text="\n".join(page.extract_text() or "" for page in reader.pages)
    compact=re.sub(r"\s+","",text)
    if "上海浦东发展银行股份有限公司" not in compact or "600000" not in compact:
        raise ValueError("issuer cash PDF product/symbol identity mismatch")
    # Read the gross cash amount explicitly labelled per share. Never use a
    # net-of-tax amount or silently interpret a per-ten-share value as per share.
    cash_values=re.findall(r"每股(?:现金红利(?:人民币)?|派发现金红利(?:人民币)?|分配现金股利(?:人民币)?)([0-9]+(?:\.[0-9]+)?)元",compact)
    wanted=Decimal(str(expected_cash_per_share))
    cash_ok=any(Decimal(value)==wanted for value in cash_values)
    publication=f"{date.fromisoformat(expected_published_date).year}年{date.fromisoformat(expected_published_date).month}月{date.fromisoformat(expected_published_date).day}日"
    ex=date.fromisoformat(expected_ex_date)
    ex_tokens=(f"{ex.year}/{ex.month}/{ex.day}",f"{ex.year}年{ex.month}月{ex.day}日")
    ordinary=("权益分派实施公告" in compact and "差异化分红送转：否" in compact)
    exact_ex=any(token in compact for token in ex_tokens)
    result={
        "symbol":"600000","url":url,"payload_sha256":hashlib.sha256(body).hexdigest(),
        "pdf_bytes":len(body),"extracted_text_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "document_kind":document_kind,"published_date":expected_published_date,
        "ex_dividend_date":expected_ex_date,"cash_per_share":float(wanted),"cash_unit":"CNY_PER_SHARE",
        "document_cash_match":"PASS" if cash_ok else "NOT VERIFIED",
        "document_date_match":"PASS" if ordinary and exact_ex and publication in compact
                              and document_kind=="ordinary_cash_implementation" else "NOT VERIFIED",
        "publication_date_printed_match":"PASS" if publication in compact else "NOT VERIFIED",
        "historical_asof_availability":"NOT VERIFIED",
        "boundary":"Bytes read now plus dates printed in the document do not prove immutable past-asof availability.",
    }
    if not cash_ok:result["reason"]="explicit gross per-share cash field did not match"
    return result

def fetch_official_cash_documents(client):
    evidence=[]
    for ex,published,cash,kind,url in OFFICIAL_CASH_DOCUMENTS:
        last=None
        for attempt in range(1,client.max_attempts+1):
            response=None
            try:
                response=client.session.get(url,timeout=(client.connect_timeout,client.read_timeout),
                    headers={"User-Agent":"Mozilla/5.0","Accept":"application/pdf"},stream=True,
                    allow_redirects=True)
                response.raise_for_status()
                final=urlparse(str(response.url))
                if (final.scheme!="https" or final.hostname!="news.spdb.com.cn"
                        or str(response.url)!=url):
                    raise ValueError("issuer PDF redirected outside exact reviewed URL")
                ctype=str(response.headers.get("content-type","")).lower()
                if "pdf" not in ctype and "octet-stream" not in ctype:
                    raise ValueError("issuer PDF Content-Type mismatch")
                chunks=[];size=0
                for block in response.iter_content(65536):
                    size+=len(block)
                    if size>2_000_000:raise ValueError("issuer PDF exceeds size bound")
                    chunks.append(block)
                body=b"".join(chunks)
                result=parse_cash_document(body,url=url,expected_ex_date=ex,
                    expected_published_date=published,expected_cash_per_share=cash,document_kind=kind)
                result.update({"retrieved_at_unix":time.time(),"http_status":response.status_code,
                               "content_type":ctype,"attempt":attempt})
                client._record({"status":"PASS","url":url,"payload_sha256":result["payload_sha256"],
                                "document_kind":kind,"content_type":ctype,"attempt":attempt,
                                "scope":"CURRENT_OFFICIAL_PDF_READ_ONLY"})
                evidence.append(result);break
            except Exception as exc:
                last=repr(exc)
                client._record({"status":"FAIL","url":url,"attempt":attempt,"error":last})
                if attempt>=client.max_attempts:
                    evidence.append({"symbol":"600000","url":url,"ex_dividend_date":ex,
                        "document_kind":kind,"status":"NOT VERIFIED","error":last,
                        "historical_asof_availability":"NOT VERIFIED"})
                else:time.sleep(client.backoff_base*(2**(attempt-1)))
            finally:
                if response is not None:response.close()
    return evidence
