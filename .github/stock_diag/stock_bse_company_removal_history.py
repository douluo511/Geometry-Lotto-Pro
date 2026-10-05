from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "stock_bse_company_announcement_contract.py"
OUT = Path("stock_bse_company_removal_history.json")
CANONICAL_CODES = ["920023", "920090", "920305", "920575", "920680"]
START = "2018-01-01"
END = "2026-09-30"
DISCLOSURE_TYPE = "5"
REMOVAL_TOKENS = (
    "撤销退市风险警示",
    "撤销股票退市风险警示",
    "取消退市风险警示",
    "终止实施退市风险警示",
    "不再实施退市风险警示",
    "撤销其他风险警示",
    "取消其他风险警示",
    "终止实施其他风险警示",
    "不再实施其他风险警示",
)

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def canonical_sha(rows) -> str:
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()

def row_identity(r):
    return (
        str(r.get("companyCd") or "").strip(),
        str(r.get("publishDate") or "").strip(),
        str(r.get("disclosureTitle") or ""),
        str(r.get("disclosurePostTitle") or ""),
        str(r.get("destFilePath") or ""),
    )

def main() -> int:
    c = load_module("contract", CONTRACT_PATH)
    session = requests.Session()
    mapping, mapping_meta = c.fetch_code_mapping(session)
    aliases = {code: [code] + list(mapping.get(code, [])) for code in CANONICAL_CODES}
    all_rows = {}
    per_company = []
    all_transport = mapping_meta.get("parse") == "PASS"

    for canonical in CANONICAL_CODES:
        rows = {}
        receipts = []
        company_transport = True
        query_codes = aliases[canonical]

        for query_code in query_codes:
            base = {
                "callback": "stockAiBseCb",
                "disclosureType": "",
                "disclosureSubtype": "",
                "page": 0,
                "companyCd": query_code,
                "isNewThree": 1,
                "startTime": START,
                "endTime": END,
                "keyword": "",
                "hyType": "",
            }

            page0 = list(base.items())
            page0 += [("disclosureType[]", DISCLOSURE_TYPE), ("xxfcbj[]", "2")]
            page0 += [("needFields[]", field) for field in c.NEED_FIELDS]
            obj0, meta0 = c.request_variant(session, f"{canonical}_{query_code}_page_0", "POST", page0)
            rec0 = c.find_records(obj0) if obj0 is not None else []
            pm0 = c.list_info_meta(obj0) if obj0 is not None else {}
            total_pages = pm0.get("totalPages")
            total_elements = pm0.get("totalElements")
            ok0 = (
                meta0.get("status") == 200
                and meta0.get("same_official_host") is True
                and meta0.get("parse") == "PASS"
                and isinstance(total_pages, int)
                and isinstance(total_elements, int)
                and 0 <= total_pages <= 200
                and pm0.get("number") == 0
            )
            company_transport = company_transport and ok0
            receipts.append({
                "query_code": query_code,
                "page": 0,
                "status": "PASS" if ok0 else "FAIL",
                "total_pages": total_pages,
                "total_elements": total_elements,
                "record_count": len(rec0),
                "transport_sha256": meta0.get("sha256"),
            })
            if not ok0:
                continue

            for r in rec0:
                if str(r.get("companyCd") or "").strip() == query_code:
                    rows[row_identity(r)] = r

            for page_no in range(1, total_pages):
                params = dict(base)
                params["page"] = page_no
                pairs = list(params.items())
                pairs += [("disclosureType[]", DISCLOSURE_TYPE), ("xxfcbj[]", "2")]
                pairs += [("needFields[]", field) for field in c.NEED_FIELDS]
                obj, meta = c.request_variant(session, f"{canonical}_{query_code}_page_{page_no}", "POST", pairs)
                recs = c.find_records(obj) if obj is not None else []
                pm = c.list_info_meta(obj) if obj is not None else {}
                pok = (
                    meta.get("status") == 200
                    and meta.get("same_official_host") is True
                    and meta.get("parse") == "PASS"
                    and pm.get("number") == page_no
                    and pm.get("totalPages") == total_pages
                    and pm.get("totalElements") == total_elements
                )
                company_transport = company_transport and pok
                receipts.append({
                    "query_code": query_code,
                    "page": page_no,
                    "status": "PASS" if pok else "FAIL",
                    "record_count": len(recs),
                    "transport_sha256": meta.get("sha256"),
                })
                for r in recs:
                    if str(r.get("companyCd") or "").strip() == query_code:
                        rows[row_identity(r)] = r

            params = dict(base)
            params["page"] = total_pages
            pairs = list(params.items())
            pairs += [("disclosureType[]", DISCLOSURE_TYPE), ("xxfcbj[]", "2")]
            pairs += [("needFields[]", field) for field in c.NEED_FIELDS]
            objn, metan = c.request_variant(session, f"{canonical}_{query_code}_page_n_plus_1", "POST", pairs)
            recn = c.find_records(objn) if objn is not None else []
            nplus = metan.get("status") == 200 and metan.get("parse") == "PASS" and len(recn) == 0
            company_transport = company_transport and nplus
            receipts.append({
                "query_code": query_code,
                "page": total_pages,
                "status": "PASS" if nplus else "FAIL",
                "n_plus_one": True,
                "record_count": len(recn),
                "transport_sha256": metan.get("sha256"),
            })

        canonical_rows = []
        removal_rows = []
        for key in sorted(rows):
            r = rows[key]
            raw_code = str(r.get("companyCd") or "").strip()
            title = str(r.get("disclosureTitle") or "") + str(r.get("disclosurePostTitle") or "")
            item = {
                "canonical_company_code": canonical,
                "raw_company_code": raw_code,
                "companyName": r.get("companyName"),
                "publishDate": r.get("publishDate"),
                "title": title,
                "destFilePath": r.get("destFilePath"),
                "fileExt": r.get("fileExt"),
            }
            canonical_rows.append(item)
            all_rows[(canonical,) + row_identity(r)] = item
            if any(token in title for token in REMOVAL_TOKENS):
                removal_rows.append(item)

        per_company.append({
            "canonical_company_code": canonical,
            "query_codes": query_codes,
            "transport_pagination": "PASS" if company_transport else "NOT VERIFIED",
            "risk_warning_category_row_count": len(canonical_rows),
            "risk_warning_category_sha256": canonical_sha(canonical_rows),
            "removal_candidate_count": len(removal_rows),
            "removal_candidates": removal_rows,
            "receipts": receipts,
        })
        all_transport = all_transport and company_transport

    combined = [all_rows[k] for k in sorted(all_rows)]
    removal = [
        row for row in combined
        if any(token in str(row.get("title") or "") for token in REMOVAL_TOKENS)
    ]
    no_removal_within_frozen_scope = all_transport and len(removal) == 0

    report = {
        "schema": "stock-bse-company-removal-history-v1",
        "window": {"start": START, "end": END},
        "disclosure_type": DISCLOSURE_TYPE,
        "canonical_codes": CANONICAL_CODES,
        "official_code_mapping_transport": mapping_meta,
        "per_company": per_company,
        "combined_row_count": len(combined),
        "combined_sha256": canonical_sha(combined),
        "removal_candidate_count": len(removal),
        "removal_candidates": removal,
        "adjudication": {
            "known_implementation_company_type5_pagination": "PASS" if all_transport else "NOT VERIFIED",
            "no_removal_announcement_within_known_type5_scope": "SUPPORTED" if no_removal_within_frozen_scope else "NOT VERIFIED",
            "bse_removal_event_history_complete": "NOT VERIFIED",
            "bse_effective_state_reconstruction": "NOT VERIFIED",
            "bse_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This exhausts disclosureType=5 announcements for the five companies with validated initial BSE "
            "risk-warning implementation events, including first-party old-code aliases, across the frozen window. "
            "A zero removal result is supported only within this exact company/type/window scope; it does not prove "
            "that every possible BSE removal disclosure type or vocabulary has been exhausted."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "per_company": [
            {
                "code": x["canonical_company_code"],
                "transport": x["transport_pagination"],
                "rows": x["risk_warning_category_row_count"],
                "removal_candidates": x["removal_candidate_count"],
            }
            for x in per_company
        ],
        "combined_row_count": len(combined),
        "removal_candidate_count": len(removal),
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if all_transport else 2

if __name__ == "__main__":
    raise SystemExit(main())
