from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import requests

OUT = Path("stock_bse_suspension_marketwide_corpus.json")
PROBE_PATH = Path(".github/stock_diag/stock_bse_marketwide_pagination_probe.py")
CONTRACT_PATH = Path(".github/stock_diag/stock_bse_company_announcement_contract.py")
KEYWORDS = ["停牌", "复牌", "停复牌"]


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


def row_view(r, old_to_new):
    raw_code = str(r.get("companyCd") or "").strip()
    title = str(r.get("disclosureTitle") or "") + str(r.get("disclosurePostTitle") or "")
    return {
        "raw_company_code": raw_code,
        "canonical_company_code": old_to_new.get(raw_code, raw_code),
        "companyName": r.get("companyName"),
        "publishDate": r.get("publishDate"),
        "title": title,
        "destFilePath": r.get("destFilePath"),
        "fileExt": r.get("fileExt"),
        "xxzrlx": r.get("xxzrlx"),
    }


def page_ok(summary, expected_page, total_pages, total_elements):
    t = summary["transport"]
    pm = summary["page_meta"]
    return (
        t.get("status") == 200
        and t.get("same_official_host") is True
        and t.get("parse") == "PASS"
        and pm.get("number") == expected_page
        and pm.get("totalPages") == total_pages
        and pm.get("totalElements") == total_elements
        and pm.get("numberOfElements") == summary["record_count"]
    )


def main() -> int:
    probe = load_module("bse_probe", PROBE_PATH)
    contract = load_module("bse_contract", CONTRACT_PATH)
    session = requests.Session()

    type_obj, type_transport = probe.request_json(session, probe.TYPE_ENDPOINT, params={"type": 6})
    type_values = probe.collect_type_values(type_obj) if type_obj is not None else []
    type_5_present = "5" in type_values

    code_mapping, mapping_transport = contract.fetch_code_mapping(session)
    old_to_new = {}
    for new_code, old_codes in code_mapping.items():
        for old_code in old_codes:
            if old_code in old_to_new and old_to_new[old_code] != new_code:
                raise RuntimeError(f"ambiguous BSE old code mapping: {old_code}")
            old_to_new[old_code] = new_code

    all_query_pass = (
        type_5_present
        and type_transport.get("parse") == "PASS"
        and mapping_transport.get("parse") == "PASS"
    )
    per_keyword = []
    combined = {}

    for keyword in KEYWORDS:
        obj0, t0 = probe.request_page(session, keyword, 0)
        s0 = probe.summarize(obj0, t0, keyword)
        pm0 = s0["page_meta"]
        if not (
            t0.get("status") == 200
            and t0.get("same_official_host") is True
            and t0.get("parse") == "PASS"
            and isinstance(pm0.get("totalPages"), int)
            and isinstance(pm0.get("totalElements"), int)
            and pm0.get("number") == 0
        ):
            per_keyword.append({
                "keyword": keyword,
                "status": "NOT VERIFIED",
                "reason": "page0 contract failed",
                "page0": s0,
            })
            all_query_pass = False
            continue

        total_pages = int(pm0["totalPages"])
        total_elements = int(pm0["totalElements"])
        if total_pages < 0 or total_elements < 0 or total_pages > 1000:
            per_keyword.append({
                "keyword": keyword,
                "status": "NOT VERIFIED",
                "reason": "unsafe denominator",
                "total_pages": total_pages,
                "total_elements": total_elements,
            })
            all_query_pass = False
            continue

        raw_by_id = {}
        receipts = []
        query_pass = True

        for page_no in range(total_pages):
            if page_no == 0:
                obj, transport, summary = obj0, t0, s0
            else:
                obj, transport = probe.request_page(session, keyword, page_no)
                summary = probe.summarize(obj, transport, keyword)
            ok = page_ok(summary, page_no, total_pages, total_elements)
            query_pass = query_pass and ok
            records = probe.find_records(obj) if obj is not None else []
            receipts.append({
                "page": page_no,
                "status": "PASS" if ok else "FAIL",
                "record_count": len(records),
                "payload_sha256": transport.get("sha256"),
                "numberOfElements": summary["page_meta"].get("numberOfElements"),
            })
            for r in records:
                raw_by_id[row_identity(r)] = r

        objn, tn = probe.request_page(session, keyword, total_pages)
        sn = probe.summarize(objn, tn, keyword)
        n_plus_one_pass = (
            tn.get("status") == 200
            and tn.get("same_official_host") is True
            and tn.get("parse") == "PASS"
            and sn["record_count"] == 0
        )
        query_pass = query_pass and n_plus_one_pass
        denominator_match = len(raw_by_id) == total_elements
        query_pass = query_pass and denominator_match

        rows = [row_view(raw_by_id[k], old_to_new) for k in sorted(raw_by_id)]
        title_rows = [r for r in rows if keyword in r["title"]]
        for r in title_rows:
            key = (
                r["raw_company_code"],
                str(r["publishDate"]),
                r["title"],
                str(r["destFilePath"]),
            )
            combined[key] = r

        per_keyword.append({
            "keyword": keyword,
            "status": "PASS" if query_pass else "NOT VERIFIED",
            "total_pages": total_pages,
            "total_elements": total_elements,
            "unique_row_count": len(rows),
            "row_count_matches_denominator": denominator_match,
            "n_plus_one_empty": n_plus_one_pass,
            "title_keyword_event_count": len(title_rows),
            "canonical_query_sha256": canonical_sha(rows),
            "canonical_title_event_sha256": canonical_sha(title_rows),
            "page_receipts": receipts,
            "title_event_sample": title_rows[:20],
        })
        all_query_pass = all_query_pass and query_pass

    combined_rows = [combined[k] for k in sorted(combined)]
    event_supported = all_query_pass and len(combined_rows) > 0

    adjudication = {
        "bse_suspension_query_pagination": "PASS" if all_query_pass else "NOT VERIFIED",
        "exhaustive_bse_suspension_keyword_query_corpus": "SUPPORTED" if all_query_pass else "NOT VERIFIED",
        "bse_suspension_title_event_corpus": "SUPPORTED" if event_supported else "NOT VERIFIED",
        "bse_suspension_event_semantics_complete": "NOT VERIFIED",
        "bse_effective_daily_suspension_state": "NOT VERIFIED",
        "bse_historical_suspension_pit": "NOT VERIFIED",
        "bse_historical_st_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "product_bytes_changed": False,
        "final_gate": "FAIL",
    }

    report = {
        "schema": "stock-bse-suspension-marketwide-corpus-v1",
        "window": {"start": probe.START, "end": probe.END},
        "endpoint": probe.ENDPOINT,
        "keywords": KEYWORDS,
        "official_type_5_present": type_5_present,
        "type_transport": type_transport,
        "code_mapping_transport": mapping_transport,
        "per_keyword": per_keyword,
        "combined_unique_title_event_count": len(combined_rows),
        "combined_unique_company_count": len({r["canonical_company_code"] for r in combined_rows}),
        "combined_canonical_sha256": canonical_sha(combined_rows),
        "combined_events": combined_rows,
        "adjudication": adjudication,
        "boundary": (
            "This exhausts the official BSE announcement query for the frozen suspension keywords "
            "under the already validated disclosureType=5 contract and server denominators. "
            "Announcement titles/publication dates are event-source evidence only; they are not "
            "effective suspension/resumption dates or a complete daily suspension PIT state."
        ),
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "keyword_statuses": {x["keyword"]: x["status"] for x in per_keyword},
        "keyword_denominators": {
            x["keyword"]: {"pages": x.get("total_pages"), "elements": x.get("total_elements")}
            for x in per_keyword
        },
        "combined_unique_title_event_count": report["combined_unique_title_event_count"],
        "combined_unique_company_count": report["combined_unique_company_count"],
        "combined_canonical_sha256": report["combined_canonical_sha256"],
        "adjudication": adjudication,
    }, ensure_ascii=True, sort_keys=True))

    return 0 if all_query_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
